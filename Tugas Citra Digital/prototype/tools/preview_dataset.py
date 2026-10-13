"""Buat contact sheet dataset agar bisa diperiksa mata.

    python tools\\preview_dataset.py                  # 2 sheet: deteksi + OCR
    python tools\\preview_dataset.py --part detect --n 36 --cols 6
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import dataset  # noqa: E402

TILE = 220
BAR = 34


def _grid(tiles: list, cols: int, out: pathlib.Path) -> None:
    import cv2
    import numpy as np

    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * (TILE + BAR), cols * TILE, 3), 24, dtype=np.uint8)
    for index, (tile, caption) in enumerate(tiles):
        r, c = divmod(index, cols)
        y0 = r * (TILE + BAR)
        h = tile.shape[0]
        scale = min(TILE / tile.shape[1], TILE / h)
        resized = cv2.resize(tile, (max(1, int(tile.shape[1] * scale)), max(1, int(h * scale))))
        oy = y0 + (TILE - resized.shape[0]) // 2
        ox = c * TILE + (TILE - resized.shape[1]) // 2
        sheet[oy : oy + resized.shape[0], ox : ox + resized.shape[1]] = resized
        cv2.rectangle(sheet, (c * TILE, y0 + TILE), (c * TILE + TILE - 1, y0 + TILE + BAR - 1), (40, 40, 40), -1)
        cv2.putText(
            sheet,
            caption[:34],
            (c * TILE + 6, y0 + TILE + 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)
    print(f"-> {out} ({sheet.shape[1]}x{sheet.shape[0]})")


def sheet_detect(n: int, cols: int, out: pathlib.Path) -> None:
    import cv2

    tiles = []
    for sample in dataset.detection_samples(n):
        image = cv2.imread(str(sample.path))
        if image is None:
            continue
        for x1, y1, x2, y2 in sample.boxes:
            cv2.rectangle(image, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 3)
        caption = f"{sample.path.stem.split('_')[0]} ({len(sample.boxes)} box)"
        tiles.append((image, caption))
    _grid(tiles, cols, out)


def sheet_overlay(n: int, cols: int, out: pathlib.Path) -> None:
    """GT (hijau) vs deteksi pipeline (merah) — untuk melihat kenapa IoU = 0."""
    import cv2

    from app import pipeline

    tiles = []
    for sample in dataset.detection_samples(n):
        image = cv2.imread(str(sample.path))
        if image is None or not sample.boxes:
            continue
        for x1, y1, x2, y2 in sample.boxes:
            cv2.rectangle(image, (int(x1), int(y1)), (int(x2), int(y2)), (0, 220, 0), 2)
        for det in pipeline.detect_plates(image):
            pts = [[int(x), int(y)] for x, y in det.quad]
            cv2.polylines(image, [__import__("numpy").array(pts)], True, (0, 0, 255), 2)
        tiles.append((image, f"{sample.path.stem.split('_')[0]} gt={len(sample.boxes)}"))
    _grid(tiles, cols, out)


def sheet_zoom(n: int, cols: int, out: pathlib.Path) -> None:
    """Crop GT (zoom-in) + versi enhance — untuk melihat kualitas plat asli."""
    import cv2

    from app import pipeline

    tiles = []
    for sample in dataset.detection_samples(n):
        image = cv2.imread(str(sample.path))
        if image is None or not sample.boxes:
            continue
        x1, y1, x2, y2 = sample.boxes[0]
        crop = image[int(y1) : int(y2), int(x1) : int(x2)]
        if crop.size == 0:
            continue
        tiles.append((crop, f"{sample.path.stem.split('_')[0]} raw"))
        tiles.append((pipeline.enhance_plate(crop), f"{sample.path.stem.split('_')[0]} enhanced"))
    _grid(tiles, cols, out)


def sheet_text(n: int, cols: int, out: pathlib.Path) -> None:
    import cv2

    tiles = []
    for path, label in dataset.text_samples(n):
        image = cv2.imread(str(path))
        if image is not None:
            tiles.append((image, label))
    _grid(tiles, cols, out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default="both", choices=("detect", "text", "overlay", "zoom", "both"))
    parser.add_argument("--n", type=int, default=24)
    parser.add_argument("--cols", type=int, default=6)
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "data" / "diag")
    args = parser.parse_args()

    if args.part in ("detect", "both"):
        sheet_detect(args.n, args.cols, args.out / "sheet_detect.png")
    if args.part in ("overlay", "both"):
        sheet_overlay(args.n, args.cols, args.out / "sheet_overlay.png")
    if args.part in ("zoom", "both"):
        sheet_zoom(args.n, args.cols, args.out / "sheet_zoom.png")
    if args.part in ("text", "both"):
        sheet_text(args.n, args.cols, args.out / "sheet_text.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
