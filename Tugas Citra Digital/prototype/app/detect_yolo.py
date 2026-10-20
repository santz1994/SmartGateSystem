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


def _default_weights() -> Path | None:
    """Pilih bobot training lokal bila operator belum mengatur environment."""
    base = Path(__file__).resolve().parent.parent
    for relative in (
        "runs/detect/smartgate-colab-v5/weights/best.pt",
        "runs/detect/runs/detect/smartgate/weights/best.pt",
        "runs/detect/runs/detect/smartgate-full/weights/best.pt",
    ):
        candidate = base / relative
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
    """Muat model sekali saja (lru_cache). ``None`` bila belum bisa dipakai."""
    path = weights_path()
    if path is None:
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        return None
    return YOLO(str(path))


def available() -> bool:
    return _model() is not None


def status() -> dict[str, Any]:
    """Info ringkas untuk halaman dashboard / API ``/api/health``."""
    path = weights_path()
    if path is None:
        return {"backend": "opencv", "yolo": False, "reason": f"{ENV_VAR} belum diisi"}
    if _model() is None:
        return {"backend": "opencv", "yolo": False, "reason": "ultralytics belum terpasang"}
    return {"backend": "yolo", "yolo": True, "weights": str(path)}


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


def detect(image: Any, max_candidates: int = 4) -> list[Detection]:
    """Deteksi plat dengan YOLO; kontrak sama dengan pipeline klasik.

    Gate tekstur/kelayakan tetap dijalankan agar skor kandidat sebanding dengan
    jalur klasik (dipakai oleh ambang keputusan di :mod:`app.fusion`).
    """
    model = _model()
    if model is None:
        return []

    result = model.predict(image, conf=DEFAULT_CONF, verbose=False)[0]
    if result.boxes is None:
        return []

    candidates: list[tuple[float, Detection]] = []
    for box in result.boxes:
        class_id = int(box.cls[0]) if getattr(box, "cls", None) is not None else 0
        # Dataset prototype hanya memiliki satu kelas: number-plate.
        if class_id != 0:
            continue
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
        if not _box_geometry_ok(x1, y1, x2, y2, image.shape):
            continue
        quad = order_points([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
        crop = four_point_transform(image, quad)
        if crop.size == 0:
            continue
        border = plate_border_score(crop)  # bingkai plat pada box penuh, sebelum snap
        texture_ok = plate_texture_ok(crop)
        vehicle_class, orientation, glyphs, plausibility = plate_plausibility(crop)
        min_aspect, max_aspect = ASPECT_RANGES.get(
            vehicle_class, ASPECT_RANGES["custom"]
        )
        box_aspect = (x2 - x1) / max(y2 - y1, 1.0)
        if not min_aspect <= box_aspect <= max_aspect:
            continue
        # Confidence YOLO saja tidak cukup: gril/emblem sering berbentuk
        # persegi panjang dan dapat diberi confidence tinggi oleh model lama.
        # Kandidat tanpa struktur karakter tidak boleh diteruskan ke OCR.
        if plausibility < MIN_PLAUSIBILITY:
            continue
        # Webcam frame kecil/gelap dapat gagal pada ambang tekstur meskipun
        # model dan struktur glyph sudah menunjuk ke plat. Tetap tolak kandidat
        # tanpa glyph, tetapi jangan menggugurkan plat valid hanya karena kontras.
        if not texture_ok and plausibility < 0.35:
            continue
        # Bobot hasil training kadang mengurung seluruh bagian depan mobil,
        # bukan papan platnya. Persempit box visual dan crop OCR ke pita teks
        # agar EasyOCR tidak ikut membaca gril, logo, atau bumper.
        text_band, _ = snap_to_text_band(crop)
        if getattr(text_band, "size", 0):
            crop = text_band
        # Quad overlay sengaja TIDAK dirapatkan ke pita teks: kotak yang berubah
        # tiap frame (loncat-loncat) membingungkan petugas dan tampak memotong
        # papan plat. Konteks bodi tetap dibuang oleh snap pada ocr_crop di bawah.
        ocr_crop = four_point_transform(image, _padded_quad(quad, image.shape))
        # Bobot lama kadang memberi box sedikit lebih besar dari papan plat.
        # Buang konteks bodi/roda sebelum EasyOCR agar suffix tidak tenggelam
        # oleh teks dan tepi lain di dalam box.
        text_crop, _ = snap_to_text_band(ocr_crop)
        if getattr(text_crop, "size", 0):
            ocr_crop = pad_crop(text_crop)  # snap rapat -> margin wajib dikembalikan
        detection = Detection(
                kind="plate",
                quad=[[float(x), float(y)] for x, y in quad],
                confidence=round(plausibility, 4),
                crop=normalize_plate_size(ocr_crop),
                meta={
                    "raw_crop": ocr_crop,
                    "detector_crop": crop,
                    "border": round(border, 4),
                    "vehicle_class": vehicle_class,
                    "orientation": orientation,
                    "glyph_count": glyphs,
                    "detector_conf": round(float(box.conf[0]), 4),
                    "class_id": class_id,
                    "box_aspect": round(box_aspect, 4),
                    "backend": "yolo",
                },
            )
        candidates.append((float(box.conf[0]), detection))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [detection for _, detection in candidates[:max_candidates]]
