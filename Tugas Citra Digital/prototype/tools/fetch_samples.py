#!/usr/bin/env python3
"""Ambil contoh data dari internet untuk memperkaya dataset training.

Sumber: Wikimedia Commons (berlisensi bebas — atribusi wajib, dicatat di
``dataset_extra/SOURCES.md``):

- Positif: ``Category:License plates of Indonesia`` — foto plat nomor asli.
  Dipseudo-label otomatis dengan ``runs/.../smartgate/weights/best.pt``
  (konfidence >= 0.5). Tanpa bbox yakin -> tidak dipakai (bukan data salah).
- Negatif: berkas acak Commons. Bila model justru mendeteksi plat di dalamnya,
  berkas dibuang — negatif harus benar-benar tanpa plat.

Hasil digabung ke ``dataset_merged/train`` dengan prefiks ``web_``.

    python tools/fetch_samples.py --positives 30 --negatives 30
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "SmartGatePrototype/1.0 (tugas pengolahan citra digital)"}
WEIGHTS = ROOT / "runs" / "detect" / "runs" / "detect" / "smartgate" / "weights" / "best.pt"

RASTER = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()

def _imageinfo(params: dict) -> list[dict]:
    params.update({"action": "query", "format": "json", "formatversion": "2", "prop": "imageinfo",
                   "iiprop": "url|extmetadata", "iiurlwidth": "1280"})
    response = requests.get(API, params=params, headers=UA, timeout=30)
    response.raise_for_status()
    out = []
    for page in response.json().get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl"):
            continue
        meta = info.get("extmetadata", {})
        out.append({
            "title": page.get("title", ""),
            "url": info["thumburl"],
            "page": info.get("descriptionurl", ""),
            "license": _strip_html(meta.get("LicenseShortName", {}).get("value", "?")),
            "author": _strip_html(meta.get("Artist", {}).get("value", "?")),
        })
    return out

def fetch_plates(limit: int) -> list[dict]:
    items = _imageinfo({"generator": "search", "gsrsearch": "indonesian license plate plat nomor kendaraan",
                        "gsrnamespace": "6", "gsrlimit": str(limit * 3)})
    return [i for i in items if Path(i["title"]).suffix.lower() in RASTER][:limit]

def fetch_random(limit: int) -> list[dict]:
    out: list[dict] = []
    bad = re.compile(r"plate|nomor|license|plat|registration", re.I)
    for _ in range(5):  # batch sampai cukup, batasi agar tidak berputar
        items = _imageinfo({"generator": "random", "grnnamespace": "6", "grmlimit": str(limit * 6)})
        for item in items:
            if Path(item["title"]).suffix.lower() in RASTER and not bad.search(item["title"]):
                out.append(item)
            if len(out) >= limit:
                return out
    return out

def download(item: dict, dest: Path) -> bool:
    for attempt in (1, 2):
        try:
            response = requests.get(item["url"], headers=UA, timeout=60)
            if response.status_code == 429 and attempt == 1:  # rate-limit Commons
                time.sleep(10)
                continue
            response.raise_for_status()
            dest.write_bytes(response.content)
            time.sleep(1.5)  # sopan ke server Commons
            return True
        except Exception as exc:  # noqa: BLE001 - unduhan gagal jangan mematikan proses
            print(f"  gagal {item['title']}: {exc}")
            if attempt == 1:
                time.sleep(5)
    return False

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positives", type=int, default=30)
    parser.add_argument("--negatives", type=int, default=30)
    args = parser.parse_args()

    if not WEIGHTS.exists():
        print(f"ERROR: {WEIGHTS} belum ada — training minimal 1 epoch dulu.")
        return 1

    from ultralytics import YOLO
    import cv2

    model = YOLO(str(WEIGHTS))
    extra = ROOT / "dataset_extra"
    train = ROOT / "dataset_merged" / "train"
    for folder in (extra / "plates", extra / "no_plates"):
        folder.mkdir(parents=True, exist_ok=True)

    sources: list[str] = ["# Sumber data unduhan (atribusi lisensi)", ""]
    used_plates = used_negatives = 0

    # Bersihkan hasil unduhan sebelumnya supaya tidak ada gambar tanpa label
    # yang tertinggal (bagi YOLO, gambar tanpa label = negatif — salah semua).
    for stale in list((train / "images").glob("web_*")) + list((train / "labels").glob("web_*")):
        stale.unlink()

    print("== Positif: foto plat nomor Indonesia ==")
    for item in fetch_plates(args.positives):
        ext = Path(item["title"]).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            continue
        name = "web_p_" + re.sub(r"\W+", "_", Path(item["title"]).stem) + ext
        path = extra / "plates" / name
        if not download(item, path):
            continue
        try:
            result = model.predict(str(path), conf=0.5, verbose=False)[0]
        except Exception as exc:  # noqa: BLE001 - satu berkas rusak jangan gagalkan semua
            print(f"  - lewati {name}: {exc}")
            path.unlink(missing_ok=True)
            continue
        boxes = result.boxes
        if len(boxes) == 0:
            path.unlink()  # tanpa bbox yakin = tidak jadi data training
            continue
        img = cv2.imread(str(path))
        h, w = img.shape[:2]
        lines = []
        for box in boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            lines.append(f"0 {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
        shutil.copy2(path, train / "images" / f"web_p_{used_plates:03d}_{name}")
        (train / "labels" / f"web_p_{used_plates:03d}_{Path(name).stem}.txt").write_text("\n".join(lines))
        sources.append(f"- {item['title']} — {item['license']} — {item['author']} — {item['page']}")
        used_plates += 1
        print(f"  + plat {name} ({len(boxes)} bbox)")

    print("== Negatif: gambar tanpa plat ==")
    for item in fetch_random(args.negatives):
        ext = Path(item["title"]).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            continue
        name = "web_n_" + re.sub(r"\W+", "_", Path(item["title"]).stem) + ext
        path = extra / "no_plates" / name
        if not download(item, path):
            continue
        try:
            result = model.predict(str(path), conf=0.5, verbose=False)[0]
        except Exception as exc:  # noqa: BLE001 - satu berkas rusak jangan gagalkan semua
            print(f"  - lewati {name}: {exc}")
            path.unlink(missing_ok=True)
            continue
        if len(result.boxes) > 0:
            path.unlink()  # ternyata ada plat -> bukan negatif
            print(f"  - buang {name} (model melihat plat)")
            continue
        shutil.copy2(path, train / "images" / f"web_n_{used_negatives:03d}_{name}")
        (train / "labels" / f"web_n_{used_negatives:03d}_{Path(name).stem}.txt").write_text("")
        sources.append(f"- {item['title']} — {item['license']} — {item['author']} — {item['page']}")
        used_negatives += 1
        print(f"  + negatif {name}")

    (extra / "SOURCES.md").write_text("\n".join(sources) + "\n", encoding="utf-8")
    print(f"\nSelesai: {used_plates} positif + {used_negatives} negatif -> dataset_merged/train")
    print(f"Atribusi: {extra / 'SOURCES.md'}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
