"""Hasilkan citra contoh ke ``data/samples/`` untuk uji manual & lampiran laporan.

    python tools/make_samples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, pipeline, simulate  # noqa: E402

SAMPLES = [
    # (nama berkas, plat, stiker, kondisi buruk?)
    ("01_terdaftar_siang.jpg", "B 1234 XYZ", "STK-WRG-0042", False),
    ("02_karyawan_siang.jpg", "D 5678 ABC", "STK-KRY-0107", False),
    ("03_tamu_booking.jpg", "B 9012 QWE", None, False),
    ("04_asing_siang.jpg", "B 9999 ZZZ", None, False),
    ("05_terdaftar_malam_hujan.jpg", "B 1234 XYZ", "STK-WRG-0042", True),
    ("06_asing_malam_hujan.jpg", "B 8888 YYY", None, True),
]


def main() -> int:
    out = config.DATA_DIR / "samples"
    out.mkdir(parents=True, exist_ok=True)

    for index, (name, plate, sticker_code, hard) in enumerate(SAMPLES):
        frames = simulate.cctv_pair(plate, sticker_code, seed=index * 13 + 1, hard=hard)
        for label, image, _role in frames:
            path = out / f"{Path(name).stem}_{label}.jpg"
            path.write_bytes(pipeline._cv2().imencode(".jpg", image)[1].tobytes())
            print(f"  {path.relative_to(config.BASE_DIR)}")

    print(f"\n{len(SAMPLES) * 2} citra contoh ditulis ke {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
