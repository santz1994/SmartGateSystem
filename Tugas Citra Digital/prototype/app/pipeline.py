"""Pipeline pengolahan citra: pre-processing, deteksi plat & stiker, best-frame.

Import berat (``cv2``/``numpy``) sengaja dilakukan *lazy* di dalam fungsi. Modul
ini diimpor saat Flask start, jadi menahan import di level modul akan menambah
~250 ms ke setiap cold start tanpa manfaat. Setelah import pertama, Python
meng-cache modul sehingga pemanggilan berikutnya hanya lookup dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config, vehicles

# --- Ambang internal pipeline (bukan ambang keputusan bisnis) ---
# Pencarian kontur dibuat permisif (gabungan semua kelas kendaraan); penyaringan
# ketat berbasis jumlah karakter dilakukan setelahnya di :func:`detect_plates`.
PLATE_MAX_AREA_RATIO = 0.35
PLATE_TARGET_HEIGHT = 64

# Plat harus terlihat seperti papan berisi karakter. Warna absolut tidak dipakai
# karena TNKB dapat hitam, putih, kuning, merah, atau memiliki warna yang dekat
# dengan bodi kendaraan.
PLATE_MIN_EDGE_RATIO = 0.012  # tepi Canny / luas bbox
PLATE_MIN_CONTRAST = 28.0  # std dev citra abu-abu (diturunkan untuk plat redup/kecil)
PLATE_ASPECT_IDEAL = 3.0  # fallback skor bila tahap OCR dimatikan


def _cv2():
    import cv2

    return cv2


def _np():
    import numpy as np

    return np


def detection_preprocess(image: Any, gamma: float | None = None) -> Any:
    """Redam highlight sebelum detector, tanpa mengubah citra untuk audit/OCR.

    Gamma > 1 menggelapkan frame webcam yang overexposed. CLAHE dibatasi agar
    pola moire tidak ikut diperkuat secara agresif.
    """
    cv2, np = _cv2(), _np()
    value = float(gamma if gamma is not None else config.DETECTION_GAMMA)
    value = max(value, 0.1)
    lut = np.array([((index / 255.0) ** value) * 255 for index in range(256)], dtype=np.uint8)
    corrected = cv2.LUT(image, lut)
    lab = cv2.cvtColor(corrected, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=max(min(config.CLAHE_CLIP_LIMIT, 2.5), 0.1), tileGridSize=(8, 8)
    )
    return cv2.cvtColor(cv2.merge([clahe.apply(l_ch), a_ch, b_ch]), cv2.COLOR_LAB2BGR)


def detection_roi(image: Any, roi: tuple[float, float, float, float] | None = None) -> tuple[Any, tuple[int, int]]:
    """Ambil ROI bawah frame dan kembalikan offset koordinat frame asli.

    ``roi=None`` = seluruh frame diproses. ROI gerbang (buang atas frame agar
    jaket/wajah tidak jadi kandidat) hanya berlaku untuk frame kamera lebar;
    foto close-up/portret bisa memuat plat di mana saja dan justru terpotong.
    """
    np = _np()
    if roi is None:
        return image, (0, 0)
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi
    x1i, y1i = max(0, int(x1 * w)), max(0, int(y1 * h))
    x2i, y2i = min(w, int(x2 * w)), min(h, int(y2 * h))
    if x2i <= x1i or y2i <= y1i:
        return image, (0, 0)
    return image[y1i:y2i, x1i:x2i].copy(), (x1i, y1i)


def translate_detections(detections: list[Detection], offset: tuple[int, int]) -> list[Detection]:
    """Kembalikan koordinat hasil detector ROI ke ruang frame asli."""
    ox, oy = offset
    if not ox and not oy:
        return detections
    for detection in detections:
        detection.quad = [[x + ox, y + oy] for x, y in detection.quad]
    return detections


@dataclass
class Detection:
    """Satu objek terdeteksi (plat atau stiker) pada sebuah frame."""

    kind: str  # "plate" | "sticker"
    quad: list[list[float]]  # 4 titik: tl, tr, br, bl
    confidence: float
    payload: str | None = None  # hasil decode stiker (QR/AprilTag)
    crop: Any = None  # np.ndarray BGR
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        xs = [p[0] for p in self.quad]
        ys = [p[1] for p in self.quad]
        return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


# --- Geometri -----------------------------------------------------------------

def order_points(pts: Any) -> Any:
    """Urutkan 4 titik jadi (tl, tr, br, bl) — konvensi untuk warpPerspective."""
    np = _np()
    pts = np.asarray(pts, dtype="float32").reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype="float32",
    )


def four_point_transform(image: Any, pts: Any) -> Any:
    """Koreksi perspektif: ratakan plat miring jadi persegi tegak."""
    cv2, np = _cv2(), _np()
    rect = order_points(pts)
    tl, tr, br, bl = rect
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    w, h = max(int(round(width)), 1), max(int(round(height)), 1)
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, matrix, (w, h))


def laplacian_variance(gray: Any) -> float:
    """Ketajaman frame. Nilai tinggi = tepi tajam = frame bagus."""
    cv2 = _cv2()
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# --- Pre-processing -----------------------------------------------------------

def preprocess(image: Any, clahe_clip_limit: float | None = None, full: bool = True) -> dict[str, Any]:
    """CLAHE -> bilateral -> grayscale.

    Urutan ini penting: CLAHE memperkuat noise, jadi denoising harus *setelah*
    CLAHE, bukan sebelumnya. ``full=False`` melewati CLAHE+bilateral (frame
    preview cepat di hardware seadanya) dan hanya membuat gray murah untuk
    metrik ketajaman.
    """
    cv2 = _cv2()
    stages: dict[str, Any] = {"original": image}
    if not full:
        stages["gray"] = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return stages

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clip_limit = clahe_clip_limit if clahe_clip_limit is not None else config.CLAHE_CLIP_LIMIT
    clahe = cv2.createCLAHE(clipLimit=max(float(clip_limit), 0.1), tileGridSize=(8, 8))
    merged = cv2.merge([clahe.apply(l_ch), a_ch, b_ch])
    stages["clahe"] = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    stages["denoise"] = cv2.bilateralFilter(stages["clahe"], 9, 75, 75)
    stages["gray"] = cv2.cvtColor(stages["denoise"], cv2.COLOR_BGR2GRAY)
    return stages


def normalize_plate_size(crop: Any, target_height: int = PLATE_TARGET_HEIGHT) -> Any:
    """Resize ke tinggi tetap, aspect ratio dipertahankan (input tetap untuk OCR)."""
    cv2 = _cv2()
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return crop
    scale = target_height / float(h)
    return cv2.resize(crop, (max(int(round(w * scale)), 1), target_height), interpolation=cv2.INTER_LANCZOS4)

def deglare(crop: Any, clahe_clip_limit: float | None = None) -> Any:
    """Redam pantulan cahaya (piksel highlight jenuh) lalu rapikan kontras.

    Pantulan lampu/silau membuat sebagian karakter hilang di area putih jenuh.
    Area tersebut di-inpaint dari tepi sekitarnya, lalu CLAHE meratakan cahaya.
    """
    cv2, np = _cv2(), _np()
    if getattr(crop, "size", 0) == 0:
        return crop
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = ((gray >= 245) * 255).astype(np.uint8)
    if not mask.any():
        return crop
    fixed = cv2.inpaint(crop, mask, 3, cv2.INPAINT_TELEA)
    lab = cv2.cvtColor(fixed, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clip_limit = clahe_clip_limit if clahe_clip_limit is not None else min(
        config.CLAHE_CLIP_LIMIT + 0.5, 3.0
    )
    clahe = cv2.createCLAHE(clipLimit=max(float(clip_limit), 0.1), tileGridSize=(8, 8))
    return cv2.cvtColor(cv2.merge([clahe.apply(l_ch), a_ch, b_ch]), cv2.COLOR_LAB2BGR)

def enhance_plate(
    crop: Any, target_height: int = 160, clahe_clip_limit: float | None = None
) -> Any:
    """Upscale + perbaiki kontras plat untuk inspeksi manual / OCR.

    Dipakai saat OCR gagal: satpam tetap bisa membaca plat dari citra yang
    diperbesar dan dikontraskan. Tiga langkah: upscale kubik (zoom-in),
    CLAHE pada kanal L (perbaikan kontras), unsharp mask (tajamkan huruf).
    """
    cv2, np = _cv2(), _np()
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return crop
    # Redam moiré/pola piksel layar monitor: median 3x3 mematikan garis
    # interferensi tipis tanpa mengaburkan tepi karakter.
    if min(h, w) >= 3:
        crop = cv2.medianBlur(crop, 3)
    scale = max(target_height / float(h), 1.0)  # hanya perbesar, jangan pernah perkecil
    up = cv2.resize(crop, (max(int(round(w * scale)), 1), max(int(round(h * scale)), 1)), interpolation=cv2.INTER_CUBIC)

    lab = cv2.cvtColor(up, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clip_limit = clahe_clip_limit if clahe_clip_limit is not None else min(
        config.CLAHE_CLIP_LIMIT + 1.0, 3.0
    )
    clahe = cv2.createCLAHE(clipLimit=max(float(clip_limit), 0.1), tileGridSize=(8, 8))
    merged = cv2.merge([clahe.apply(l_ch), a_ch, b_ch])
    enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    # Tutup celah goresan karakter yang pudar (hujan/kotor) sebelum penajaman.
    enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))

    blur = cv2.GaussianBlur(enhanced, (0, 0), 3.0)
    return cv2.addWeighted(enhanced, 1.6, blur, -0.6, 0)

def grow_to_text_line(image: Any, bbox: tuple[int, int, int, int]) -> Any:
    """Lebarkan kotak kandidat ke seluruh baris tinta plat pada frame.

    Detektor sering hanya menutup sebagian plat ('NB' saja) sehingga OCR membaca
    potongan. Tumbuh dulu vertikal ke pita tinta, lalu horizontal ke seluruh
    baris — baris 'H 6249 NB' utuh kembali terbaca. Batas jangkauan 1x tinggi /
    1,5x lebar kotak agar tidak menelan seluruh frame.
    """
    cv2, np = _cv2(), _np()
    h_frame, w_frame = image.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, w_frame), min(y2, h_frame)
    if x2 <= x1 or y2 <= y1:
        return image[y1:y2, x1:x2].copy()

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    def grow(profile: Any, lo: int, hi: int, reach: int, gap: int) -> tuple[int, int]:
        closed = np.convolve((profile > 0).astype(np.uint8), np.ones(max(gap, 2), np.uint8), mode="same") > 0
        window_lo, window_hi = max(lo - reach, 0), min(hi + reach, len(profile))
        idx = np.nonzero(closed[window_lo:window_hi])[0]
        if idx.size == 0:
            return lo, hi
        return window_lo + int(idx.min()), window_lo + int(idx.max()) + 1

    row_ink = (binary[:, x1:x2] > 0).sum(axis=1)
    y1, y2 = grow(row_ink, y1, y2, max(y2 - y1, 4), max(int((y2 - y1) * 0.3), 4))
    col_ink = (binary[y1:y2, :] > 0).sum(axis=0)
    x1, x2 = grow(col_ink, x1, x2, int((x2 - x1) * 1.5), max(y2 - y1, 8))
    return image[y1:y2, x1:x2].copy()

def filter_gate_zone(
    detections: list[Detection],
    image_shape: Any,
    roi: tuple[float, float, float, float] = (0.10, 0.25, 0.90, 1.0),
    min_width_frac: float = 0.35,
) -> list[Detection]:
    """Filter multi-kendaraan: hanya plat di zona gerbang & berukuran wajar.

    - **ROI gate** (normalisasi x1,y1,x2,y2): centroid plat harus masuk kotak
      virtual di depan palang. Plat jalur seberang / latar belakang dibuang.
    - **Ukuran minimum relatif**: lebar plat >= ``min_width_frac`` x lebar
      kandidat terlebar (kendaraan mengekor jauh = lebih kecil = dibuang).

    Hanya aktif bila ada >1 kandidat — kandidat tunggal tetap lolos apa adanya
    (foto manual / sudut bebas). Tiap tahap punya fallback: bila semua gugur,
    pakai hasil tahap sebelumnya, tidak pernah kosong.
    """
    if len(detections) <= 1:
        return detections
    h, w = image_shape[:2]
    rx1, ry1, rx2, ry2 = roi[0] * w, roi[1] * h, roi[2] * w, roi[3] * h

    def centroid(det: Detection) -> tuple[float, float]:
        x1, y1, x2, y2 = det.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2

    in_zone = [
        det for det in detections
        if rx1 <= centroid(det)[0] <= rx2 and ry1 <= centroid(det)[1] <= ry2
    ] or detections

    max_width = max(det.bbox[2] - det.bbox[0] for det in in_zone)
    sized = [det for det in in_zone if det.bbox[2] - det.bbox[0] >= min_width_frac * max_width]
    return sized or in_zone

def closeness(det: Detection, image_shape: Any) -> float:
    """Skor kedekatan ke kamera: bbox besar + bawah frame = kendaraan terdekat."""
    h, w = image_shape[:2]
    x1, y1, x2, y2 = det.bbox
    area_ratio = ((x2 - x1) * (y2 - y1)) / max(h * w, 1)
    front = 1.5 if y2 > h * 0.6 else 1.0  # bawah frame = lebih dekat
    return area_ratio * front

def plate_border_score(crop: Any) -> float:
    """Skor bingkai plat: tepi gelap mengelilingi inti terang (papan TNKB).

    Subtitle/video (teks putih di latar hitam) punya tepi sama gelapnya dengan
    inti -> skor mendekati 0. Papan plat punya bingkai hitam + bidang terang
    -> skor tinggi. Faktor lembut, bukan gerbang keras (plat kusam tetap lolos)."""
    cv2, np = _cv2(), _np()
    if getattr(crop, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = gray.shape[:2]
    if h < 6 or w < 6:
        return 0.0
    strip = max(1, int(min(h, w) * 0.08))
    edges = np.concatenate([
        gray[:strip, :].ravel(), gray[-strip:, :].ravel(),
        gray[:, :strip].ravel(), gray[:, -strip:].ravel(),
    ])
    core = gray[strip:h - strip, strip:w - strip]
    if core.size == 0:
        return 0.0
    return float((edges < 70).mean() * (core > 140).mean())

def candidate_score(det: Detection, image_shape: Any) -> float:
    """Skor pemilihan kandidat: kemiripan bentuk plat dulu, kedekatan pemecah seri.

    Blob teks/video besar tidak boleh mengambil slot OCR hanya karena dekat
    atau lebar. ponytail: "kendaraan terdekat selalu menang" perlu MOT
    (ByteTrack/DeepSORT) — lihat saran Bab V."""
    border = float(det.meta.get("border", 0.5))
    return det.confidence + border + 0.1 * closeness(det, image_shape)

def drop_swallowed(detections: list[Detection]) -> list[Detection]:
    """Buang kandidat yang menelan kandidat lain — box rapat (plat asli) menang."""
    if len(detections) <= 1:
        return detections

    def area(det: Detection) -> int:
        x1, y1, x2, y2 = det.bbox
        return (x2 - x1) * (y2 - y1)

    kept: list[Detection] = []
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        swallows = False
        for other in detections:
            if other is det or area(other) >= area(det):
                continue
            ox1, oy1, ox2, oy2 = other.bbox
            inter = max(0, min(x2, ox2) - max(x1, ox1)) * max(0, min(y2, oy2) - max(y1, oy1))
            if inter / max(area(other), 1) > 0.8:
                swallows = True
                break
        if not swallows:
            kept.append(det)
    return kept

def pick_primary_plate(detections: list[Detection], image_shape: Any) -> Detection | None:
    """Pilih plat kendaraan paling dekat kamera saat ada >1 kandidat.

    Kandidat blob yang menelan box lebih rapat dibuang lebih dulu, lalu terdekat
    = bbox terbesar + paling bawah dalam frame. Itu kendaraan yang siap masuk
    gerbang; plat kendaraan lain diabaikan sampai maju sendiri. Keyakinan
    deteksi hanya pemecah seri.
    """
    kept = drop_swallowed(detections)
    if not kept:
        return None
    return max(kept, key=lambda det: (closeness(det, image_shape), det.confidence))


# --- Deteksi plat -------------------------------------------------------------

def _candidates_from_binary(binary: Any, frame_area: float) -> list[tuple[float, Any]]:
    """Kandidat kotak plat bergaya kotak (``minAreaRect`` sudah memutarkan kontur)."""
    cv2 = _cv2()
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found: list[tuple[float, Any]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < frame_area * vehicles.DETECT_BOUNDS.min_area_ratio:
            continue
        if area > frame_area * PLATE_MAX_AREA_RATIO:
            continue
        (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
        if rw < rh:
            rw, rh = rh, rw
        if rh <= 0 or rw < vehicles.DETECT_BOUNDS.min_width_px:
            continue
        aspect = rw / rh
        if not vehicles.DETECT_BOUNDS.aspect_min <= aspect <= vehicles.DETECT_BOUNDS.aspect_max:
            continue
        aspect_score, _ = vehicles.match_aspect(aspect)
        solidity = area / max(rw * rh, 1.0)
        found.append((0.6 * aspect_score + 0.4 * solidity, cv2.boxPoints(cv2.minAreaRect(contour))))
    return found


def _iou(a: Any, b: Any) -> float:
    np = _np()
    ax1, ay1 = a.min(axis=0)
    ax2, ay2 = a.max(axis=0)
    bx1, by1 = b.min(axis=0)
    bx2, by2 = b.max(axis=0)
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return float(inter / union) if union > 0 else 0.0


def _ink_mask(crop: Any, trim_x: float = 0.0, trim_y: float = 0.0) -> Any:
    """Mask tinta karakter. Tepi papan (border hitam) dibuang agar tidak
    dihitung sebagai karakter / baris."""
    cv2 = _cv2()
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = binary.shape
    ty, tx = int(h * trim_y), int(w * trim_x)
    if h > 2 * ty and w > 2 * tx:
        binary = binary[ty : h - ty, tx : w - tx]
    return binary

def ink_glyph_count(crop: Any) -> int:
    """Perkiraan jumlah karakter lewat proyeksi vertikal.

    Dipakai sebagai gerbang anti false-positive: potongan aspal/kaca tidak punya
    deretan 3+ komponen gelap sempit berjarak seragam.
    """
    binary = _ink_mask(crop, trim_x=0.03, trim_y=0.10)
    h, w = binary.shape
    if h < 8 or w < 8:
        return 0
    ink = (binary > 0).sum(axis=0)
    threshold = max(1, int(h * 0.08))
    count, in_run = 0, False
    for value in ink:
        if value > threshold:
            if not in_run:
                count += 1
            in_run = True
        else:
            in_run = False
    return count

def split_rows(crop: Any) -> list[Any]:
    """Pisahkan plat 1 baris vs 2 baris (proyeksi horizontal).

    Truk/bus memakai TNKB 2 baris: karakter atas & bawah dipisah celah mendatar
    kosong. Celah hanya diterima bila menyisakan dua pita yang sama-sama cukup
    tinggi, jadi margin/border pada plat 1 baris tidak ikut membelah papan.
    """
    binary = _ink_mask(crop)
    h = binary.shape[0]
    if h < 16:
        return [crop]
    ink = (binary > 0).sum(axis=1)
    empty = ink <= max(1, int(binary.shape[1] * 0.02))

    min_gap = max(int(h * 0.06), 2)
    min_band = h * 0.20
    gaps: list[tuple[int, int]] = []
    start = None
    for y, is_empty in enumerate(empty):
        if is_empty and start is None:
            start = y
        elif not is_empty and start is not None:
            gaps.append((start, y - start))
            start = None
    if start is not None:
        gaps.append((start, h - start))

    best = None
    for gap_start, gap_len in gaps:
        if gap_len < min_gap:
            continue
        if gap_start < min_band or h - (gap_start + gap_len) < min_band:
            continue
        if best is None or gap_len > best[1]:
            best = (gap_start, gap_len)
    if best is None:
        return [crop]
    return [crop[: best[0]], crop[best[0] + best[1] :]]

def text_rows(crop: Any, min_height_frac: float = 0.10) -> list[Any]:
    """Semua pita baris yang layak dibaca OCR, termasuk baris pendek.

    Berbeda dengan :func:`split_rows` (syaratnya ketat, khusus memutus plat
    1 vs 2 baris), fungsi ini longgar: stiker tanggal "12 26" setinggi ~10 px
    di bawah nomor plat harus ikut terpisah, karena bila seluruh crop dibaca
    sebagai satu teks, stiker itulah yang menang dibaca — bukan nomor plat.
    Pita tipis (border/bingkai) dibuang lewat ``min_height_frac``.
    """
    binary = _ink_mask(crop)
    h, w = binary.shape
    if h < 16:
        return [crop]
    ink = (binary > 0).sum(axis=1)
    threshold = max(1, int(w * 0.01))
    min_height = max(4, int(h * min_height_frac))
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for y, value in enumerate(ink):
        if value > threshold and start is None:
            start = y
        elif value <= threshold and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, h))
    bands = [(a, b) for a, b in bands if b - a >= min_height]
    if not bands:
        return [crop]
    return [crop[a:b] for a, b in bands[:4]]

def snap_to_text_band(crop: Any) -> tuple[Any, tuple[int, int, int, int]]:
    """Persempit kandidat ke pita teks plat, buang konteks bodi kendaraan.

    Kandidat klasik sering berupa blob besar (lampu + logo + plat) karena ambang
    menggabungkan area terang. Pita yang dipilih = baris dengan run karakter
    sempit terbanyak (deretan huruf/angka), bukan blok warna/teks kecil.
    Kembalikan ``(crop, (x1, y1, x2, y2))`` dengan kotak pada ruang crop awal.
    """
    cv2, np = _cv2(), _np()
    binary = _ink_mask(crop, trim_x=0.02, trim_y=0.02)
    h, w = binary.shape
    if h < 8 or w < 8:
        return crop, (0, 0, w, h)

    ink_rows = (binary > 0).sum(axis=1)
    row_thresh = max(1, int(w * 0.01))
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for y, value in enumerate(ink_rows):
        if value > row_thresh and start is None:
            start = y
        elif value <= row_thresh and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, h))
    bands = [(a, b) for a, b in bands if b - a >= max(4, int(h * 0.06))]
    if not bands:
        return crop, (0, 0, w, h)

    def glyph_runs(band: tuple[int, int]) -> int:
        sub = binary[band[0] : band[1]]
        ink = (sub > 0).sum(axis=0)
        thresh = max(1, int(sub.shape[0] * 0.10))
        runs, in_run = 0, False
        for value in ink:
            if value > thresh:
                if not in_run:
                    runs += 1
                in_run = True
            else:
                in_run = False
        return runs

    scored = [(glyph_runs(band), band[1] - band[0], band[0], band[1]) for band in bands]
    best = max(scored)
    # Sertakan baris kedua (plat truk 2 baris) bila sebanding dengan baris utama.
    keep = [(a, b) for runs, height, a, b in scored if height >= 0.5 * best[1] and runs >= 0.4 * best[0]]
    y1 = max(min(a for a, _ in keep) - int(h * 0.05), 0)
    y2 = min(max(b for _, b in keep) + int(h * 0.05), h)
    sub = binary[y1:y2]
    cols = np.nonzero((sub > 0).sum(axis=0) > max(1, int(sub.shape[0] * 0.05)))[0]
    if cols.size:
        margin = int(w * 0.04)
        x1, x2 = max(int(cols[0]) - margin, 0), min(int(cols[-1]) + margin, w)
    else:
        x1, x2 = 0, w
    snapped = crop[y1:y2, x1:x2]
    if not snapped.size:
        return crop, (0, 0, w, h)
    return snapped, (x1, y1, x2, y2)

def pad_crop(crop: Any, frac: float = 0.06) -> Any:
    """Beri margin di sekeliling crop hasil snap.

    Snap ke pita teks memangkas rapat ke tepi tinta — lengan huruf (Y, G, 4)
    yang samar bisa ikut terpotong lalu salah baca (mis. Y -> terbaca 1 ->
    dinormalisasi jadi I). Margin ini wajib ada pada setiap crop yang masuk OCR.
    """
    np = _np()
    if getattr(crop, "size", 0) == 0:
        return crop
    h, w = crop.shape[:2]
    py, px = max(int(h * frac), 2), max(int(w * frac), 2)
    return np.pad(crop, ((py, py), (px, px), (0, 0)), mode="edge")

def _tight_quad(quad: Any, crop_shape: Any, rect: tuple[int, int, int, int]) -> Any:
    """Petakan kotak ruang-crop kembali ke ruang gambar — quad jadi rapat."""
    cv2, np = _cv2(), _np()
    h, w = crop_shape[:2]
    x1, y1, x2, y2 = rect
    src = np.array([[[0, 0]], [[w - 1, 0]], [[w - 1, h - 1]], [[0, h - 1]]], dtype="float32")
    dst = np.asarray(quad, dtype="float32").reshape(4, 1, 2)
    matrix = cv2.getPerspectiveTransform(src, dst)
    box = np.array([[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]], dtype="float32")
    return order_points(cv2.perspectiveTransform(box, matrix).reshape(4, 2))

def plate_texture_ok(crop: Any) -> bool:
    """Tolak kandidat yang tidak menyerupai papan plat.

    Gunakan tepi dari luminance yang dinormalisasi lokal dan kanal warna LAB.
    Dengan begitu plat berwarna atau plat yang menyatu secara warna dengan bodi
    tetap dapat lolos bila karakter di dalamnya menghasilkan struktur tepi.
    """
    cv2, np = _cv2(), _np()
    if getattr(crop, "size", 0) == 0:
        return False
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    luminance = lab[:, :, 0]
    local = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(luminance)
    edges = cv2.Canny(local, 40, 140)
    color_edges = cv2.Canny(lab[:, :, 1], 35, 120) | cv2.Canny(lab[:, :, 2], 35, 120)
    combined = cv2.bitwise_or(edges, color_edges)
    h, w = luminance.shape
    edge_ratio = float(np.count_nonzero(combined)) / max(h * w, 1)
    local_contrast = float(np.std(local))
    raw_contrast = float(np.std(luminance))
    # Area benar-benar kosong tetap ditolak; ambang kontras hanya cadangan,
    # bukan lagi syarat mutlak seperti pada versi grayscale sebelumnya.
    if edge_ratio < PLATE_MIN_EDGE_RATIO:
        return False
    return local_contrast >= 18.0 or raw_contrast >= PLATE_MIN_CONTRAST or edge_ratio >= 0.025

def plate_plausibility(crop: Any) -> tuple[str, str, int, float]:
    """Nilai kelayakan kandidat: (kelas, orientasi, jumlah glyph, skor).

    Orientasi memakai istilah baku: ``horizontal`` = plat 1 baris,
    ``vertical`` = plat 2 baris (truk/bus & plat custom tertentu).
    """
    cv2, np = _cv2(), _np()
    rows = split_rows(crop)
    if len(rows) >= 2:
        counts = [ink_glyph_count(part) for part in rows]
        glyphs = sum(counts)
        row_count = 2 if all(c >= 2 for c in counts) else 1
    else:
        glyphs = ink_glyph_count(crop)
        row_count = 1

    h, w = crop.shape[:2]
    aspect = w / max(h, 1)
    key = vehicles.classify(aspect, row_count)
    profile = vehicles.PROFILES[key]

    if not profile.accepts_rows(row_count):
        key = "custom"
        profile = vehicles.PROFILES["custom"]
    floor = profile.glyph_floor(row_count)
    if glyphs < floor:
        return key, "horizontal", glyphs, 0.0

    ideal = min((abs(aspect - i) / i for i in profile.ideals), default=1.0)
    aspect_score = max(0.0, 1.0 - ideal)
    # Glyph berlebih biasanya blob gabungan, bukan plat: beri penalti ringan.
    count_score = 1.0 if glyphs <= floor + 3 else max(0.0, 1.0 - 0.1 * (glyphs - floor - 3))
    score = 0.6 * aspect_score + 0.4 * count_score
    return key, "vertical" if row_count >= 2 else "horizontal", glyphs, round(score, 4)

def detect_plates(image: Any, max_candidates: int = 12) -> list[Detection]:
    """Cari kandidat plat.

    Backend dipilih otomatis: bila ``app.detect_yolo`` punya bobot YOLO yang
    siap (env ``SGS_YOLO_WEIGHTS`` + paket ``ultralytics``), pakai itu; kalau
    tidak, jalur klasik OpenCV di bawah. Pemanggil tidak perlu tahu bedanya.
    """
    from . import detect_yolo
    # Crop ROI dulu, baru gamma+CLAHE — pemrosesan citra berat hanya pada kotak
    # kecil plat, bukan seluruh frame CCTV (kunci latensi rendah di CPU standar).
    # ROI gerbang hanya untuk frame kamera lebar (rasio >= 1.3). Foto manual /
    # close-up (square/portrait) diproses utuh — ROI justru memotong platnya.
    h_frame, w_frame = image.shape[:2]
    gate_roi = config.DETECTION_ROI if w_frame / max(h_frame, 1) >= 1.3 else None
    roi_image, offset = detection_roi(image, gate_roi)
    detector_image = detection_preprocess(roi_image)

    if detect_yolo.available():
        detections = detect_yolo.detect(detector_image, max_candidates)
        # Rekaman monitor dapat membuat pola plat berbeda jauh dari data
        # training YOLO (moire, pantulan, dan refresh layar). Dalam kondisi
        # itu YOLO bisa kosong meskipun papan plat terlihat jelas. Jalankan
        # detektor klasik hanya sebagai fallback kosong; jalur klasik tetap
        # memiliki gate tekstur, geometri, dan struktur glyph.
        if not detections:
            detections = detect_plates_classic(detector_image, max_candidates)
        return translate_detections(detections, offset)
    detections = detect_plates_classic(detector_image, max_candidates)
    return translate_detections(detections, offset)


def _merge_fragments(candidates: list[tuple[float, Any]]) -> list[tuple[float, Any]]:
    """Gabung fragmen teks plat yang berjajar jadi satu kandidat penuh.

    Pada kasus sulit (plat gelap, silau) kontur teks sering pecah per kata.
    Dua box yang sebaris (y-center dekat) dengan celah horizontal wajar
    digabung; aspek gabungan harus menyerupai plat agar tidak asal menyatu.
    """
    cv2, np = _cv2(), _np()
    boxes = [box for _, box in candidates]
    unions: list[Any] = []
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                ax1, ay1 = a.min(axis=0)
                ax2, ay2 = a.max(axis=0)
                bx1, by1 = b.min(axis=0)
                bx2, by2 = b.max(axis=0)
                h_max = max(ay2 - ay1, by2 - by1)
                if h_max <= 0:
                    continue
                centers_near = abs((ay1 + ay2) / 2 - (by1 + by2) / 2) < 0.8 * h_max
                gap = max(ax1, bx1) - min(ax2, bx2)
                if not (centers_near and 0 <= gap < 3.0 * h_max):
                    continue
                ux1, uy1 = min(ax1, bx1), min(ay1, by1)
                ux2, uy2 = max(ax2, bx2), max(ay2, by2)
                aspect = (ux2 - ux1) / max(uy2 - uy1, 1)
                if not 1.2 <= aspect <= vehicles.DETECT_BOUNDS.aspect_max:
                    continue
                union = np.array([[ux1, uy1], [ux2, uy1], [ux2, uy2], [ux1, uy2]], dtype="float32")
                boxes = [b for k, b in enumerate(boxes) if k not in (i, j)]
                boxes.append(union)
                unions.append(union)
                merged = True
                break
            if merged:
                break
    return [(0.6, box) for box in unions]

def detect_plates_classic(image: Any, max_candidates: int = 8) -> list[Detection]:
    """Cari kandidat plat dengan morfologi + kontur (klasik, tanpa ML).

    Alur: pencarian permisif (semua kelas kendaraan) -> gerbang kualitas
    (jumlah karakter + tekstur) -> skor akhir -> buang duplikat IoU.
    """
    cv2, np = _cv2(), _np()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    # Ambang Otsu global dari frame cenderung tenggelam saat malam (frame gelap
    # jadi mayoritas hitam putih). Ambil juga ambang dari ROI tengah, tempat
    # kendaraan berada.
    h, w = gray.shape
    cab = gray[int(h * 0.3) : int(h * 0.9), int(w * 0.2) : int(w * 0.8)]
    otsu_global = float(cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0])
    otsu_center = (
        float(cv2.threshold(cab, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]) if cab.size else otsu_global
    )

    frame_area = float(image.shape[0] * image.shape[1])
    candidates: list[tuple[float, Any]] = []
    for kernel_w, threshold_value in ((17, otsu_global), (19, otsu_center), (31, otsu_global)):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 5))
        closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
        for flag in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
            _, binary = cv2.threshold(closed, threshold_value, 255, flag)
            candidates.extend(_candidates_from_binary(binary, frame_area))

        # Adaptive threshold path: menangani plat putih pada bodi terang (Otsu gagal)
        for bs, C in ((21, -5), (25, -5)):
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, bs, C)
            candidates.extend(_candidates_from_binary(binary, frame_area))

        candidates.sort(key=lambda item: item[0], reverse=True)

    candidates.extend(_merge_fragments(candidates))
    candidates.sort(key=lambda item: item[0], reverse=True)

    detections: list[Detection] = []
    kept_quads: list[Any] = []
    for _, box in candidates:
        if len(detections) >= max_candidates:
            break
        quad = order_points(box)
        full_crop = four_point_transform(image, quad)
        border = plate_border_score(full_crop)  # bingkai dihitung sebelum snap memotong tepi
        crop, rect = snap_to_text_band(full_crop)  # buang konteks bodi dari blob kandidat
        if crop.size == 0 or not plate_texture_ok(crop):
            continue
        quad = _tight_quad(quad, full_crop.shape, rect)  # bbox akurat = pita teks saja
        vehicle_class, orientation, glyphs, plausibility = plate_plausibility(crop)
        if plausibility <= 0.0:
            continue
        if any(_iou(quad, kept_quad) > 0.4 for kept_quad in kept_quads):
            continue
        kept_quads.append(quad)
        ocr_view = pad_crop(crop)  # snap rapat -> margin wajib sebelum OCR
        detections.append(
            Detection(
                kind="plate",
                quad=[[float(x), float(y)] for x, y in quad],
                confidence=plausibility,
                crop=normalize_plate_size(ocr_view),
                meta={
                    "raw_crop": ocr_view,
                    "full_crop": pad_crop(full_crop),
                    "border": round(border, 4),
                    "vehicle_class": vehicle_class,
                    "orientation": orientation,
                    "glyph_count": glyphs,
                },
            )
        )
    return detections


# --- Deteksi stiker -----------------------------------------------------------

def detect_stickers(image: Any, max_candidates: int = 2) -> list[Detection]:
    """Deteksi stiker: QR (deterministik) + fallback blok warna jenuh."""
    cv2, np = _cv2(), _np()
    detections: list[Detection] = []

    detector = cv2.QRCodeDetector()
    try:
        ok, decoded, points, _ = detector.detectAndDecodeMulti(image)
    except cv2.error:
        ok, decoded, points = False, (), None
    if ok and points is not None:
        for payload, quad in zip(decoded, points):
            quad = order_points(quad)
            crop = four_point_transform(image, quad)
            detections.append(
                Detection(
                    kind="sticker",
                    quad=[[float(x), float(y)] for x, y in quad],
                    confidence=0.95 if payload else 0.5,
                    payload=payload or None,
                    crop=crop,
                    meta={"decoder": "qrcode"},
                )
            )

    if len(detections) < max_candidates:
        detections.extend(_detect_color_patches(image, max_candidates - len(detections)))
    return detections[:max_candidates]


def _detect_color_patches(image: Any, limit: int) -> list[Detection]:
    """Fallback: cari blok warna jenuh berbentuk persegi (stiker pudar/rusak)."""
    cv2, np = _cv2(), _np()
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 90, 60]), np.array([180, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    frame_area = float(image.shape[0] * image.shape[1])
    found: list[tuple[float, Any]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < frame_area * 0.0004 or area > frame_area * 0.08:
            continue
        (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
        if rh <= 0:
            continue
        aspect = rw / rh
        if not 0.6 <= aspect <= 1.7:
            continue
        squareness = 1.0 - min(abs(aspect - 1.0), 1.0)
        found.append((0.5 * squareness + 0.5 * min(area / (frame_area * 0.01), 1.0), cv2.boxPoints(cv2.minAreaRect(contour))))

    found.sort(key=lambda item: item[0], reverse=True)
    out: list[Detection] = []
    for score, box in found[:limit]:
        quad = order_points(box)
        out.append(
            Detection(
                kind="sticker",
                quad=[[float(x), float(y)] for x, y in quad],
                confidence=round(float(score) * 0.7, 4),  # pola warna = sinyal lemah
                payload=None,
                crop=four_point_transform(image, quad),
                meta={"decoder": "color_patch"},
            )
        )
    return out


# --- Best frame ---------------------------------------------------------------

def frame_score(image: Any, detection_confidence: float) -> float:
    """Skor pemilihan frame: ketajaman x keyakinan deteksi."""
    cv2 = _cv2()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return laplacian_variance(gray) * max(detection_confidence, 0.0)


def annotate(image: Any, detections: list[Detection], label: str = "") -> Any:
    """Gambar kotak deteksi + label untuk snapshot yang bisa diaudit manusia."""
    cv2 = _cv2()
    out = image.copy()
    colors = {"plate": (0, 200, 0), "sticker": (0, 165, 255)}
    for det in detections:
        pts = _np().array(det.quad, dtype="int32").reshape(-1, 1, 2)
        # Hanya kotak utama yang terang; kandidat sekunder tipis gelap agar
        # tampilan tidak "sibuk" saat latar penuh objek mirip plat.
        primary = bool(det.meta.get("primary"))
        color = colors.get(det.kind, (255, 255, 255)) if primary else (90, 90, 90)
        cv2.polylines(out, [pts], True, color, 3 if primary else 1)
        if not primary:
            continue
        x, y, _, _ = det.bbox
        text = f"{det.kind} {det.confidence:.2f}"
        if det.payload:
            text += f" {det.payload}"
        cv2.putText(out, text, (x, max(y - 8, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    if label:
        cv2.putText(out, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return out
