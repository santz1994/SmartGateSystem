#!/usr/bin/env python3
"""Gabungkan SEMUA sumber dataset deteksi plat ke plat-nomor/ (dataset utama).

plat-nomor/ berisi dataset Roboflow asli (train/valid/test) — ISI ASLI TIDAK
DISENTUH. Semua sumber lain ditambahkan ke plat-nomor/train dengan prefix:
  mg_  dataset_merged dari smartgate-all-datasets.zip
  rf_  Indonesia License Plate Detection.v1i.yolov8.zip (train saja)
  kg_  Kaggle plate dataset.zip (COCO -> YOLO)
  bg_  no-plate-backgrounds.zip + dataset-extra-package.zip (label kosong)

Aturan:
  - gambar yang stem/hash-nya ada di valid/test plat-nomor TIDAK masuk train
    (anti-leakage);
  - duplikat (hash sama) hanya disimpan sekali;
  - sumber OCR (alpr glyph, plate_text, plate_reference) sengaja tidak ikut;
  - data.yaml ditulis ulang dengan path lokal (train/images, dst).

Pemakaian:
  python tools/merge_datasets.py            # tambah sekali jalan
  python tools/merge_datasets.py --force    # hapus hasil tambahan lama, ulangi
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

FILE = Path(__file__).resolve()
PROTOTYPE = FILE.parents[1]
REPO = FILE.parents[3]

BIG_ZIP = PROTOTYPE / "smartgate-all-datasets.zip"
RF_ZIP = PROTOTYPE / "dataset_extra" / "downloads" / "Indonesia License Plate Detection.v1i.yolov8.zip"
KG_ZIP = PROTOTYPE / "dataset_extra" / "downloads" / "Kaggle plate dataset.zip"
BG_ZIPS = [REPO / "no-plate-backgrounds.zip", REPO / "dataset-extra-package.zip"]
OUT_ROOT = PROTOTYPE / "plat-nomor"
PREFIXES = ("mg_", "rf_", "kg_", "bg_")

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_yolo_lines(raw: bytes) -> list[str] | None:
    out = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        f = line.split()
        if len(f) != 5:
            return None
        try:
            cls = int(f[0])
            vals = [float(v) for v in f[1:]]
        except ValueError:
            return None
        if cls != 0 or any(v < 0 or v > 1 for v in vals):
            return None
        out.append(line)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Hapus hasil tambahan (prefix mg_/rf_/kg_/bg_) lalu ulangi")
    args = parser.parse_args()

    for path in [BIG_ZIP, RF_ZIP, KG_ZIP, *BG_ZIPS]:
        if not path.is_file():
            print(f"ERROR: sumber tidak ditemukan: {path}")
            return 1

    train_img = OUT_ROOT / "train" / "images"
    train_lbl = OUT_ROOT / "train" / "labels"
    for d in (train_img, train_lbl):
        d.mkdir(parents=True, exist_ok=True)

    # --- Guard: stem & hash valid/test asli (jangan bocor ke train) ---
    guard_stems: set[str] = set()
    guard_hashes: set[str] = set()
    for split in ("valid", "test"):
        img_dir = OUT_ROOT / split / "images"
        if not img_dir.is_dir():
            continue
        for p in img_dir.iterdir():
            if p.suffix.lower() in IMG_EXTS:
                guard_stems.add(p.stem)
                guard_hashes.add(sha256(p.read_bytes()))

    # --- Idempotensi: --force menghapus hasil tambahan sebelumnya ---
    if args.force:
        removed = 0
        for folder in (train_img, train_lbl):
            for p in folder.iterdir():
                if p.stem.startswith(PREFIXES):
                    p.unlink()
                    removed += 1
        print(f"--force: {removed} file hasil tambahan lama dihapus.")

    # Dedup terhadap train yang sudah ada
    train_hashes = {
        sha256(p.read_bytes()) for p in train_img.iterdir() if p.suffix.lower() in IMG_EXTS
    }
    print(f"plat-nomor: {len(train_hashes)} gambar train awal, "
          f"{len(guard_stems)} gambar valid/test (dijaga dari kebocoran)")

    summary = {"mg": 0, "rf": 0, "kg": 0, "bg": 0, "skipped_leakage": 0, "skipped_dup": 0, "invalid": 0}

    def add_train(img: bytes, suffix: str, label: str, prefix: str) -> None:
        h = sha256(img)
        if h in guard_hashes:
            summary["skipped_leakage"] += 1
            return
        if h in train_hashes:
            summary["skipped_dup"] += 1
            return
        counter = summary[prefix]
        stem = f"{prefix}_{counter:05d}"
        while stem in guard_stems or (train_img / f"{stem}{suffix}").exists():
            counter += 1
            stem = f"{prefix}_{counter:05d}"
        (train_img / f"{stem}{suffix}").write_bytes(img)
        (train_lbl / f"{stem}.txt").write_text(label + ("\n" if label else ""))
        train_hashes.add(h)
        summary[prefix] = counter + 1

    # --- mg_: dataset_merged dari arsip besar ---
    big = zipfile.ZipFile(BIG_ZIP)
    members = set(big.namelist())
    mg_imgs = sorted(
        n for n in members
        if n.startswith("dataset_merged/train/images/") and Path(n).suffix.lower() in IMG_EXTS
    )
    for n in mg_imgs:
        stem = Path(n).stem
        lbl_name = f"dataset_merged/train/labels/{stem}.txt"
        lines = valid_yolo_lines(big.read(lbl_name)) if lbl_name in members else None
        if lines is None:
            summary["invalid"] += 1
            continue
        add_train(big.read(n), Path(n).suffix.lower(), "\n".join(lines), "mg")

    # --- rf_: Roboflow Indonesia License Plate Detection, split train saja ---
    rf = zipfile.ZipFile(RF_ZIP)
    rf_names = set(rf.namelist())
    for n in sorted(x for x in rf_names if x.startswith("train/images/") and Path(x).suffix.lower() in IMG_EXTS):
        stem = Path(n).stem
        lbl_name = f"train/labels/{stem}.txt"
        lines = valid_yolo_lines(rf.read(lbl_name)) if lbl_name in rf_names else None
        if lines is None:
            summary["invalid"] += 1
            continue
        add_train(rf.read(n), Path(n).suffix.lower(), "\n".join(lines), "rf")

    # --- kg_: Kaggle plate dataset (COCO -> YOLO) ---
    kg = zipfile.ZipFile(KG_ZIP)
    kg_names = set(kg.namelist())
    ann_name = next(n for n in kg_names if n.endswith("annotations.json"))
    coco = json.loads(kg.read(ann_name))
    images_meta = {im["id"]: im for im in coco.get("images", [])}
    by_img: dict[int, list] = {}
    for a in coco.get("annotations", []):
        by_img.setdefault(a["image_id"], []).append(a)
    plate_cats = [c["id"] for c in coco.get("categories", []) if "plate" in c["name"].lower()] or [
        c["id"] for c in coco.get("categories", [])
    ]
    # Lokasi gambar dicari dari nama file — struktur folder tiap rilis bisa beda.
    kg_img_members = {
        Path(n).name: n for n in kg_names
        if Path(n).suffix.lower() in IMG_EXTS and not n.endswith("/")
    }
    for mid, im in sorted(images_meta.items()):
        img_name = kg_img_members.get(Path(im["file_name"]).name)
        if img_name is None:
            summary["invalid"] += 1
            continue
        W, H = float(im.get("width", 0) or 0), float(im.get("height", 0) or 0)
        lines, ok = [], True
        for a in by_img.get(mid, []):
            if a.get("category_id") not in plate_cats:
                continue
            x, y, w, h = (float(v) for v in a["bbox"])
            if not (W and H):
                ok = False
                break
            cx, cy, bw, bh = (x + w / 2) / W, (y + h / 2) / H, w / W, h / H
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                ok = False
                break
            lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        if not ok or not lines:
            summary["invalid"] += 1
            continue
        add_train(kg.read(img_name), Path(img_name).suffix.lower(), "\n".join(lines), "kg")

    # --- bg_: background tanpa plat (label kosong) ---
    for bg_zip in BG_ZIPS:
        bg = zipfile.ZipFile(bg_zip)
        for n in sorted(set(bg.namelist())):
            if Path(n).suffix.lower() in IMG_EXTS and "images/" in n and not n.endswith("/"):
                add_train(bg.read(n), Path(n).suffix.lower(), "", "bg")

    total_train = sum(1 for p in train_img.iterdir() if p.suffix.lower() in IMG_EXTS)
    print("Tambahan:", summary)
    print(f"Total train akhir: {total_train} gambar")

    # --- data.yaml path lokal + validasi pasangan ---
    (OUT_ROOT / "data.yaml").write_text(
        "train: train/images\nval: valid/images\ntest: test/images\n\nnc: 1\nnames: ['number-plate']\n",
        encoding="utf-8",
    )
    for split in ("train", "valid", "test"):
        imgs = {p.stem for p in (OUT_ROOT / split / "images").iterdir() if p.suffix.lower() in IMG_EXTS}
        lbls = {p.stem for p in (OUT_ROOT / split / "labels").iterdir()}
        if imgs != lbls:
            print(f"ERROR {split}: pasangan image/label tidak cocok ({len(imgs)} vs {len(lbls)})")
            return 1
        boxes = sum(
            1
            for lp in (OUT_ROOT / split / "labels").glob("*.txt")
            for line in lp.read_text().splitlines()
            if line.strip()
        )
        print(f"{split}: {len(imgs)} gambar, {boxes} kotak")
    print("data.yaml diperbarui. Dataset gabungan siap:", OUT_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
