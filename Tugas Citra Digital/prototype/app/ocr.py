"""OCR plat nomor.

Dua backend, dipilih otomatis saat runtime:

1. ``paddleocr`` — bila paket terpasang. Akurasi kelas produksi.
2. ``template_match`` — fallback murni pengolahan citra: segmentasi karakter
   lewat *vertical projection profile*, lalu pencocokan template dengan IoU.
   Tidak butuh model terlatih, jalan di mana saja, dan justru inilah bagian
   yang relevan untuk tugas Pengolahan Citra Digital.

Atlas template dibuat sekali lalu di-cache (``lru_cache``) — pembuatan 36 glyph
butuh ~40 ms, tidak perlu diulang tiap request.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from .pipeline import _cv2, _np, split_rows

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
GLYPH_SIZE = 32

# Format plat Indonesia: 1-2 huruf, 1-4 angka, 0-3 huruf. Kelas angka sengaja
# hanya memuat huruf yang sering salah baca sebagai angka (O/I/Z/S) supaya 'B'
# di prefix tidak ikut dikoreksi jadi '8'.
_PLATE_RE = re.compile(r"^([A-Z0-9]{1,2}?)([0-9OIZS]{1,4})([A-Z0-9]{0,3})$")
_TO_DIGIT = str.maketrans({"O": "0", "I": "1", "Z": "2", "S": "5", "B": "8", "G": "6"})
_TO_ALPHA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"})

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)


def normalize_plate(text: str) -> str:
    """Rapikan hasil OCR: buang non-alfanumerik + koreksi karakter ambigu.

    Koreksi hanya diterapkan pada blok yang sesuai posisinya, jadi ``B 1234 XYZ``
    tetap ``B1234XYZ`` dan bukan ``81234XYZ``.
    """
    compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    match = _PLATE_RE.match(compact)
    if not match:
        return compact
    prefix, digits, suffix = match.groups()
    return prefix.translate(_TO_ALPHA) + digits.translate(_TO_DIGIT) + suffix.translate(_TO_ALPHA)


# --- Atlas template -----------------------------------------------------------

@lru_cache(maxsize=1)
def _load_font(size: int = 64):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 tidak menerima argumen size
        return ImageFont.load_default()


def _normalize_glyph(arr: Any, size: int = GLYPH_SIZE) -> Any:
    """Crop ke bounding box tinta, skala proporsional, taruh di tengah kanvas."""
    cv2, np = _cv2(), _np()
    mask = (arr > 0).astype(np.uint8)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.zeros((size, size), dtype=np.uint8)
    glyph = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = glyph.shape
    scale = (size - 4) / float(max(h, w))
    nh, nw = max(int(round(h * scale)), 1), max(int(round(w * scale)), 1)
    resized = cv2.resize(glyph * 255, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((size, size), dtype=np.uint8)
    oy, ox = (size - nh) // 2, (size - nw) // 2
    canvas[oy : oy + nh, ox : ox + nw] = resized
    return (canvas > 127).astype(np.uint8)


@lru_cache(maxsize=1)
def _templates() -> dict[str, Any]:
    """Atlas 36 glyph (A-Z, 0-9) yang dirender dari font sistem."""
    np = _np()
    from PIL import Image, ImageDraw

    font = _load_font(64)
    atlas: dict[str, Any] = {}
    for char in CHARSET:
        canvas = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(canvas).text((48, 48), char, fill=255, font=font, anchor="mm")
        atlas[char] = _normalize_glyph(np.array(canvas))
    return atlas


# --- Segmentasi karakter ------------------------------------------------------

def _split_run(ink: Any, start: int, end: int, median_width: int) -> list[tuple[int, int]]:
    """Pecah satu run lebar jadi beberapa karakter di titik tinta minimum."""
    np = _np()
    parts = max(2, int(round((end - start) / max(median_width, 1))))
    bounds = [start]
    for i in range(1, parts):
        center = start + int((end - start) * i / parts)
        pad = max(int((end - start) * 0.15), 1)
        lo, hi = max(center - pad, bounds[-1] + 1), min(center + pad, end - 1)
        bounds.append(center if hi <= lo else int(lo + np.argmin(ink[lo:hi])))
    bounds.append(end)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def _segment_glyphs(binary: Any) -> list[Any]:
    """Vertical projection profile: kolom ber-tinta = karakter."""
    h, w = binary.shape
    ink = (binary > 0).sum(axis=0)
    threshold = max(1, int(h * 0.08))

    runs: list[tuple[int, int]] = []
    start: int | None = None
    for x in range(w):
        if ink[x] > threshold:
            if start is None:
                start = x
        elif start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, w))

    min_width = max(2, int(h * 0.06))
    runs = [(a, b) for a, b in runs if b - a >= min_width]
    if not runs:
        return []

    widths = sorted(b - a for a, b in runs)
    median = widths[len(widths) // 2]

    spans: list[tuple[int, int]] = []
    for a, b in runs:
        spans.extend(_split_run(ink, a, b, median) if b - a > median * 1.7 else [(a, b)])
    return [binary[:, a:b] for a, b in spans]


def _match_glyph(glyph: Any, atlas: dict[str, Any]) -> tuple[str, float, float]:
    """IoU glyph vs atlas. Kembalikan (karakter, skor terbaik, selisih ke-2)."""
    np = _np()
    probe = _normalize_glyph(glyph)
    probe_bool = probe > 0
    best_char, best, second = "?", -1.0, -1.0
    for char, template in atlas.items():
        template_bool = template > 0
        union = np.logical_or(probe_bool, template_bool).sum()
        if union == 0:
            continue
        score = float(np.logical_and(probe_bool, template_bool).sum() / union)
        if score > best:
            second, best, best_char = best, score, char
        elif score > second:
            second = score
    return best_char, max(best, 0.0), max(best - second, 0.0)


# --- Backend: template matching ----------------------------------------------

def _read_template(crop: Any) -> tuple[str, float]:
    cv2, np = _cv2(), _np()
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = max(2.0, 64.0 / max(gray.shape[0], 1))  # baris pendek di-upscale lebih
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h, w = binary.shape
    binary = binary[int(h * 0.10) : int(h * 0.90), int(w * 0.03) : int(w * 0.97)]

    glyphs = _segment_glyphs(binary)
    if not glyphs:
        return "", 0.0

    atlas = _templates()
    chars, scores, margins = [], [], []
    for glyph in glyphs:
        char, score, margin = _match_glyph(glyph, atlas)
        chars.append(char)
        scores.append(score)
        margins.append(margin)

    text = normalize_plate("".join(chars))
    # Margin rendah = karakter ambigu (8 vs B). Turunkan keyakinan, jangan buang.
    confidence = float(np.mean(scores)) * min(1.0, 0.6 + 4.0 * float(np.mean(margins)))
    return text, round(min(confidence, 0.99), 4)

def _read_template_multiline(crop: Any) -> tuple[str, float]:
    """Plat 2 baris (truk/bus): baca tiap baris, gabung, agregat keyakinan.

    Setiap baris dinormalisasi sendiri lalu digabung, karena format TNKB 2 baris
    memecah prefix/angka/suffix ke baris berbeda.
    """
    np = _np()
    rows = split_rows(crop)
    if len(rows) < 2:
        return _read_template(crop)

    parts: list[str] = []
    confidences: list[float] = []
    for row in rows:
        text, confidence = _read_template(row)
        if text:
            parts.append(text)
            confidences.append(confidence)
    if not parts:
        return "", 0.0
    # Baris yang gagal dibaca menurunkan keyakinan keseluruhan (bukan diabaikan).
    coverage = len(parts) / len(rows)
    confidence = float(np.mean(confidences)) * (0.6 + 0.4 * coverage)
    return normalize_plate("".join(parts)), round(min(confidence, 0.99), 4)


# --- Backend: PaddleOCR -------------------------------------------------------

@lru_cache(maxsize=1)
def _paddle_reader():
    from paddleocr import PaddleOCR

    return PaddleOCR(use_angle_cls=False, lang="en", show_log=False)


def _read_paddle(crop: Any) -> tuple[str, float]:
    result = _paddle_reader().ocr(crop, cls=False)
    lines = result[0] if result else None
    if not lines:
        return "", 0.0
    text = "".join(item[1][0] for item in lines)
    confidence = float(sum(item[1][1] for item in lines) / len(lines))
    return normalize_plate(text), round(confidence, 4)


# --- Backend: EasyOCR ---------------------------------------------------------

@lru_cache(maxsize=1)
def _easy_reader():
    import easyocr

    return easyocr.Reader(["en"], gpu=False, verbose=False)

def _read_easyocr(crop: Any) -> tuple[str, float]:
    np = _np()
    results = _easy_reader().readtext(crop)
    if not results:
        return "", 0.0
    # Plat 2 baris = 2 kotak setinggi sebanding; baris tanggal/tambahan dibuang.
    boxes = []
    for points, text, confidence in results:
        pts = np.asarray(points, dtype="float32")
        height = float(pts[:, 1].max() - pts[:, 1].min())
        baseline = float(pts[:, 1].max())
        left = float(pts[:, 0].min())
        boxes.append((baseline, left, height, float(confidence), text))
    max_height = max(b[2] for b in boxes)
    rows = [b for b in boxes if b[2] >= 0.6 * max_height]
    if not rows:
        rows = [max(boxes, key=lambda b: b[2])]
    # Urut baca: sejajar baseline (baris) dulu, baru kiri->kanan.
    rows.sort(key=lambda b: (b[0], b[1]))
    text = normalize_plate("".join(b[4] for b in rows))
    confidence = float(np.mean([b[3] for b in rows]))
    return text, round(min(confidence, 0.99), 4)

@lru_cache(maxsize=1)
def active_backend() -> str:
    import importlib.util

    if importlib.util.find_spec("paddleocr"):
        return "paddleocr"
    if importlib.util.find_spec("easyocr"):
        return "easyocr"
    return "template_match"

def read_plate(crop: Any) -> tuple[str, float, str]:
    """Baca plat dari crop yang sudah di-deskew. -> (teks, keyakinan, backend)."""
    if active_backend() == "paddleocr":
        try:
            text, confidence = _read_paddle(crop)
            return text, confidence, "paddleocr"
        except Exception:  # noqa: BLE001 - prototipe harus tetap jalan
            pass
    if active_backend() == "easyocr":
        try:
            text, confidence = _read_easyocr(crop)
            return text, confidence, "easyocr"
        except Exception:  # noqa: BLE001 - jatuh ke template_match bila model belum ada
            pass
    text, confidence = _read_template_multiline(crop)
    return text, confidence, "template_match"
