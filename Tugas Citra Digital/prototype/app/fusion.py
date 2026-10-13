"""Fusi skor & logika keputusan.

Fungsi di sini **murni** (tanpa I/O, tanpa DB) supaya bisa diuji langsung —
lihat ``tests/test_pipeline.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import FUSION_WEIGHTS

# Kode keputusan final.
AUTO_OPEN = "AUTO_OPEN"
NO_MATCH = "NO_MATCH"
OCR_FAILED = "OCR_FAILED"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
REJECTED = "REJECTED"

# Keputusan yang masih menunggu tindakan satpam.
PENDING_DECISIONS = (NO_MATCH, OCR_FAILED, LOW_CONFIDENCE)

DECISION_LABEL = {
    AUTO_OPEN: "Buka Pintu Otomatis",
    NO_MATCH: "Kendaraan Tidak Dikenali",
    OCR_FAILED: "Kendaraan Tidak Dikenali (Gagal Baca)",
    LOW_CONFIDENCE: "Perlu Konfirmasi Satpam",
    MANUAL_OVERRIDE: "Buka Pintu Manual (Bypass)",
    REJECTED: "Tolak Akses",
}

DECISION_ALERT = {
    AUTO_OPEN: "GREEN",
    NO_MATCH: "RED",
    OCR_FAILED: "RED",
    LOW_CONFIDENCE: "AMBER",
    MANUAL_OVERRIDE: "AMBER",
    REJECTED: "RED",
}


@dataclass
class FusionResult:
    plate_score: float
    sticker_score: float
    fused_score: float
    sources: int


def fuse_scores(
    plate_confs: list[float],
    sticker_confs: list[float],
    sources: int = 1,
    bonus: float = 0.05,
) -> FusionResult:
    """Gabungkan keyakinan plat & stiker dari semua frame dalam satu sesi.

    Stiker adalah **penguat**, bukan syarat: skor akhir = max(plat, stiker) plus
    bonus kecil per sumber tambahan (korelasi multi-kamera), dibatasi 1.0.
    """
    plate_score = (max(plate_confs) if plate_confs else 0.0) + bonus * max(len(plate_confs) - 1, 0)
    sticker_score = (max(sticker_confs) if sticker_confs else 0.0) + bonus * max(len(sticker_confs) - 1, 0)
    plate_score = min(plate_score * FUSION_WEIGHTS["plate"], 1.0)
    sticker_score = min(sticker_score * FUSION_WEIGHTS["sticker"], 1.0)
    camera_bonus = bonus * max(sources - 1, 0)
    fused = min(1.0, max(plate_score, sticker_score) + camera_bonus)
    return FusionResult(
        plate_score=round(plate_score, 4),
        sticker_score=round(sticker_score, 4),
        fused_score=round(fused, 4),
        sources=sources,
    )


def decide(
    *,
    plate_text: str | None,
    plate_confidence: float,
    sticker_code: str | None,
    sticker_confidence: float,
    fused_score: float,
    match: Any | None,
    thresholds: dict[str, float],
) -> tuple[str, str]:
    """Tentukan kode keputusan + alasan. -> (decision, reason).

    Dua lapis ambang:
    * ambang per sumber (plat/stiker) menentukan apakah identitas boleh dipercaya;
    * ambang fusi menentukan apakah bukti gabungan cukup untuk buka otomatis.

    Fail-safe: pemanggil wajib memastikan ``match`` bernilai None bila DB tidak
    tersedia, sehingga sistem tidak pernah membuka pintu tanpa verifikasi.
    """
    floor = thresholds.get("low_confidence_floor", 0.60)
    fused_threshold = thresholds.get("fused_confidence_threshold", 0.90)
    plate_threshold = thresholds.get("plat_confidence_threshold", 0.85)
    sticker_threshold = thresholds.get("sticker_confidence_threshold", 0.80)

    plate_ok = bool(plate_text) and plate_confidence >= plate_threshold
    sticker_ok = bool(sticker_code) and sticker_confidence >= sticker_threshold

    if match is None:
        if plate_confidence < floor and sticker_confidence < floor:
            return OCR_FAILED, "Plat & stiker gagal dibaca (di bawah ambang minimum)"
        if plate_text and not plate_ok:
            return LOW_CONFIDENCE, (
                f"Plat {plate_text} terbaca {plate_confidence:.2f} < ambang {plate_threshold:.2f}"
            )
        if sticker_code and not sticker_ok:
            return LOW_CONFIDENCE, (
                f"Stiker {sticker_code} terbaca {sticker_confidence:.2f} < ambang {sticker_threshold:.2f}"
            )
        if plate_text:
            return NO_MATCH, f"Plat {plate_text} tidak terdaftar di database"
        if sticker_code:
            return NO_MATCH, f"Stiker {sticker_code} tidak terdaftar di database"
        return OCR_FAILED, "Tidak ada identitas kendaraan yang terbaca"

    if not (plate_ok or sticker_ok):
        return LOW_CONFIDENCE, (
            f"Data cocok tapi keyakinan identitas di bawah ambang "
            f"(plat {plate_confidence:.2f}/{plate_threshold:.2f}, "
            f"stiker {sticker_confidence:.2f}/{sticker_threshold:.2f})"
        )

    if fused_score >= fused_threshold:
        return AUTO_OPEN, "Data cocok di database dengan keyakinan tinggi"

    return LOW_CONFIDENCE, (
        f"Data cocok tapi skor fusi {fused_score:.2f} < ambang {fused_threshold:.2f}"
    )
