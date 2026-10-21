"""Isi bobot YOLO ke layout yang diharapkan aplikasi (runs/detect/.../weights/).

Bobot tidak berada di git (terlalu besar). Sumber pencarian, berurutan:
1. berkas/URL eksplisit dari CLI (``--source`` / ``--url``);
2. folder artefak lokal ``smartgate-artifacts-<VAR>`` (hasil ekspor Colab);
3. arsip ``smartgate-artifacts-<VAR>.zip`` di root repo;
4. URL unduhan per varian: env ``SGS_WEIGHTS_URL_<VAR>``.

Jalan: ``python tools/fetch_weights.py`` (idempoten — yang sudah ada dibiarkan).
Hanya stdlib; tidak butuh dependency tambahan.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROTOTYPE = Path(__file__).resolve().parent.parent

VARIANTS = {
    "yolov8n": "Y8N",
    "yolov8x": "Y8X",
    "yolo11n": "Y11N",
}
TARGETS = {
    name: PROTOTYPE / "runs" / "detect" / f"smartgate-colab-v6-{name}" / "weights" / "best.pt"
    for name in VARIANTS
}
# File pendukung untuk halaman /training (metrik evaluasi per varian).
EXTRAS = ("evaluation_summary.json", "results.csv", "confusion_matrix.png")


def _copy_extras(source_dir: Path, target: Path) -> None:
    for name in EXTRAS:
        candidate = source_dir / name
        if candidate.is_file():
            shutil.copy2(candidate, target.parent.parent / name)


def _from_zip(archive: Path, target: Path) -> bool:
    if not archive.is_file():
        return False
    with zipfile.ZipFile(archive) as handle:
        members = [n for n in handle.namelist() if n.endswith("best.pt")]
        if not members:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        with handle.open(members[0]) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        extras = [n for n in handle.namelist() if Path(n).name in EXTRAS]
        for name in extras:
            with handle.open(name) as src, (target.parent.parent / Path(name).name).open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return True


def _from_url(url: str, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    try:
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 - URL berasal dari operator
        tmp.replace(target)
        return True
    except OSError:
        tmp.unlink(missing_ok=True)
        return False


def _try_source(name: str, source: Path | None, target: Path) -> bool:
    if source is None:
        return False
    if source.is_dir():
        found = source / "best.pt"
        if not found.is_file():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, target)
        _copy_extras(source, target)
        print(f"  salin  {name}: {found} -> {target.relative_to(PROTOTYPE)}")
        return True
    if _from_zip(source, target):
        print(f"  zip    {name}: {source.name} -> {target.relative_to(PROTOTYPE)}")
        return True
    return False


def fetch(name: str, source: Path | None = None, url: str | None = None) -> bool:
    target = TARGETS[name]
    if target.is_file():
        print(f"  ada    {name}: {target.relative_to(PROTOTYPE)}")
        return True
    if _try_source(name, source, target):
        return True
    artifacts = VARIANTS[name]
    for candidate in (ROOT / f"smartgate-artifacts-{artifacts}", ROOT / f"smartgate-artifacts-{artifacts}.zip"):
        if _try_source(name, candidate, target):
            return True
    env_url = url or os.getenv(f"SGS_WEIGHTS_URL_{name.upper()}", "").strip()
    if env_url and _from_url(env_url, target):
        print(f"  unduh  {name}: {env_url}")
        return True
    print(f"  GAGAL  {name}: sumber tidak ditemukan (smartgate-artifacts-{artifacts} / --url)")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Isi bobot YOLO ke runs/detect/")
    parser.add_argument("variants", nargs="*", help="varian yang diisi: yolov8n yolov8x yolo11n (default: semua)")
    parser.add_argument("--source", type=Path, help="folder/zip artefak lokal")
    parser.add_argument("--url", help="URL unduhan best.pt")
    args = parser.parse_args()
    unknown = [name for name in args.variants if name not in VARIANTS]
    if unknown:
        parser.error(f"varian tidak dikenal: {', '.join(unknown)}")
    ok = all(fetch(name, args.source, args.url) for name in (args.variants or sorted(VARIANTS)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
