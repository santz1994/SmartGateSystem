"""Backend deteksi plat berbasis YOLO (opsional).

Pipeline OpenCV klasik di :mod:`app.pipeline` tetap dipakai sebagai *fallback*
CPU. Modul ini menyalakan jalur akurasi tinggi hanya bila pengguna memasang
``ultralytics`` **dan** menunjuk file bobot hasil training:

.. code-block:: powershell

    $env:SGS_YOLO_WEIGHTS = "$PWD\\runs\\detect\\train\\weights\\best.pt"
    python run.py

Kontrak keluaran disamakan dengan :func:`app.pipeline.detect_plates` supaya
seluruh lapisan di atasnya (OCR, fusi, log) tidak perlu tahu backend mana yang
aktif. Bobot belum ada -> :func:`available` mengembalikan ``False`` dan pipeline
klasik yang jalan; jadi tidak ada dependensi baru yang wajib dipasang.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config
from . import vehicles
from .pipeline import (
    Detection,
    four_point_transform,
    normalize_plate_size,
    order_points,
    plate_plausibility,
    plate_texture_ok,
    snap_to_text_band,
    plate_border_score,
    pad_crop,
)

ENV_VAR = "SGS_YOLO_WEIGHTS"
# Threshold awal dibuat lebih rendah agar plat motor kecil/blur tetap masuk ke
# quality gate; validasi geometri, tekstur, dan glyph tetap menentukan kelolosan.
DEFAULT_CONF = 0.10
MIN_PLAUSIBILITY = 0.10
OCR_PADDING_X = 0.08
OCR_PADDING_Y = 0.12
MAX_BOX_AREA_RATIO = 0.15
ASPECT_RANGES = {
    # Box YOLO bersifat axis-aligned; perspektif dapat menurunkan rasio
    # plat motor yang sebenarnya sekitar 2.4 menjadi sekitar 1.2.
    "motorcycle": (1.20, 3.80),
    "car": (1.80, 5.00),
    "truck": (1.30, 5.00),
    "custom": (1.20, 5.00),
}


VARIANT_ENV = "SGS_YOLO_VARIANT"
ONNX_ENV = "SGS_USE_ONNX"
VARIANTS: dict[str, str] = {
    "yolo11n": "runs/detect/smartgate-colab-v6-yolo11n/weights/best.pt",
    "yolov8n": "runs/detect/smartgate-colab-v6-yolov8n/weights/best.pt",
}
ONNX_VARIANTS: dict[str, str] = {
    "yolo11n": "runs/detect/smartgate-colab-v6-yolo11n/weights/best.onnx",
    "yolov8n": "runs/detect/smartgate-colab-v6-yolov8n/weights/best.onnx",
}
ARTIFACT_FALLBACKS: dict[str, Path] = {
    "yolo11n": config.REPO_ROOT / "smartgate-artifacts-Y11N" / "best.pt",
    "yolov8n": config.REPO_ROOT / "smartgate-artifacts-Y8N" / "best.pt",
}
ARTIFACT_ONNX_FALLBACKS: dict[str, Path] = {
    "yolo11n": config.REPO_ROOT / "smartgate-artifacts-Y11N" / "best.onnx",
    "yolov8n": config.REPO_ROOT / "smartgate-artifacts-Y8N" / "best.onnx",
}
_raw_variant = os.getenv(VARIANT_ENV, "yolov8n").strip()
_variant: str = _raw_variant if _raw_variant in VARIANTS else "yolov8n"


def _use_onnx() -> bool:
    """Aktif bila SGS_USE_ONNX!=0 dan backend ONNX (onnxruntime / cv2.dnn) tersedia."""
    enabled = os.getenv(ONNX_ENV, "1").strip().lower() not in {"0", "false", "no"}
    return enabled and config.onnx_backend_available()


def _onnx_runtime_name() -> str:
    return "onnxruntime" if config.onnxruntime_available() else "opencv-dnn-onnx"


class _OnnxYoloRunner:
    """Runner YOLOv8/YOLOv11 ``.onnx`` murni (tanpa ``torch`` / ``ultralytics``).

    Menghindari konflik DLL Windows antara PaddlePaddle dan ``torch\\lib\\shm.dll``
    sekaligus memangkas pemakaian RAM produksi CPU. Menggunakan ``onnxruntime``
    bila terpasang, atau ``cv2.dnn.readNetFromONNX`` bawaan OpenCV.
    """

    def __init__(self, weight_file: Path, imgsz: int = 640) -> None:
        self.path = weight_file
        self.imgsz = imgsz
        self.backend = "opencv-dnn-onnx"
        self._ort_session: Any = None
        self._ort_input_name: str = ""
        self._cv_net: Any = None

        if config.onnxruntime_available():
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = config.CPU_THREADS
            opts.inter_op_num_threads = 1
            self._ort_session = ort.InferenceSession(
                str(weight_file), sess_options=opts, providers=["CPUExecutionProvider"]
            )
            self._ort_input_name = self._ort_session.get_inputs()[0].name
            self.backend = "onnxruntime"
        else:
            import cv2

            self._cv_net = cv2.dnn.readNetFromONNX(str(weight_file))
            self.backend = "opencv-dnn-onnx"

    def predict_boxes(
        self, image: Any, conf: float = DEFAULT_CONF, iou: float = 0.45
    ) -> list[tuple[float, float, float, float, float, int]]:
        import cv2
        import numpy as np

        h, w = image.shape[:2]
        if h == 0 or w == 0:
            return []
        size = self.imgsz
        scale = min(size / float(w), size / float(h))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        pad_x = (size - new_w) // 2
        pad_y = (size - new_h) // 2
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

        blob = cv2.dnn.blobFromImage(
            canvas, 1.0 / 255.0, (size, size), swapRB=True, crop=False
        )
        if self._ort_session is not None:
            raw = self._ort_session.run(None, {self._ort_input_name: blob})[0]
        else:
            self._cv_net.setInput(blob)
            raw = self._cv_net.forward()

        preds = np.squeeze(raw, axis=0)
        if preds.ndim == 2 and preds.shape[0] < preds.shape[1]:
            preds = preds.T  # (8400, 4 + nc)
        if preds.ndim != 2 or preds.shape[1] < 5:
            return []

        cls_scores = preds[:, 4:]
        if cls_scores.shape[1] == 1:
            scores = cls_scores[:, 0]
            class_ids = np.zeros(len(scores), dtype=np.int32)
        else:
            class_ids = np.argmax(cls_scores, axis=1)
            scores = cls_scores[np.arange(len(preds)), class_ids]

        keep = scores >= conf
        if not np.any(keep):
            return []

        boxes_xywh = preds[keep, :4]
        scores_kept = scores[keep]
        classes_kept = class_ids[keep]

        cx, cy, bw, bh = (
            boxes_xywh[:, 0],
            boxes_xywh[:, 1],
            boxes_xywh[:, 2],
            boxes_xywh[:, 3],
        )
        x1 = np.clip((cx - bw * 0.5 - pad_x) / scale, 0.0, float(w))
        y1 = np.clip((cy - bh * 0.5 - pad_y) / scale, 0.0, float(h))
        x2 = np.clip((cx + bw * 0.5 - pad_x) / scale, 0.0, float(w))
        y2 = np.clip((cy + bh * 0.5 - pad_y) / scale, 0.0, float(h))

        nms_boxes = [
            [float(a), float(b), float(c - a), float(d - b)]
            for a, b, c, d in zip(x1, y1, x2, y2)
        ]
        indices = cv2.dnn.NMSBoxes(
            nms_boxes, scores_kept.astype(float).tolist(), float(conf), float(iou)
        )
        if len(indices) == 0:
            return []

        out: list[tuple[float, float, float, float, float, int]] = []
        for idx in np.asarray(indices).flatten():
            i = int(idx)
            out.append(
                (
                    float(x1[i]),
                    float(y1[i]),
                    float(x2[i]),
                    float(y2[i]),
                    float(scores_kept[i]),
                    int(classes_kept[i]),
                )
            )
        return out


def current_variant() -> str:
    return _variant


def set_variant(name: str) -> None:
    """Ganti model deteksi aktif (yolov8n vs yolo11n) dan muat ulang bobot."""
    global _variant
    if name not in VARIANTS:
        raise ValueError(f"Varian model tidak dikenal: {name}")
    _variant = name
    _model.cache_clear()


def _variant_candidates(name: str, prefer_onnx: bool) -> list[Path]:
    """Urutan kandidat bobot untuk satu varian (ONNX dulu bila diaktifkan)."""
    base = Path(__file__).resolve().parent.parent
    onnx_paths = [base / ONNX_VARIANTS[name], ARTIFACT_ONNX_FALLBACKS[name]]
    pt_paths = [base / VARIANTS[name], ARTIFACT_FALLBACKS[name]]
    return (onnx_paths + pt_paths) if prefer_onnx else pt_paths


def available_variants() -> dict[str, dict[str, Any]]:
    """Daftar varian + status bobot + metrik evaluasi, untuk halaman /training."""
    import json

    base = Path(__file__).resolve().parent.parent
    prefer_onnx = _use_onnx()
    out: dict[str, dict[str, Any]] = {}
    for name, relative in VARIANTS.items():
        candidate = base / relative
        artifact_candidate = ARTIFACT_FALLBACKS[name]
        candidates = _variant_candidates(name, prefer_onnx=prefer_onnx)
        active_file = next((p for p in candidates if p.is_file()), candidate)
        ready = active_file.is_file()
        info: dict[str, Any] = {
            "weights": str(active_file),
            "runtime": _onnx_runtime_name() if active_file.suffix.lower() == ".onnx" else "pytorch",
            "ready": ready,
            "size_mb": round(active_file.stat().st_size / 1e6, 1) if ready else 0,
        }
        summary_path = candidate.parent.parent / "evaluation_summary.json"
        if not summary_path.is_file():
            summary_path = artifact_candidate.parent / "evaluation_summary.json"
        if summary_path.is_file():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                bench = summary.get("ocr_and_gate_benchmark", {})
                info["metrics"] = {
                    "test_map50": summary.get("test", {}).get("mAP50"),
                    "test_map50_95": summary.get("test", {}).get("mAP50_95"),
                    "valid_format_rate": bench.get("valid_format_rate"),
                    "latency_avg_ms": bench.get("avg_end_to_end_latency_ms"),
                    "latency_p95_ms": bench.get("p95_end_to_end_latency_ms"),
                }
            except (OSError, ValueError):
                pass
        out[name] = info
    return out


def _default_weights(*, prefer_onnx: bool | None = None) -> Path | None:
    """Pilih bobot training v6: prioritaskan .onnx bila onnxruntime aktif, fallback .pt."""
    use_onnx = _use_onnx() if prefer_onnx is None else prefer_onnx
    candidates: list[Path] = _variant_candidates(_variant, prefer_onnx=use_onnx)
    for name in VARIANTS:
        if name != _variant:
            candidates.extend(_variant_candidates(name, prefer_onnx=use_onnx))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def weights_path() -> Path | None:
    """File bobot dari variabel lingkungan, bila ada dan benar-benar ada."""
    raw = os.getenv(ENV_VAR, "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_file() else None
    return _default_weights()


@lru_cache(maxsize=1)
def _model() -> Any | None:
    """Muat model sekali saja (lru_cache) & panaskan inferensi. ``None`` bila belum bisa dipakai.

    Untuk file ``.onnx``, pemuatan dilakukan murni lewat :class:`_OnnxYoloRunner`
    (``onnxruntime`` atau ``cv2.dnn``) **tanpa mengimpor ``torch``/``ultralytics``**
    sehingga bebas konflik DLL Windows dengan PaddlePaddle dan jauh lebih hemat RAM.
    """
    path = weights_path()
    if path is None:
        return None

    import numpy as np

    if path.suffix.lower() == ".onnx":
        try:
            runner = _OnnxYoloRunner(path)
            runner.predict_boxes(np.zeros((160, 160, 3), dtype=np.uint8), conf=DEFAULT_CONF)
            return runner
        except Exception:  # noqa: BLE001
            fallback_pt = _default_weights(prefer_onnx=False)
            if fallback_pt is None or fallback_pt == path:
                return None
            path = fallback_pt

    try:
        from ultralytics import YOLO
        import torch

        torch.set_num_threads(config.CPU_THREADS)
    except (ImportError, OSError):
        return None

    try:
        yolo = YOLO(str(path), task="detect")
        # Panggilan predict pertama melakukan Conv+BN fusion (~1,5-2 dtk di CPU);
        # lakukan saat warmup agar scan pertama pengguna langsung cepat.
        dummy = np.zeros((160, 160, 3), dtype=np.uint8)
        yolo.predict(dummy, conf=DEFAULT_CONF, imgsz=160, verbose=False)
        return yolo
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    return _model() is not None


def status() -> dict[str, Any]:
    """Info ringkas untuk halaman dashboard / API ``/api/health``."""
    path = weights_path()
    if path is None:
        return {"backend": "opencv", "yolo": False, "reason": f"{ENV_VAR} belum diisi"}
    model = _model()
    if model is None:
        return {"backend": "opencv", "yolo": False, "reason": "backend YOLO tidak tersedia"}
    runtime = getattr(model, "backend", "pytorch")
    return {"backend": "yolo", "yolo": True, "runtime": runtime, "weights": str(path)}


def _padded_quad(quad: Any, image_shape: Any) -> Any:
    """Tambah margin hanya pada crop OCR; bbox overlay tetap dari YOLO asli."""
    np = __import__("numpy")
    h, w = image_shape[:2]
    x1, y1 = np.asarray(quad).min(axis=0)
    x2, y2 = np.asarray(quad).max(axis=0)
    pad_x = max((x2 - x1) * OCR_PADDING_X, 4.0)
    pad_y = max((y2 - y1) * OCR_PADDING_Y, 3.0)
    return order_points([
        [max(0.0, x1 - pad_x), max(0.0, y1 - pad_y)],
        [min(float(w - 1), x2 + pad_x), max(0.0, y1 - pad_y)],
        [min(float(w - 1), x2 + pad_x), min(float(h - 1), y2 + pad_y)],
        [max(0.0, x1 - pad_x), min(float(h - 1), y2 + pad_y)],
    ])


def _box_geometry_ok(
    x1: float, y1: float, x2: float, y2: float, image_shape: Any
) -> bool:
    """Tolak box bodi kendaraan sebelum crop/OCR."""
    h, w = image_shape[:2]
    width, height = max(x2 - x1, 0.0), max(y2 - y1, 0.0)
    if width <= 0 or height <= 0:
        return False
    aspect = width / height
    area_ratio = (width * height) / max(float(w * h), 1.0)
    # Box detector yang menelan bumper/aspal tidak boleh lolos hanya karena
    # confidence YOLO tinggi. Rentang ini mencakup plat motor dan mobil,
    # tetapi menolak kandidat yang hampir persegi atau terlalu memanjang.
    return 1.20 <= aspect <= 5.00 and area_ratio <= MAX_BOX_AREA_RATIO


def _predict_boxes(
    model: Any, image: Any, conf: float = DEFAULT_CONF
) -> list[tuple[float, float, float, float, float, int]]:
    """Seragamkan keluaran kotak dari :class:`_OnnxYoloRunner` maupun Ultralytics YOLO."""
    if isinstance(model, _OnnxYoloRunner):
        return model.predict_boxes(image, conf=conf)
    result = model.predict(image, conf=conf, verbose=False)[0]
    if result.boxes is None:
        return []
    out: list[tuple[float, float, float, float, float, int]] = []
    for box in result.boxes:
        class_id = int(box.cls[0]) if getattr(box, "cls", None) is not None else 0
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
        out.append((x1, y1, x2, y2, float(box.conf[0]), class_id))
    return out


def detect(image: Any, max_candidates: int = 4) -> list[Detection]:
    """Deteksi plat dengan YOLO; kontrak sama dengan pipeline klasik.

    Gate tekstur/kelayakan tetap dijalankan agar skor kandidat sebanding dengan
    jalur klasik (dipakai oleh ambang keputusan di :mod:`app.fusion`).
    """
    model = _model()
    if model is None:
        return []

    raw_boxes = _predict_boxes(model, image, conf=DEFAULT_CONF)
    if not raw_boxes:
        return []

    candidates: list[tuple[float, Detection]] = []
    for x1, y1, x2, y2, det_conf, class_id in raw_boxes:
        # Dataset prototype hanya memiliki satu kelas: number-plate.
        if class_id != 0:
            continue
        if not _box_geometry_ok(x1, y1, x2, y2, image.shape):
            continue
        quad = order_points([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
        crop = four_point_transform(image, quad)
        if crop.size == 0:
            continue
        border = plate_border_score(crop)  # bingkai plat pada box penuh, sebelum snap
        texture_ok = plate_texture_ok(crop)
        # Persempit vertikal ke pita teks terlebih dahulu (keep_horizontal=True)
        # agar bingkai hitam holder plat di atas/bawah tidak merusak hitungan glyph.
        text_band, _ = snap_to_text_band(crop, keep_horizontal=True)
        vehicle_class, orientation, glyphs, plausibility = plate_plausibility(crop)
        if getattr(text_band, "size", 0):
            vc2, ori2, gl2, pl2 = plate_plausibility(text_band)
            if pl2 > plausibility:
                vehicle_class, orientation, glyphs, plausibility = vc2, ori2, gl2, pl2
            crop = text_band
        min_aspect, max_aspect = ASPECT_RANGES.get(
            vehicle_class, ASPECT_RANGES["custom"]
        )
        box_aspect = (x2 - x1) / max(y2 - y1, 1.0)
        if not min_aspect <= box_aspect <= max_aspect:
            continue
        # Bila YOLO sangat yakin (det_conf >= 0.45) dan tekstur plat valid,
        # jangan pernah membuang box YOLO hanya karena proyeksi Otsu gagal menghitung glyph.
        if plausibility < MIN_PLAUSIBILITY:
            if det_conf >= 0.45 and texture_ok:
                plausibility = round(det_conf * 0.85, 4)
            else:
                continue
        if not texture_ok and plausibility < 0.35 and det_conf < 0.50:
            continue
        # Quad overlay sengaja TIDAK dirapatkan ke pita teks: kotak yang berubah
        # tiap frame (loncat-loncat) membingungkan petugas dan tampak memotong
        # papan plat. Konteks bodi tetap dibuang oleh snap pada ocr_crop di bawah.
        ocr_crop = four_point_transform(image, _padded_quad(quad, image.shape))
        full_crop = ocr_crop  # crop bermargin: tampilan cadangan bila snap terlalu rapat
        # Buang margin vertikal berlebih (mis. stiker tanggal/bumper), tetap
        # pertahankan lebar horizontal box YOLO agar karakter tepi utuh.
        text_crop, _ = snap_to_text_band(ocr_crop, keep_horizontal=True)
        if getattr(text_crop, "size", 0):
            ocr_crop = pad_crop(text_crop)  # snap rapat -> margin wajib dikembalikan
        detection = Detection(
                kind="plate",
                quad=[[float(x), float(y)] for x, y in quad],
                confidence=round(max(plausibility, det_conf), 4),
                crop=normalize_plate_size(ocr_crop),
                meta={
                    "raw_crop": ocr_crop,
                    "full_crop": full_crop,
                    "detector_crop": crop,
                    "border": round(border, 4),
                    "vehicle_class": vehicle_class,
                    "orientation": orientation,
                    "glyph_count": glyphs,
                    "detector_conf": round(det_conf, 4),
                    "class_id": class_id,
                    "box_aspect": round(box_aspect, 4),
                    "backend": "yolo",
                },
            )
        candidates.append((det_conf, detection))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [detection for _, detection in candidates[:max_candidates]]
