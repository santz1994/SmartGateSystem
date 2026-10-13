"""Loader dataset nyata `Datasheet 2` (dua bagian).

* ``plate_detection_dataset`` — anotasi COCO (``annotations.json``), dipakai untuk
  mengukur akurasi **lokalisasi** plat (IoU terhadap ``detect_plates``).
* ``plate_text_dataset`` — crop plat 416x416 + ``label.csv`` (teks plat asli),
  dipakai untuk mengukur akurasi **pembacaan** plat (OCR).

Modul ini sengaja hanya berisi pembacaan file; metriknya ada di
:mod:`tools.eval_dataset`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterator, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"
DETECTION_DIR = DATASETS / "detection"
TEXT_DIR = DATASETS / "text"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp")

# COCO membaur jpg + png; urutan daftar ini menentukan urutan hasil, jadi
# evaluasi dua kali berturut-turut memberi urutan citra yang sama.
def _images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT), key=lambda p: p.name)


class Sample(NamedTuple):
    """Satu citra + daftar kotak kebenaran (piksel, format ``x1, y1, x2, y2``)."""

    path: Path
    boxes: list[tuple[float, float, float, float]]


def detection_available() -> bool:
    return (DETECTION_DIR / "annotations" / "annotations.json").is_file()


def text_available() -> bool:
    return (TEXT_DIR / "label.csv").is_file()


def _load_coco() -> dict[str, list[tuple[float, float, float, float]]]:
    """``{file_name: [kotak]}`` dari anotasi COCO (``bbox`` = x, y, w, h)."""
    payload = json.loads((DETECTION_DIR / "annotations" / "annotations.json").read_text(encoding="utf-8"))
    names = {img["id"]: img["file_name"] for img in payload["images"]}
    per_file: dict[str, list[tuple[float, float, float, float]]] = {}
    for ann in payload["annotations"]:
        name = names.get(ann["image_id"])
        if name is None:
            continue
        x, y, w, h = (float(v) for v in ann["bbox"])
        per_file.setdefault(name, []).append((x, y, x + w, y + h))
    return per_file


def detection_samples(limit: int | None = None) -> Iterator[Sample]:
    """Citra lokalisasi + kotak kebenaran, hanya yang filenya ada di disk."""
    per_file = _load_coco()
    for index, path in enumerate(_images(DETECTION_DIR / "images")):
        if limit is not None and index >= limit:
            return
        yield Sample(path, per_file.get(path.name, []))


def text_samples(limit: int | None = None) -> Iterator[tuple[Path, str]]:
    """Citra crop plat + teks kebenaran (``label.csv``)."""
    folder = TEXT_DIR / "dataset"
    present = {p.name for p in _images(folder)}
    with (TEXT_DIR / "label.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    count = 0
    for row in rows:
        name = (row.get("filename") or "").strip()
        if not name or name not in present:
            continue
        if limit is not None and count >= limit:
            return
        count += 1
        yield folder / name, (row.get("label") or "").strip()
