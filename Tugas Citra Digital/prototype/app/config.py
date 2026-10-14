"""Konfigurasi prototipe Smart Gate.

Semua path & ambang keputusan terpusat di sini. Ambang dapat dioverride runtime
lewat tabel ``system_settings`` (lihat :mod:`app.db`).
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SGS_DATA_DIR", BASE_DIR / "data"))
SNAPSHOT_DIR = DATA_DIR / "snapshots"
DB_PATH = Path(os.getenv("SGS_DB", DATA_DIR / "smartgate.db"))

# Ambang default. Nilai ini yang dipakai bila baris system_settings tidak ada.
DEFAULTS: dict[str, float] = {
    "plat_confidence_threshold": 0.85,
    "sticker_confidence_threshold": 0.80,
    "fused_confidence_threshold": 0.90,
    "low_confidence_floor": 0.60,
    "session_window_seconds": 3.0,
    "multi_camera_bonus": 0.05,
    "clahe_clip_limit": 2.0,
    "frame_vote_minimum": 2.0,
}

# Bobot fusi: stiker adalah *penguat*, bukan syarat.
FUSION_WEIGHTS = {"plate": 1.0, "sticker": 0.95}

# EasyOCR adalah backend produksi default pada Windows CPU; PaddleOCR tetap
# tersedia sebagai opsi melalui SGS_OCR_BACKEND=paddleocr.
OCR_BACKEND = os.getenv("SGS_OCR_BACKEND", "easyocr").lower()
CLAHE_CLIP_LIMIT = float(os.getenv("SGS_CLAHE_CLIP_LIMIT", str(DEFAULTS["clahe_clip_limit"])))
DETECTION_GAMMA = float(os.getenv("SGS_DETECTION_GAMMA", "1.15"))
DETECTION_ROI = tuple(
    float(part) for part in os.getenv("SGS_DETECTION_ROI", "0.05,0.35,0.95,1.0").split(",")
)

# Batas ukuran upload (MB) untuk foto manual.
MAX_UPLOAD_MB = 16


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
