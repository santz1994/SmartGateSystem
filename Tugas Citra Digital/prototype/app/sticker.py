"""Dekode stiker khusus.

Stiker bersifat **deterministik** — tidak perlu training ML. Cukup detektor:
QR (OpenCV bawaan), AprilTag (bila ``opencv-contrib`` tersedia), dan fallback
pola warna dari :mod:`app.pipeline`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .pipeline import Detection, _cv2, _np


@lru_cache(maxsize=1)
def _apriltag_detector():
    """AprilTag butuh opencv-contrib. Kembalikan None bila tidak tersedia."""
    cv2 = _cv2()
    if not hasattr(cv2, "aruco"):
        return None
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    if hasattr(cv2.aruco, "DetectorParameters"):
        params = cv2.aruco.DetectorParameters()
    else:  # OpenCV < 4.7
        params = cv2.aruco.DetectorParameters_create()
    return cv2.aruco.ArucoDetector(dictionary, params)


def decode_sticker(detection: Detection) -> tuple[str | None, float, str]:
    """Kembalikan (kode, keyakinan, decoder) untuk satu kandidat stiker."""
    if detection.payload:
        return detection.payload, detection.confidence, detection.meta.get("decoder", "qrcode")

    crop = detection.crop
    if crop is None or crop.size == 0:
        return None, 0.0, "none"

    code, confidence = _try_apriltag(crop)
    if code:
        return code, confidence, "apriltag"

    code, confidence = _try_qr(crop)
    if code:
        return code, confidence, "qrcode"

    # Pola warna: tidak menghasilkan kode, hanya sinyal "ada stiker".
    return None, detection.confidence, detection.meta.get("decoder", "color_patch")


def _try_qr(crop: Any) -> tuple[str | None, float]:
    cv2 = _cv2()
    try:
        payload, points, _ = cv2.QRCodeDetector().detectAndDecode(crop)
    except cv2.error:
        return None, 0.0
    if payload and points is not None:
        return payload, 0.95
    return None, 0.0


def _try_apriltag(crop: Any) -> tuple[str | None, float]:
    detector = _apriltag_detector()
    if detector is None:
        return None, 0.0
    cv2, np = _cv2(), _np()
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    try:
        corners, ids, _ = detector.detectMarkers(gray)
    except cv2.error:
        return None, 0.0
    if ids is None or len(ids) == 0:
        return None, 0.0
    return f"TAG-{int(np.ravel(ids)[0]):05d}", 0.92


def available_decoders() -> list[str]:
    decoders = ["qrcode", "color_patch"]
    if _apriltag_detector() is not None:
        decoders.insert(1, "apriltag")
    return decoders
