"""Generator citra sintetis untuk demo tanpa CCTV fisik.

Menghasilkan frame "kendaraan" lengkap dengan plat nomor dan stiker, lalu
menambahkan degradasi realistis (perspektif, blur, noise, pencahayaan) supaya
pipeline benar-benar diuji, bukan diberi citra bersih.

Empat siluet didukung agar variasi geometri plat benar-benar terwakili:
mobil (plat 1 baris lebar), motor (plat kecil 1 baris), truk/bus (plat 2 baris),
dan plat custom/dealer (rasio bebas).
"""

from __future__ import annotations

import random
import re
from typing import Any

from .ocr import _load_font
from .pipeline import _cv2, _np
from .vehicles import PROFILES

PLATE_FONT_RATIO = 0.60

def split_two_rows(text: str) -> tuple[str, str]:
    """Pecah teks plat jadi (baris atas, baris bawah) untuk TNKB 2 baris.

    Format Indonesia: prefix + angka di baris atas, suffix huruf di baris bawah.
    """
    compact = re.sub(r"[^A-Za-z0-9]", "", text or "").upper()
    match = re.match(r"^([A-Z]{0,2}[0-9]{1,4})([A-Z]{0,3})$", compact)
    if not match:
        half = max(len(compact) // 2, 1)
        return compact[:half], compact[half:]
    top, bottom = match.groups()
    return (top or compact), (bottom or top)

def render_plate(text: str, height: int = 110, rows: int = 1, aspect: float | None = None) -> Any:
    """Render plat putih-teks-hitam bergaya Indonesia (1 atau 2 baris).

    ``aspect`` memaksa rasio papan (lebar/tinggi) sesuai kelas kendaraan —
    penting supaya siluet tahu bedanya plat mobil (3.54) dan plat motor (2.38).
    Font dikecilkan bila teks lebih lebar dari papan, jadi rasio papan selalu
    terjaga dan bukan teks yang menentukan lebar.
    """
    cv2, np = _cv2(), _np()
    from PIL import Image, ImageDraw

    top, bottom = split_two_rows(text)
    label = f"{top}\n{bottom}" if rows >= 2 else text
    pad = int(height * 0.55)
    allowed_text_w = max(int(round(height * aspect)) - pad, 8) if aspect else 0
    ratio = PLATE_FONT_RATIO * (0.62 if rows >= 2 else 1.0)
    font_size = max(int(height * ratio), 10)

    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    for _ in range(6):  # monoton mengecil, 6 putaran cukup untuk konvergen
        font = _load_font(font_size)
        box = probe.multiline_textbbox((0, 0), label, font=font, spacing=4, align="center")
        text_w = int(box[2] - box[0])
        if not allowed_text_w or text_w <= allowed_text_w or font_size <= 8:
            break
        font_size = max(int(font_size * allowed_text_w / text_w), 8)

    text_h = int(box[3] - box[1])
    width = max(text_w + pad, int(round(height * aspect)) if aspect else 0)
    canvas = Image.new("RGB", (width, height), (246, 246, 242))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(18, 18, 18), width=max(2, height // 20))
    draw.multiline_text(
        ((width - text_w) // 2 - box[0], (height - text_h) // 2 - box[1]),
        label,
        fill=(12, 12, 12),
        font=font,
        spacing=4,
        align="center",
    )
    return cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)


def render_sticker(payload: str, size: int = 130) -> Any:
    """Render QR code sebagai stiker (putih dengan margin)."""
    cv2 = _cv2()
    encoder = cv2.QRCodeEncoder_create()
    qr = encoder.encode(payload)
    qr = cv2.resize(qr, (size, size), interpolation=cv2.INTER_NEAREST)
    bgr = cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)
    return cv2.copyMakeBorder(bgr, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def _attach(plate: Any, sticker: Any | None, x0: int, y0: int, body_w: int, body_h: int) -> tuple[Any, Any, int, int, int]:
    """Hitung ukuran & posisi plat+stiker di bumper. -> (plat, stiker, px, py, plate_h)."""
    cv2 = _cv2()
    plate_h = max(int(body_h * 0.20), 24)
    plate_w = max(int(plate.shape[1] * plate_h / plate.shape[0]), 24)
    plate_resized = cv2.resize(plate, (plate_w, plate_h), interpolation=cv2.INTER_AREA)
    px = int(x0 + body_w * 0.5 - plate_w * 0.5)
    py = int(y0 + body_h * 0.66)

    sticker_resized = None
    sticker_h = max(int(plate_h * 0.85), 20)
    sx = px + plate_w + max(int(body_w * 0.03), 6)
    if sticker is not None and sx + sticker_h < x0 + body_w:
        sticker_resized = cv2.resize(sticker, (sticker_h, sticker_h), interpolation=cv2.INTER_AREA)
    return plate_resized, sticker_resized, px, py, plate_h

def _paste(canvas: Any, plate: Any, sticker: Any | None, x0: int, y0: int, body_w: int, body_h: int) -> None:
    plate_resized, sticker_resized, px, py, plate_h = _attach(plate, sticker, x0, y0, body_w, body_h)
    canvas[py : py + plate_resized.shape[0], px : px + plate_resized.shape[1]] = plate_resized
    if sticker_resized is not None:
        sx = px + plate_resized.shape[1] + max(int(body_w * 0.03), 6)
        canvas[py : py + sticker_resized.shape[0], sx : sx + sticker_resized.shape[1]] = sticker_resized

def _draw_car(canvas: Any, plate: Any, sticker: Any | None, scale: float) -> None:
    """Gambar tampak belakang kendaraan sederhana + tempel plat & stiker."""
    cv2 = _cv2()
    h, w = canvas.shape[:2]
    body_w = int(w * scale)
    body_h = int(body_w * 0.62)
    x0 = (w - body_w) // 2
    y0 = int(h * 0.30)

    body_color = (58, 62, 74)
    cv2.rectangle(canvas, (x0, y0), (x0 + body_w, y0 + body_h), body_color, -1)
    cv2.rectangle(canvas, (x0, y0), (x0 + body_w, y0 + body_h), (24, 26, 32), 3)

    # Kaca belakang
    glass = (int(x0 + body_w * 0.12), int(y0 + body_h * 0.10))
    cv2.rectangle(
        canvas,
        glass,
        (int(x0 + body_w * 0.88), int(y0 + body_h * 0.42)),
        (36, 44, 58),
        -1,
    )
    # Lampu belakang
    lamp_h = max(int(body_h * 0.10), 4)
    for fx in (0.06, 0.80):
        cv2.rectangle(
            canvas,
            (int(x0 + body_w * fx), int(y0 + body_h * 0.50)),
            (int(x0 + body_w * (fx + 0.14)), int(y0 + body_h * 0.50) + lamp_h),
            (40, 40, 190),
            -1,
        )

    _paste(canvas, plate, sticker, x0, y0, body_w, body_h)

def _draw_motorcycle(canvas: Any, plate: Any, sticker: Any | None, scale: float) -> None:
    """Motor: badan sempit, plat kecil menempel di bawah lampu belakang."""
    cv2 = _cv2()
    h, w = canvas.shape[:2]
    body_w = int(w * scale * 0.42)
    body_h = int(body_w * 1.15)
    x0 = (w - body_w) // 2
    y0 = int(h * 0.34)

    cv2.rectangle(canvas, (x0, y0), (x0 + body_w, y0 + body_h), (46, 46, 52), -1)
    cv2.rectangle(canvas, (x0, y0), (x0 + body_w, y0 + body_h), (22, 22, 26), 3)
    cv2.rectangle(  # lampu belakang
        canvas,
        (int(x0 + body_w * 0.28), int(y0 + body_h * 0.12)),
        (int(x0 + body_w * 0.72), int(y0 + body_h * 0.26)),
        (40, 40, 200),
        -1,
    )
    cv2.circle(  # roda
        canvas,
        (int(x0 + body_w * 0.5), int(y0 + body_h * 0.94)),
        max(int(body_w * 0.16), 5),
        (28, 28, 30),
        -1,
    )

    plate_h = max(int(body_h * 0.26), 18)
    plate_w = max(int(plate.shape[1] * plate_h / plate.shape[0]), 18)
    plate_resized = cv2.resize(plate, (plate_w, plate_h), interpolation=cv2.INTER_AREA)
    px = int(x0 + body_w * 0.5 - plate_w * 0.5)
    py = int(y0 + body_h * 0.62)
    canvas[py : py + plate_h, px : px + plate_w] = plate_resized

    if sticker is not None:
        sticker_h = max(int(plate_h * 0.9), 14)
        sticker_resized = cv2.resize(sticker, (sticker_h, sticker_h), interpolation=cv2.INTER_AREA)
        sx = px + plate_w + max(int(body_w * 0.05), 4)
        sy = py
        if sx + sticker_h < x0 + body_w + int(body_w * 0.4):
            canvas[sy : sy + sticker_h, sx : sx + sticker_h] = sticker_resized

def _draw_truck(canvas: Any, plate: Any, sticker: Any | None, scale: float) -> None:
    """Truk/bus: badan besar tinggi, plat 2 baris di bumper."""
    cv2 = _cv2()
    h, w = canvas.shape[:2]
    body_w = int(w * min(scale * 1.1, 0.55))
    body_h = min(int(body_w * 1.30), int(h * 0.80))
    x0 = (w - body_w) // 2
    y0 = int(h * 0.12)

    cv2.rectangle(canvas, (x0, y0), (x0 + body_w, y0 + body_h), (74, 76, 82), -1)
    cv2.rectangle(canvas, (x0, y0), (x0 + body_w, y0 + body_h), (26, 26, 30), 4)
    # Kotak pintu ditahan agak ke bawah supaya plaza plat di bumper selalu muat.
    cv2.rectangle(
        canvas,
        (int(x0 + body_w * 0.10), int(y0 + body_h * 0.08)),
        (int(x0 + body_w * 0.90), int(y0 + body_h * 0.62)),
        (62, 64, 70),
        -1,
    )
    for fx in (0.08, 0.78):  # lampu
        cv2.rectangle(
            canvas,
            (int(x0 + body_w * fx), int(y0 + body_h * 0.66)),
            (int(x0 + body_w * (fx + 0.14)), int(y0 + body_h * 0.76)),
            (46, 46, 170),
            -1,
        )

    _paste(canvas, plate, sticker, x0, y0, body_w, body_h)

_DRAWERS = {
    "car": _draw_car,
    "motorcycle": _draw_motorcycle,
    "truck": _draw_truck,
    "custom": _draw_car,
}

# Kelas kendaraan yang boleh diminta lewat /api/simulate.
VEHICLES = tuple(_DRAWERS)

def vehicle_rows(vehicle: str) -> int:
    """Jumlah baris plat bawaan sebuah kelas kendaraan (truk/bus = 2 baris)."""
    return 2 if vehicle == "truck" else 1

def plate_for(vehicle: str, text: str, height: int) -> Any:
    """Render plat dengan ukuran proporsional kelas kendaraan (rasio TNKB asli)."""
    profile = PROFILES.get(vehicle, PROFILES["car"])
    return render_plate(text, height=height, rows=vehicle_rows(vehicle), aspect=profile.ideals[0])


def _degrade(image: Any, *, brightness: float, blur: int, noise: float, angle: float, rng: random.Random) -> Any:
    """Terapkan degradasi fotometrik + geometrik ringan."""
    cv2, np = _cv2(), _np()
    h, w = image.shape[:2]

    if abs(angle) > 0.01:
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        image = cv2.warpAffine(image, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE)

    if blur > 0:
        ksize = blur * 2 + 1
        image = cv2.GaussianBlur(image, (ksize, ksize), 0)

    image = cv2.convertScaleAbs(image, alpha=brightness, beta=(brightness - 1.0) * 40)

    if noise > 0:
        noise_map = np.random.default_rng(rng.randrange(1 << 30)).normal(0, noise, image.shape)
        image = np.clip(image.astype(np.float32) + noise_map, 0, 255).astype(np.uint8)
    return image


def render_scene(
    plate_text: str,
    sticker_payload: str | None = None,
    *,
    width: int = 1280,
    height: int = 720,
    scale: float = 0.42,
    brightness: float = 1.0,
    blur: int = 0,
    noise: float = 5.0,
    angle: float = 0.0,
    rows: int = 1,
    vehicle: str = "car",
    seed: int = 0,
) -> Any:
    """Satu frame sintetis berisi kendaraan + plat + (opsional) stiker."""
    cv2, np = _cv2(), _np()
    rng = random.Random(seed)

    # Latar: aspal dengan gradien + marka.
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        shade = int(70 + 45 * (y / height))
        canvas[y, :] = (shade, shade - 4, shade - 8)
    cv2.line(canvas, (0, int(height * 0.86)), (width, int(height * 0.86)), (200, 200, 200), 4)

    profile = PROFILES.get(vehicle, PROFILES["car"])
    plate = render_plate(
        plate_text,
        height=max(int(height * 0.16), 40),
        rows=rows if vehicle != "truck" else max(rows, 2),
        aspect=profile.ideals[0],
    )
    # QR demo ikut rantai kepercayaan: tanda tangani bila kunci tersedia (H2).
    if sticker_payload and not sticker_payload.startswith("SGS1."):
        try:
            from .sticker import create_signed_token

            sticker_payload = create_signed_token(1, sticker_payload)
        except RuntimeError:
            pass  # tanpa kunci: QR mentah tetap dirender, decoder menolaknya
    sticker = render_sticker(sticker_payload) if sticker_payload else None
    _DRAWERS.get(vehicle, _draw_car)(canvas, plate, sticker, scale)

    return _degrade(canvas, brightness=brightness, blur=blur, noise=noise, angle=angle, rng=rng)

def cctv_pair(
    plate_text: str,
    sticker_payload: str | None = None,
    *,
    seed: int = 0,
    hard: bool = False,
    vehicle: str = "car",
) -> list[tuple[str, Any, str]]:
    """Dua frame korelasi: CCTV 1 (pendekatan, jauh) + CCTV 2 (gate, dekat).

    ``hard=True`` mensimulasikan kondisi buruk (malam + hujan) untuk menguji
    jalur kegagalan OCR. ``vehicle`` memilih kelas kendaraan (siluet + baris plat).
    """
    rows = vehicle_rows(vehicle)
    if hard:
        approach = render_scene(
            plate_text, sticker_payload, scale=0.20, brightness=0.55, blur=3, noise=26,
            angle=-6.0, seed=seed, rows=rows, vehicle=vehicle,
        )
        gate = render_scene(
            plate_text, sticker_payload, scale=0.30, brightness=0.62, blur=2, noise=18,
            angle=4.0, seed=seed + 1, rows=rows, vehicle=vehicle,
        )
    else:
        approach = render_scene(
            plate_text, sticker_payload, scale=0.30, brightness=1.0, blur=1, noise=6,
            angle=-2.0, seed=seed, rows=rows, vehicle=vehicle,
        )
        gate = render_scene(
            plate_text, sticker_payload, scale=0.46, brightness=1.05, blur=0, noise=4,
            angle=1.5, seed=seed + 1, rows=rows, vehicle=vehicle,
        )
    return [("cctv1_approach", approach, "approach"), ("cctv2_gate", gate, "gate")]
