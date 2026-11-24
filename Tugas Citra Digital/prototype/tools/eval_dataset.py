"""Ukur akurasi lokalisasi detect_plates + validasi OCR NRKB pada dataset YOLO nyata.

Ground truth: ``<dataset>/<split>/labels/*.txt`` (kelas tunggal ``number-plate``).
Metrik: precision / recall / F1 @ IoU ambang, rata-rata IoU pasangan terbaik,
Valid Format OCR Rate (Perpol No. 7 Tahun 2021), serta latensi per citra.

Jalankan::

    python tools\\eval_dataset.py            # valid + test pada plat-nomor/
    python tools\\eval_dataset.py --dataset "D:\\Project\\Smart Gate System\\Tugas Citra Digital\\prototype\\plat-nomor" --split test
    python tools\\eval_dataset.py --split test --limit 20
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DATASET = ROOT / "plat-nomor"
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp")


def read_labels(label_path: pathlib.Path, width: int, height: int) -> list[list[float]]:
    """YOLO xywh ternormalisasi -> kotak piksel [x1, y1, x2, y2]."""
    boxes: list[list[float]] = []
    if not label_path.exists():
        return boxes
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        _, cx, cy, bw, bh = (float(v) for v in parts[:5])
        x1 = (cx - bw / 2) * width
        y1 = (cy - bh / 2) * height
        x2 = (cx + bw / 2) * width
        y2 = (cy + bh / 2) * height
        boxes.append([x1, y1, x2, y2])
    return boxes


def quad_bounds(quad) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def iou(a: tuple[float, float, float, float], b: list[float] | tuple[float, float, float, float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def evaluate(
    split: str,
    limit: int | None,
    threshold: float,
    quiet: bool,
    *,
    dataset_dir: pathlib.Path = DEFAULT_DATASET,
    with_ocr: bool = True,
) -> dict:
    import cv2

    from app import detect_yolo, ocr, pipeline

    backend = detect_yolo.status()
    if not quiet:
        print(f"dataset: {dataset_dir} | split: {split} | backend deteksi: {backend} | OCR: {ocr.active_backend()}")

    img_dir = dataset_dir / split / "images"
    lbl_dir = dataset_dir / split / "labels"
    images = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT)
    if limit:
        images = images[:limit]

    tp = fp = fn = 0
    best_ious: list[float] = []
    latencies: list[float] = []
    misses: list[str] = []
    ocr_tested = 0
    ocr_valid = 0
    sample_reads: list[dict] = []

    for path in images:
        image = cv2.imread(str(path))
        if image is None:
            continue
        h, w = image.shape[:2]
        truth = read_labels(lbl_dir / f"{path.stem}.txt", w, h)

        t0 = time.perf_counter()
        detections = pipeline.detect_plates(image)
        if with_ocr and detections:
            primary_det = detections[0]
            raw_crop = primary_det.meta.get("raw_crop")
            crop = raw_crop if getattr(raw_crop, "size", 0) else primary_det.crop
            plate_text, plate_conf, ocr_be = ocr.read_plate_robust(
                crop, primary_det.meta.get("vehicle_class"), fast=True
            )
            ocr_tested += 1
            is_valid = ocr._looks_like_plate(plate_text)
            if is_valid:
                ocr_valid += 1
            if len(sample_reads) < 10:
                sample_reads.append(
                    {
                        "file": path.name,
                        "plate": plate_text,
                        "conf": round(plate_conf, 4),
                        "valid": is_valid,
                        "backend": ocr_be,
                    }
                )
        latencies.append((time.perf_counter() - t0) * 1000.0)

        predicted = [quad_bounds(d.quad) for d in detections]
        used: set[int] = set()
        paired = 0
        for box in truth:
            best_i, best_v = -1, 0.0
            for i, pred in enumerate(predicted):
                if i in used:
                    continue
                value = iou(pred, box)
                if value > best_v:
                    best_i, best_v = i, value
            if best_i >= 0 and best_v >= threshold:
                used.add(best_i)
                paired += 1
                best_ious.append(best_v)
            else:
                fn += 1
                if not quiet:
                    misses.append(f"{path.name} iou={best_v:.2f}")
        tp += paired
        fp += len(predicted) - paired

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    ocr_valid_rate = ocr_valid / ocr_tested if ocr_tested else 0.0

    return {
        "dataset": str(dataset_dir),
        "split": split,
        "images": len(images),
        "gt_boxes": tp + fn,
        "detected": tp + fp,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "iou_median": round(statistics.median(best_ious), 4) if best_ious else 0.0,
        "iou_mean": round(statistics.fmean(best_ious), 4) if best_ious else 0.0,
        "ocr_tested": ocr_tested,
        "ocr_valid": ocr_valid,
        "ocr_valid_rate": round(ocr_valid_rate, 4),
        "sample_reads": sample_reads,
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else 0.0,
        "latency_ms_p90": (
            round(sorted(latencies)[int(len(latencies) * 0.9)], 1) if latencies else 0.0
        ),
        "misses": misses[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=pathlib.Path,
        default=DEFAULT_DATASET,
        help="Path folder dataset YOLO (default: prototype/plat-nomor)",
    )
    parser.add_argument("--split", default="valid,test", help="valid / test / train (pisah koma)")
    parser.add_argument("--limit", type=int, default=None, help="batasi jumlah citra per split")
    parser.add_argument("--iou", type=float, default=0.5, help="ambang IoU untuk TP")
    parser.add_argument("--no-ocr", action="store_true", help="lewati pengujian OCR pada crop terdeteksi")
    parser.add_argument("--json", type=pathlib.Path, default=None, help="tulis hasil ke file JSON")
    parser.add_argument("--quiet", action="store_true", help="jangan cetak daftar kegagalan")
    args = parser.parse_args()

    dataset_dir = args.dataset.resolve()
    if not dataset_dir.exists():
        print(f"dataset tidak ada: {dataset_dir}", file=sys.stderr)
        return 2

    reports = [
        evaluate(
            s.strip(),
            args.limit,
            args.iou,
            args.quiet,
            dataset_dir=dataset_dir,
            with_ocr=not args.no_ocr,
        )
        for s in args.split.split(",")
        if s.strip()
    ]
    for rep in reports:
        ocr_str = (
            f" OCR_valid={rep['ocr_valid_rate']:.1%}({rep['ocr_valid']}/{rep['ocr_tested']})"
            if not args.no_ocr
            else ""
        )
        print(
            f"[{rep['split']:5}] img={rep['images']:4} gt={rep['gt_boxes']:4} "
            f"P={rep['precision']:.3f} R={rep['recall']:.3f} F1={rep['f1']:.3f} "
            f"IoU(med)={rep['iou_median']:.3f}{ocr_str} "
            f"lat(med/p90)={rep['latency_ms_median']:.0f}/{rep['latency_ms_p90']:.0f} ms "
            f"(tp={rep['tp']} fp={rep['fp']} fn={rep['fn']})"
        )
        if rep["sample_reads"] and not args.quiet:
            for sr in rep["sample_reads"][:6]:
                mark = "OK " if sr["valid"] else "---"
                print(f"    ocr [{mark}] {sr['file']}: {sr['plate'] or '-'} (conf={sr['conf']:.2f}, {sr['backend']})")
        for miss in rep["misses"]:
            print(f"    miss: {miss}")

    if args.json:
        args.json.write_text(json.dumps(reports, indent=2), encoding="utf-8")
        print(f"-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
