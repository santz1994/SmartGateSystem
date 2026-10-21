"""Dekode stiker khusus.

Stiker bersifat **deterministik** — tidak perlu training ML. Cukup detektor:
QR (OpenCV bawaan), AprilTag (bila ``opencv-contrib`` tersedia), dan fallback
pola warna dari :mod:`app.pipeline`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from functools import lru_cache
from typing import Any

from .pipeline import Detection, _cv2, _np

TOKEN_PREFIX = "SGS1"
CODE_PATTERN = re.compile(r"^STK-[A-Z0-9-]{3,32}$")

def _require_signed() -> bool:
    """Produksi: QR tanpa tanda tangan ditolak. Escape hatch demo: env = 0."""
    return os.getenv("SGS_REQUIRE_SIGNED_STICKER", "1") == "1"


def _secret() -> bytes | None:
    value = os.getenv("SGS_STICKER_SIGNING_KEY", "").encode("utf-8")
    return value if len(value) >= 32 else None


def create_signed_token(
    vehicle_id: int, sticker_code: str, ttl_seconds: int = 365 * 24 * 3600
) -> str:
    secret = _secret()
    if secret is None:
        raise RuntimeError("SGS_STICKER_SIGNING_KEY wajib berisi minimal 32 byte")
    payload = {
        "v": int(vehicle_id),
        "c": str(sticker_code),
        "exp": int(time.time()) + max(int(ttl_seconds), 60),
        "jti": base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("="),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    signature = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
    return f"{TOKEN_PREFIX}.{encoded}.{signature}"


def verify_signed_token(token: str) -> dict[str, Any] | None:
    secret = _secret()
    parts = (token or "").split(".")
    if secret is None or len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return None
    encoded, signature = parts[1], parts[2]
    expected = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode((encoded + padding).encode()))
        if int(payload["exp"]) < int(time.time()):
            return None
        if not payload.get("c") or not payload.get("v") or not payload.get("jti"):
            return None
        return payload
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


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


def _legacy_code(payload: str, confidence: float, decoder: str) -> tuple[str | None, float, str]:
    """QR lama tanpa tanda tangan: hanya kode berformat STK-* yang boleh lolos.

    Default menolak semuanya (H2) — QR bebas apa pun (teks HTML/JS, kode
    kendaraan orang lain) tidak boleh menjadi bukti identitas.
    """
    if _require_signed():
        return None, 0.0, "qrcode_unsigned_rejected"
    compact = re.sub(r"\s+", "", (payload or "").upper())
    if not CODE_PATTERN.fullmatch(compact):
        return None, 0.0, "qrcode_bad_format"
    return compact, confidence, decoder

def decode_sticker(detection: Detection) -> tuple[str | None, float, str]:
    """Kembalikan (kode, keyakinan, decoder) untuk satu kandidat stiker."""
    if detection.payload:
        payload = verify_signed_token(detection.payload)
        if payload is not None:
            return str(payload["c"]), detection.confidence, "qrcode_signed"
        if detection.payload.startswith(f"{TOKEN_PREFIX}."):
            return None, 0.0, "qrcode_invalid_signature"
        return _legacy_code(
            detection.payload, detection.confidence, detection.meta.get("decoder", "qrcode_legacy")
        )

    crop = detection.crop
    if crop is None or crop.size == 0:
        return None, 0.0, "none"

    code, confidence = _try_apriltag(crop)
    if code:
        return code, confidence, "apriltag"

    code, confidence = _try_qr(crop)
    if code:
        payload = verify_signed_token(code)
        if payload is not None:
            return str(payload["c"]), confidence, "qrcode_signed"
        if code.startswith(f"{TOKEN_PREFIX}."):
            return None, 0.0, "qrcode_invalid_signature"
        return _legacy_code(code, confidence, "qrcode_legacy")

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
