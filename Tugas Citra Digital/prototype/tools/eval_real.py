"""Ukur akurasi lokalisasi + OCR pada dataset nyata (``Datasheet 2``).

Jalankan::

    python tools\\eval_real.py                 # deteksi + OCR
    python tools\\eval_real.py --part detect --limit 200
    python tools\\eval_real.py --part ocr --limit 200 --save-csv data/ocr_eval.csv
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import dataset  # noqa: E402


def box_iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def quad_box(quad) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def eval_detect(limit: int | None, threshold: float) -> dict:
    import cv2

    from app import detect_yolo, pipeline

    tp = fp = fn = 0
    best_ious: list[float] = []
    latencies: list[float] = []
    worst: list[tuple[float, str]] = []
    images = 0

    for sample in dataset.detection_samples(limit):
        image = cv2.imread(str(sample.path))
        if image is None or not sample.boxes:
            continue
        images += 1
        start = time.perf_counter()
        detected = [quad_box(d.quad) for d in pipeline.detect_plates(image)]
        latencies.append((time.perf_counter() - start) * 1000.0)

        used: set[int] = set()
        for truth in sample.boxes:
            best_i, best_v = -1, 0.0
            for index, box in enumerate(detected):
                if index in used:
                    continue
                value = box_iou(box, truth)
                if value > best_v:
                    best_i, best_v = index, value
            if best_i >= 0 and best_v >= threshold:
                used.add(best_i)
                tp += 1
                best_ious.append(best_v)
            else:
                fn += 1
                worst.append((best_v, sample.path.name))
        fp += len(detected) - len(used)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    worst.sort()
    return {
        "images": images,
        "backend": detect_yolo.status()["backend"],
        "gt": tp + fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "iou_median": round(statistics.median(best_ious), 4) if best_ious else 0.0,
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else 0.0,
        "worst": worst[:15],
    }


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def eval_ocr(limit: int | None, save_csv: pathlib.Path | None) -> dict:
    import cv2

    from app import ocr

    exact = 0
    char_hits = char_total = 0
    rows: list[tuple[str, str, str, float]] = []
    latencies: list[float] = []

    for path, truth in dataset.text_samples(limit):
        image = cv2.imread(str(path))
        if image is None:
            continue
        start = time.perf_counter()
        text, confidence, _ = ocr.read_plate(image)
        latencies.append((time.perf_counter() - start) * 1000.0)
        got, want = _normalize(text), _normalize(truth)
        exact += int(got == want)
        # Levenshtein-lite: hitung irisan posisi sejajar (cukup untuk tren).
        char_hits += sum(1 for a, b in zip(got, want) if a == b)
        char_total += max(len(want), 1)
        rows.append((path.name, truth, text, round(confidence, 4)))

    total = len(rows)
    return {
        "images": total,
        "backend": ocr.active_backend(),
        "exact_match": round(exact / total, 4) if total else 0.0,
        "char_alignment": round(char_hits / char_total, 4) if char_total else 0.0,
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else 0.0,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default="both", choices=("detect", "ocr", "both"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--save-csv", type=pathlib.Path, default=None)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    args = parser.parse_args()

    summary: dict[str, dict] = {}

    if args.part in ("detect", "both"):
        if not dataset.detection_available():
            print("dataset lokalisasi tidak ada", file=sys.stderr)
        else:
            rep = eval_detect(args.limit, args.iou)
            summary["detect"] = {k: v for k, v in rep.items() if k != "worst"}
            print(
                f"[detect] citra={rep['images']} backend={rep['backend']} gt={rep['gt']} "
                f"P={rep['precision']:.3f} R={rep['recall']:.3f} F1={rep['f1']:.3f} "
                f"IoU(med)={rep['iou_median']:.3f} lat={rep['latency_ms_median']:.0f}ms"
            )
            for value, name in rep["worst"][:8]:
                print(f"    gagal: {name} (IoU terbaik {value:.2f})")

    if args.part in ("ocr", "both"):
        if not dataset.text_available():
            print("dataset teks plat tidak ada", file=sys.stderr)
        else:
            rep = eval_ocr(args.limit, args.save_csv)
            summary["ocr"] = {k: v for k, v in rep.items() if k != "rows"}
            print(
                f"[ocr] citra={rep['images']} backend={rep['backend']} "
                f"exact={rep['exact_match']:.3f} char_align={rep['char_alignment']:.3f} "
                f"lat={rep['latency_ms_median']:.0f}ms"
            )
            for name, truth, got, conf in rep["rows"][:8]:
                mark = "ok " if _normalize(got) == _normalize(truth) else "   "
                print(f"    {mark} {name}: mau={truth} dapat={got} ({conf:.2f})")
            if args.save_csv:
                args.save_csv.parent.mkdir(parents=True, exist_ok=True)
                with args.save_csv.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["file", "ground_truth", "predicted", "confidence"])
                    writer.writerows(rep["rows"])
                print(f"-> {args.save_csv}")

    if args.json:
        import json

        args.json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
