"""Pipeline pengolahan citra: pre-processing, deteksi plat & stiker, best-frame.

Import berat (``cv2``/``numpy``) sengaja dilakukan *lazy* di dalam fungsi. Modul
ini diimpor saat Flask start, jadi menahan import di level modul akan menambah
~250 ms ke setiap cold start tanpa manfaat. Setelah import pertama, Python
meng-cache modul sehingga pemanggilan berikutnya hanya lookup dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import vehicles

# --- Ambang internal pipeline (bukan ambang keputusan bisnis) ---
# Pencarian kontur dibuat permisif (gabungan semua kelas kendaraan); penyaringan
# ketat berbasis jumlah karakter dilakukan setelahnya di :func:`detect_plates`.
PLATE_MAX_AREA_RATIO = 0.35
PLATE_TARGET_HEIGHT = 64

# Plat harus selalu terlihat seperti papan: kontras tinggi, tepi rapi. Ambang ini
# membuang false-positive "segitiga" (potongan aspal) yang punya tepi kabur.
PLATE_MIN_EDGE_RATIO = 0.012  # tepi Canny / luas bbox
PLATE_MIN_CONTRAST = 28.0  # std dev citra abu-abu (diturunkan untuk plat redup/kecil)
PLATE_ASPECT_IDEAL = 3.0  # fallback skor bila tahap OCR dimatikan


def _cv2():
    import cv2

    return cv2


def _np():
    import numpy as np

    return np


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

def preprocess(image: Any) -> dict[str, Any]:
    """CLAHE -> bilateral -> grayscale.

    Urutan ini penting: CLAHE memperkuat noise, jadi denoising harus *setelah*
    CLAHE, bukan sebelumnya.
    """
    cv2 = _cv2()
    stages: dict[str, Any] = {"original": image}

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
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

def enhance_plate(crop: Any, target_height: int = 160) -> Any:
    """Upscale + perbaiki kontras plat untuk inspeksi manual / OCR.

    Dipakai saat OCR gagal: satpam tetap bisa membaca plat dari citra yang
    diperbesar dan dikontraskan. Tiga langkah: upscale kubik (zoom-in),
    CLAHE pada kanal L (perbaikan kontras), unsharp mask (tajamkan huruf).
    """
    cv2, np = _cv2(), _np()
    h, w = crop.shape[:2]
    if h == 0 or w == 0:
        return crop
    scale = max(target_height / float(h), 1.0)  # hanya perbesar, jangan pernah perkecil
    up = cv2.resize(crop, (max(int(round(w * scale)), 1), max(int(round(h * scale)), 1)), interpolation=cv2.INTER_CUBIC)

    lab = cv2.cvtColor(up, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    merged = cv2.merge([clahe.apply(l_ch), a_ch, b_ch])
    enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    blur = cv2.GaussianBlur(enhanced, (0, 0), 3.0)
    return cv2.addWeighted(enhanced, 1.6, blur, -0.6, 0)


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

def plate_texture_ok(crop: Any) -> bool:
    """Tolak kandidat yang tidak menyerupai papan plat.

    Dua ciri: kepadatan tepi cukup tinggi (ada huruf) dan kontras cukup besar
    (papan terang dengan huruf gelap). Langit/aspal licin akan gagal di sini.
    """
    cv2, np = _cv2(), _np()
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return False
    edges = cv2.Canny(gray, 60, 180)
    h, w = gray.shape
    if float(edges.sum() / 255) / max(h * w, 1) < PLATE_MIN_EDGE_RATIO:
        return False
    return float(np.std(gray)) >= PLATE_MIN_CONTRAST

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

def detect_plates(image: Any, max_candidates: int = 4) -> list[Detection]:
    """Cari kandidat plat.

    Backend dipilih otomatis: bila ``app.detect_yolo`` punya bobot YOLO yang
    siap (env ``SGS_YOLO_WEIGHTS`` + paket ``ultralytics``), pakai itu; kalau
    tidak, jalur klasik OpenCV di bawah. Pemanggil tidak perlu tahu bedanya.
    """
    from . import detect_yolo

    if detect_yolo.available():
        return detect_yolo.detect(image, max_candidates)
    return detect_plates_classic(image, max_candidates)


def detect_plates_classic(image: Any, max_candidates: int = 4) -> list[Detection]:
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
    for kernel_w, threshold_value in ((17, otsu_global), (19, otsu_center)):
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

    detections: list[Detection] = []
    kept_quads: list[Any] = []
    for _, box in candidates:
        if len(detections) >= max_candidates:
            break
        quad = order_points(box)
        crop = four_point_transform(image, quad)
        if crop.size == 0 or not plate_texture_ok(crop):
            continue
        vehicle_class, orientation, glyphs, plausibility = plate_plausibility(crop)
        if plausibility <= 0.0:
            continue
        if any(_iou(quad, kept_quad) > 0.4 for kept_quad in kept_quads):
            continue
        kept_quads.append(quad)
        detections.append(
            Detection(
                kind="plate",
                quad=[[float(x), float(y)] for x, y in quad],
                confidence=plausibility,
                crop=normalize_plate_size(crop),
                meta={
                    "raw_crop": crop,
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
        cv2.polylines(out, [pts], True, colors.get(det.kind, (255, 255, 255)), 2)
        x, y, _, _ = det.bbox
        text = f"{det.kind} {det.confidence:.2f}"
        if det.payload:
            text += f" {det.payload}"
        cv2.putText(out, text, (x, max(y - 8, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colors.get(det.kind, (255, 255, 255)), 2)
    if label:
        cv2.putText(out, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return out
