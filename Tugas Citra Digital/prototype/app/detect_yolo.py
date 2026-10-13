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
)

ENV_VAR = "SGS_YOLO_WEIGHTS"
DEFAULT_CONF = 0.25


def weights_path() -> Path | None:
    """File bobot dari variabel lingkungan, bila ada dan benar-benar ada."""
    raw = os.getenv(ENV_VAR, "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


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

    detections: list[Detection] = []
    for box in result.boxes:
        if len(detections) >= max_candidates:
            break
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
        quad = order_points([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
        crop = four_point_transform(image, quad)
        if crop.size == 0 or not plate_texture_ok(crop):
            continue
        vehicle_class, orientation, glyphs, plausibility = plate_plausibility(crop)
        # Model YOLO jauh lebih andal soal lokasi daripada gerbang glyph kita;
        # kalau gate menolak (glyphs=0 pada plat miring/blur), kandidat tetap
        # diterima dengan skor minimum supaya tidak hilang sia-sia.
        score = plausibility
        if plausibility <= 0.0:
            h, w = crop.shape[:2]
            vehicle_class = vehicles.classify(w / max(h, 1), 1)
            orientation = "horizontal"
            score = 0.5
        detections.append(
            Detection(
                kind="plate",
                quad=[[float(x), float(y)] for x, y in quad],
                confidence=round(score, 4),
                crop=normalize_plate_size(crop),
                meta={
                    "raw_crop": crop,
                    "vehicle_class": vehicle_class,
                    "orientation": orientation,
                    "glyph_count": glyphs,
                    "detector_conf": round(float(box.conf[0]), 4),
                    "backend": "yolo",
                },
            )
        )
    return detections
