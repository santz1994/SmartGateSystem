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
import hashlib
import logging
import time
from functools import lru_cache
from typing import Any

from . import config

LOGGER = logging.getLogger(__name__)
from .pipeline import _cv2, _np, split_rows

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
GLYPH_SIZE = 32

# Struktur NRKB (Perkapolri 5/2012 — bapenda.jabarprov.go.id/2017/10/24/kenali-
# penomoran-kendaraan-bermotor/):
#   [kode wilayah 1-3 huruf][nomor urut 1-4 angka][seri 0-3 huruf]
# Golongan nomor urut: 1-1999 mobil penumpang, 2000-6999 sepeda motor,
# 7000-7999 bus, 8000-8999 barang, 9000-9999 khusus.
# Struktur inilah pemutus sengketa B/8, 6/G, 1/I: huruf di blok huruf,
# angka di blok angka — 'I' di tengah berarti '1', '8' di depan berarti 'B'.
_TO_DIGIT = str.maketrans({
    "O": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8",
    "G": "6", "T": "7", "A": "4", "D": "0",
})
_TO_ALPHA = str.maketrans({
    "0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G",
    "7": "T", "8": "B", "Q": "O",
})
_AMBIGUOUS = set("OQIZSBG012568")  # pasangan huruf-angka yang sering tertukar

# Kode wilayah TNKB tidak pernah memakai O/Q/I/L/angka. Plat Makassar "DD"
# sering terbaca "00"/"O0" — koreksi HANYA blok prefix memakai peta ini, bukan
# seluruh teks, supaya angka di blok nomor urut tidak ikut tersentuh.
_PREFIX_FIX = str.maketrans({"0": "D", "1": "D", "O": "D", "I": "D", "L": "D", "8": "B"})
VALID_PREFIXES = frozenset({
    "A","B","D","E","F","G","H","K","L","M","N","P","R","S","T","W","Z",
    "AA","AB","AD","AE","AG","BA","BB","BD","BE","BG","BH","BK","BL","BM",
    "BN","BP","DA","DB","DC","DD","DE","DG","DH","DK","DL","DM","DN","DP",
    "DR","DT","DW","EA","EB","ED","KB","KH","KT","KU","PA","PB",
})
NUMBER_GROUPS = ((1, 1999, "car"), (2000, 6999, "motorcycle"), (7000, 8999, "truck"), (9000, 9999, "custom"))

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)


def _char_scores(char: str) -> tuple[float, float]:
    """(skor di blok huruf, skor di blok angka) untuk satu karakter."""
    if char in _AMBIGUOUS:
        return 0.6, 0.6  # bisa salah baca dua arah (B/8, 6/G, 1/I)
    return (1.0, 0.2) if char.isalpha() else (0.2, 1.0)

def number_group(text: str) -> int | None:
    """Nomor urut NRKB dari teks plat (blok angka pertama)."""
    compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    match = re.match(r"^[A-Z]{1,3}([0-9]{1,4})", compact)
    if not match or match.group(1).startswith("0"):
        return None
    return int(match.group(1))

def number_fits_class(text: str, vehicle_class: str | None) -> bool:
    """Nomor urut sesuai golongan kendaraan (Perkapolri 5/2012)?"""
    number = number_group(text)
    if number is None or not vehicle_class:
        return False
    return any(key == vehicle_class and low <= number <= high for low, high, key in NUMBER_GROUPS)

def normalize_plate(text: str) -> str:
    """Rapikan hasil OCR memakai struktur NRKB — pemutus sengketa B/8, 6/G, 1/I.

    Semua pemecahan panjang blok dicoba (kode wilayah 1-3, nomor urut 1-4,
    seri 0-3); skor tertinggi menang: karakter sesuai bloknya bernilai penuh,
    karakter ambigu (B/8, 6/G, 1/I, ...) bernilai setengah di kedua blok, dan
    blok angka 3-4 digit (lazim) diberi bonus.
    """
    compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    if len(compact) < 2:
        return compact
    best_score, best_text = -1.0, compact
    for prefix_len in (1, 2, 3):
        for suffix_len in (0, 1, 2, 3):
            digit_len = len(compact) - prefix_len - suffix_len
            if not 1 <= digit_len <= 4:
                continue
            prefix = compact[:prefix_len]
            digits = compact[prefix_len : prefix_len + digit_len]
            suffix = compact[prefix_len + digit_len :]
            score = sum(_char_scores(c)[0] for c in prefix + suffix)
            score += sum(_char_scores(c)[1] for c in digits)
            score += 0.5 * digit_len
            prefix_fixed = prefix.translate(_PREFIX_FIX)
            if prefix_fixed in VALID_PREFIXES:
                score += 2.0  # kode wilayah valid mengalahkan split lain
            if digits.startswith("0"):
                # NRKB tak pernah diawali 0; netralkan tie-split yang mencuri
                # angka ke blok prefix (mis. "O05441XS" -> DD5441XS, bukan D0544...).
                score -= 0.5
            if score > best_score:
                best_score = score
                best_text = "".join(
                    (prefix_fixed, digits.translate(_TO_DIGIT), suffix.translate(_TO_ALPHA))
                )
    return best_text


def koreksi_karakter_plat(teks_ocr: str) -> str:
    """Koreksi karakter ambigu berdasarkan blok NRKB, bukan penggantian global."""
    return normalize_plate(teks_ocr)


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

    text = best_plate_text(["".join(chars)])
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
    return best_plate_text(parts), round(min(confidence, 0.99), 4)


# --- Backend: PaddleOCR -------------------------------------------------------

@lru_cache(maxsize=1)
def _paddle_reader():
    # PaddlePaddle 3.x dapat memilih oneDNN secara otomatis pada CPU Windows.
    # Beberapa operator PP-OCRv6 belum kompatibel dengan executor oneDNN dan
    # menghasilkan NotImplementedError saat inferensi. Pakai executor CPU
    # standar agar OCR tetap berjalan konsisten.
    import os

    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ["FLAGS_enable_pir_api"] = "0"
    from paddleocr import PaddleOCR
    import paddle

    paddle.set_flags({"FLAGS_use_mkldnn": False})

    # Flag FLAGS_* belum cukup: prediktor statis paddlex tetap memakai oneDNN
    # dan melempar NotImplementedError (ConvertPirAttribute2RuntimeAttribute).
    # Paksa run_mode="paddle" (tanpa oneDNN) pada opsi prediktor.
    try:
        from paddlex.inference.models.runners.paddle_static.config.pp_option import (
            PaddlePredictorOption,
        )

        original = PaddlePredictorOption.setdefault_by_model_name

        def _without_mkldnn(self: Any, model_name: str) -> None:
            self._cfg.setdefault("run_mode", "paddle")
            original(self, model_name)

        PaddlePredictorOption.setdefault_by_model_name = _without_mkldnn  # type: ignore[method-assign]
    except Exception:  # noqa: BLE001 - paddlex versi lain biarkan perilaku bawaan
        pass

    try:
        return PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
        )
    except (TypeError, ValueError):
        # Kompatibel dengan PaddleOCR 2.x yang masih memakai API lama.
        return PaddleOCR(use_angle_cls=False, lang="en", show_log=False)


def _read_paddle(crop: Any) -> tuple[str, float]:
    reader = _paddle_reader()
    if hasattr(reader, "predict"):
        result = reader.predict(crop)
    else:
        legacy = reader.ocr(crop, cls=False)
        lines = legacy[0] if legacy else None
        if not lines:
            return "", 0.0
        confidence = float(sum(item[1][1] for item in lines) / len(lines))
        return best_plate_text([item[1][0] for item in lines]), round(confidence, 4)
    if not result:
        return "", 0.0
    texts: list[str] = []
    confidences: list[float] = []
    for page in result:
        data = getattr(page, "json", None)
        if callable(data):
            data = data()
        if isinstance(data, str):
            import json
            data = json.loads(data)
        data = data or {}
        ocr_res = data.get("res", data) if isinstance(data, dict) else {}
        texts.extend(str(value) for value in ocr_res.get("rec_texts", []))
        confidences.extend(float(value) for value in ocr_res.get("rec_scores", []))
    if not texts:
        return "", 0.0
    text = best_plate_text(texts)
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return text, round(confidence, 4)


# --- Backend: EasyOCR ---------------------------------------------------------

_PLATE_ALLOW = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

@lru_cache(maxsize=1)
def _easy_reader():
    import easyocr

    return easyocr.Reader(["en"], gpu=False, verbose=False)

def _read_easyocr(crop: Any) -> tuple[str, float]:
    np = _np()
    reader = _easy_reader()
    # Jalur cepat: recognizer saja. Deteksi (CRAFT) dilewati karena crop sudah
    # dipastikan pita teks plat oleh pipeline — hemat ~60% waktu. allowlist A-Z0-9
    # sekaligus mencegah karakter di luar format plat.
    fast = reader.recognize(crop, allowlist=_PLATE_ALLOW, detail=1)
    if fast:
        text = best_plate_text([item[1] if len(item) == 3 else item[0] for item in fast])
        conf = float(np.mean([item[2] if len(item) == 3 else item[1] for item in fast]))
        if len(re.sub(r"[^A-Z0-9]", "", text.upper())) >= 3 and conf >= 0.3:
            return normalize_plate(text), round(min(conf, 0.99), 4)

    # Fallback: multi-baris (plat truk) atau hasil lemah -> deteksi penuh.
    results = reader.readtext(
        crop,
        allowlist=_PLATE_ALLOW,
        paragraph=False,
        width_ths=0.9,
        link_threshold=0.2,
        mag_ratio=1.5,
    )
    if not results:
        results = reader.readtext(
            crop,
            allowlist=_PLATE_ALLOW,
            paragraph=True,
            width_ths=0.9,
            link_threshold=0.2,
            mag_ratio=1.5,
        )
    if not results:
        return "", 0.0
    # Plat 2 baris = 2 kotak setinggi sebanding; baris tanggal/tambahan dibuang.
    boxes = []
    for item in results:
        if len(item) == 3:
            points, text, confidence = item
        elif len(item) == 2:
            points, text = item
            confidence = 0.5
        else:
            continue
        pts = np.asarray(points, dtype="float32")
        height = float(pts[:, 1].max() - pts[:, 1].min())
        baseline = float(pts[:, 1].max())
        left = float(pts[:, 0].min())
        boxes.append((baseline, left, height, float(confidence), text))
    if not boxes:
        return "", 0.0
    max_height = max(b[2] for b in boxes)
    rows = [b for b in boxes if b[2] >= 0.6 * max_height]
    if not rows:
        rows = [max(boxes, key=lambda b: b[2])]
    # Urut baca: sejajar baseline (baris) dulu, baru kiri->kanan.
    rows.sort(key=lambda b: (b[0], b[1]))
    text = best_plate_text([b[4] for b in rows])
    confidence = float(np.mean([b[3] for b in rows]))
    return text, round(min(confidence, 0.99), 4)


def _enhance_ocr_crop(crop: Any) -> Any:
    """Pertegas suffix tipis tanpa mengganti crop asli untuk audit."""
    cv2, np = _cv2(), _np()
    if getattr(crop, "size", 0) == 0:
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if min(gray.shape[:2]) >= 3:
        gray = cv2.medianBlur(gray, 3)  # anti-moiré layar monitor
    scale = max(2.0, 120.0 / max(gray.shape[0], 1))
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    blur = cv2.GaussianBlur(enhanced, (0, 0), 1.2)
    sharpened = cv2.addWeighted(enhanced, 1.5, blur, -0.5, 0)
    adaptive = cv2.adaptiveThreshold(
        sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
    )
    return cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR)

# Kunci cache = digest SHA-1 crop (bukan bytes mentah yang mahal di-hash berulang
# dan boros memori), dengan TTL agar frame kamera yang lambat berubah tidak
# mengunci hasil lama selamanya (L6).
_ROBUST_CACHE: dict[tuple[str, str, bytes], tuple[float, tuple[str, float, str]]] = {}
_CACHE_TTL_SECONDS = 30.0

def _looks_like_plate(text: str) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    return bool(re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,3}[A-Z]{0,3}", compact))

def band_crops(crop: Any, count: int = 4, frac: float = 0.38) -> list[Any]:
    """Pita horizontal beririsan (zoom + crop otomatis saat belum terbaca).

    Deteksi teks OCR hanya akurat pada crop rapat. Pada crop besar/tinggi, baris
    plat tenggelam dan yang terbaca justru stiker tanggal. Pita beririsan
    menjamin baris plat selalu masuk satu pita yang cukup rapat.
    """
    height_total = int(getattr(crop, "shape", (0,))[0] or 0)
    if height_total < 40:
        return []
    height = max(int(height_total * frac), 32)
    span = max(height_total - height, 0)
    step = max(span // max(count - 1, 1), 1)
    starts = list(range(0, span + 1, step))[:count]
    return [crop[start : start + height] for start in starts]

def _plate_candidates(texts: list[str]) -> list[str]:
    """Kandidat teks plat dari kumpulan kotak hasil OCR.

    OCR mengembalikan banyak kotak ('H', '2518', 'OK', stiker '12·26').
    Menggabungkan semuanya selalu salah; teks plat biasanya hanya gabungan
    1-3 kotak berurutan.
    """
    compact = [re.sub(r"[^A-Z0-9]", "", (text or "").upper()) for text in texts]
    compact = [text for text in compact if text]
    candidates: list[str] = []
    for size in (1, 2, 3):
        for index in range(len(compact) - size + 1):
            candidates.append("".join(compact[index : index + size]))
    joined = "".join(compact)
    if joined not in candidates:
        candidates.append(joined)
    return candidates

def best_plate_text(texts: list[str]) -> str:
    """Pilih kandidat paling menyerupai NRKB — bukan teks terpanjang/tergabung.

    Aturan keras (permintaan pengguna): plat nomor SELALU diawali huruf.
    Kandidat yang bentuk mentahnya diawali angka — sisa stiker tanggal
    ('04 25' -> 'D425'), fragmen nomor — ditolak, jangan diubah jadi plat
    palsu oleh koreksi prefix. Tidak ada kandidat berawal huruf = tidak terbaca.

    Skor = (berformat NRKB, panjang): 'H2518OK' menang atas '2518OK', 'OK',
    maupun gabungan penuh 'H2518OK1226' yang menyertakan stiker tanggal.
    """
    best_text, best_score = "", (-1, -1)
    for candidate in _plate_candidates(texts):
        if not candidate[:1].isalpha():
            continue
        normalized = normalize_plate(candidate)
        valid = 1 if _looks_like_plate(normalized) else 0
        score = (valid, len(normalized) if valid else 0)
        if score > best_score:
            best_score, best_text = score, normalized
    return best_text

def read_plate_robust(
    crop: Any, vehicle_class: str | None = None, *, fast: bool = False
) -> tuple[str, float, str]:
    """Baca plat dengan strategi ulang: baris per baris + zoom + deglare + threshold.

    Skor per pembacaan = (format plat, golongan NRKB cocok kelas kendaraan,
    keyakinan) — sengketa B/8, 6/G, 1/I diputus :func:`normalize_plate` sesuai
    struktur NRKB. Berhenti awal bila valid + conf >= 0.80. Hasil di-cache per
    crop: auto-scan frame sama jadi instan.
    """
    from . import pipeline

    digest = hashlib.sha1(crop.tobytes()).digest()
    cache_key = (vehicle_class or "", "fast" if fast else "full", digest)
    cached = _ROBUST_CACHE.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    best = ("", 0.0, "")
    best_score = (-1, -1, -1, -1.0)

    def attempt(variant: Any) -> bool:
        """Satu kali baca. True bila hasil sudah layak dan usaha boleh berhenti."""
        nonlocal best, best_score
        if getattr(variant, "size", 0) == 0:
            return False
        text, confidence, backend = read_plate(variant)
        valid = 1 if _looks_like_plate(text) else 0
        fits = 1 if number_fits_class(text, vehicle_class) else 0
        # Panjang mendahului keyakinan: 'A8X' conf 1.0 tidak boleh mengalahkan
        # 'L1399ABX' yang sama-sama berformat NRKB.
        score = (valid, fits, min(len(text), 9), confidence)
        if score > best_score:
            best_score, best = score, (text, confidence, backend)
        # Berhenti awal hanya untuk hasil yang terlihat utuh: potongan pendek
        # seperti 'A8X'/'D226' sering hanya sebagian plat / sisa stiker.
        return bool(valid and confidence >= 0.80 and len(text) >= 5)

    # Baris dibaca terpisah lebih dulu. Stiker tanggal/masa berlaku di bawah
    # baris plat punya kontras lebih tinggi dan selalu "menang" baca bila
    # seluruh crop dipakai sebagai satu teks — kasus "yang terbaca malah tahun".
    rows = pipeline.text_rows(crop) if getattr(crop, "size", 0) else []
    if len(rows) > 1:
        rows.sort(key=lambda row: row.shape[0] * row.shape[1], reverse=True)
        bases = [*rows, crop]
    else:
        bases = [crop]

    for base in bases:
        if attempt(base):
            break
    else:
        # Belum terbaca -> naikkan kelas citra: zoom polos dulu (terbukti
        # memulihkan huruf kecil pada foto jarak jauh), lalu deglare/binarisasi.
        target = bases[0]
        cv2 = _cv2()
        scales = (2.0,) if fast else (2.0, 4.0)
        ladder: list[Any] = [
            cv2.resize(target, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC) for s in scales
        ]
        ladder += [
            pipeline.enhance_plate(target, 160),
            pipeline.enhance_plate(target, 240),
            pipeline.deglare(target),
            _enhance_ocr_crop(target),
        ]
        if fast:
            ladder = ladder[:2]  # auto-scan tetap coba ulang, tapi tetap murah
        for variant in ladder:
            if attempt(variant):
                break

    if len(_ROBUST_CACHE) >= 32:
        _ROBUST_CACHE.pop(next(iter(_ROBUST_CACHE)))
    _ROBUST_CACHE[cache_key] = (time.monotonic(), best)
    return best

@lru_cache(maxsize=1)
def active_backend() -> str:
    import importlib.util

    if config.OCR_BACKEND in {"paddleocr", "easyocr", "template_match"}:
        requested = config.OCR_BACKEND
    else:
        requested = "paddleocr"
    if requested == "paddleocr" and importlib.util.find_spec("paddleocr"):
        return "paddleocr"
    if requested == "easyocr" and importlib.util.find_spec("easyocr"):
        return "easyocr"
    if importlib.util.find_spec("paddleocr"):
        return "paddleocr"
    if importlib.util.find_spec("easyocr"):
        return "easyocr"
    return "template_match"

def warmup() -> None:
    """Muat model OCR di background saat server start — scan pertama tidak lambat."""
    try:
        backend = active_backend()
        if backend == "easyocr":
            _easy_reader()
        elif backend == "paddleocr":
            _paddle_reader()
    except Exception:  # noqa: BLE001 - warmup gagal jangan menahan server
        pass

def read_plate(crop: Any) -> tuple[str, float, str]:
    """Baca plat dari crop yang sudah di-deskew. -> (teks, keyakinan, backend)."""
    if active_backend() == "paddleocr":
        try:
            text, confidence = _read_paddle(crop)
            return text, confidence, "paddleocr"
        except Exception:  # noqa: BLE001 - fallback tetap menjaga service hidup
            LOGGER.exception("PaddleOCR gagal membaca crop plat")
    if active_backend() == "easyocr":
        try:
            text, confidence = _read_easyocr(crop)
            return text, confidence, "easyocr"
        except Exception:  # noqa: BLE001 - jatuh ke template_match bila model belum ada
            pass
    text, confidence = _read_template_multiline(crop)
    return text, confidence, "template_match"
