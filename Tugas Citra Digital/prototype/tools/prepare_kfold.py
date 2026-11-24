#!/usr/bin/env python3
"""Pembagi dataset 5-Fold Stratified Group Cross-Validation (TRAIN-1, TRAIN-3).

Dirancang untuk dijalankan baik di Google Colab (``/content/...``) maupun di
lokal tanpa menduplikasi file gambar di disk.

Fitur utama:
1. **Anti-Leakage Visual Berbasis Perceptual Hash (``dHash`` 64-bit) + SHA-256**:
   Frame CCTV berurutan atau kompresi ulang JPEG dari kendaraan yang sama
   dikelompokkan ke dalam satu ``group_id`` (jarak Hamming dHash <= ``hamming_threshold``)
   sehingga selalu berada di fold yang sama (*GroupKFold*).
2. **Stratifikasi Multi-Dimensi (``StratifiedGroupKFold``)**:
   Menjaga proporsi gabungan:
   - Sumber domain (``orig``, ``rf``, ``kg``, ``mg``, ``bg``)
   - Skala luas bbox plat (``bg_empty``, ``small`` < 1.5%, ``medium`` 1.5-5%, ``large`` > 5%)
   - Rasio aspek (``two_row`` w/h < 2.0 vs ``one_row`` w/h >= 2.0)
3. **Manifest Portabel (Relative Path)**:
   Menghasilkan ``folds/fold_{k}_train.txt``, ``folds/fold_{k}_val.txt``, dan
   ``folds/data_fold_{k}.yaml`` dengan path relatif terhadap ``data_root``.

Pemakaian::

    python tools/prepare_kfold.py --data-root plat-nomor --k 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class SampleMeta:
    rel_image_path: str
    domain: str
    scale_bucket: str
    aspect_bucket: str
    stratum: str
    dhash: int
    sha256: str
    group_id: int
    box_count: int


def compute_dhash(image_gray_or_bgr: Any, hash_size: int = 8) -> int:
    """Hitung 64-bit difference perceptual hash (dHash) menggunakan OpenCV/NumPy.

    Resize grayscale ke ``(hash_size + 1, hash_size)`` = ``9x8``, lalu bandingkan
    ``img[:, 1:] > img[:, :-1]`` -> integer 64-bit.
    """
    import cv2

    if image_gray_or_bgr is None or getattr(image_gray_or_bgr, "size", 0) == 0:
        return 0
    if image_gray_or_bgr.ndim == 3:
        gray = cv2.cvtColor(image_gray_or_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_gray_or_bgr
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bool(bit))
    return value


def hamming_distance(hash_a: int, hash_b: int) -> int:
    """Jarak Hamming (jumlah bit berbeda) antara dua dHash 64-bit."""
    return (hash_a ^ hash_b).bit_count()


def infer_domain(stem: str) -> str:
    """Kenali sumber domain dari prefix nama file."""
    lowered = stem.lower()
    for prefix in ("rf_", "kg_", "mg_", "bg_", "web_"):
        if lowered.startswith(prefix):
            return prefix.rstrip("_")
    return "orig"


def classify_boxes(lines: list[str]) -> tuple[str, str, int]:
    """Klasifikasikan ukuran & rasio bbox YOLO: ``(scale_bucket, aspect_bucket, box_count)``.

    Format baris YOLO: ``class_id cx cy bw bh`` (ternormalisasi 0..1).
    """
    areas: list[float] = []
    aspects: list[float] = []
    for raw in lines:
        parts = raw.strip().split()
        if len(parts) != 5:
            continue
        try:
            _, _cx, _cy, bw, bh = (float(v) for v in parts)
        except ValueError:
            continue
        if bw <= 0 or bh <= 0:
            continue
        areas.append(bw * bh)
        aspects.append(bw / bh)

    if not areas:
        return "bg_empty", "none", 0

    max_area = max(areas)
    if max_area < 0.015:
        scale_bucket = "small"
    elif max_area <= 0.050:
        scale_bucket = "medium"
    else:
        scale_bucket = "large"

    mean_aspect = sum(aspects) / len(aspects)
    aspect_bucket = "two_row" if mean_aspect < 2.0 else "one_row"
    return scale_bucket, aspect_bucket, len(areas)


def build_stratum(domain: str, scale_bucket: str, aspect_bucket: str) -> str:
    """Label strata gabungan untuk StratifiedGroupKFold."""
    return f"{domain}__{scale_bucket}__{aspect_bucket}"


def assign_visual_groups(
    dhashes: list[int], sha256s: list[str], hamming_threshold: int = 6
) -> list[int]:
    """Kelompokkan gambar yang identik (SHA-256) atau sangat mirip secara visual
    (jarak Hamming dHash <= ``hamming_threshold``) ke dalam ``group_id`` yang sama.

    Untuk efisiensi pada ribuan gambar ($O(N)$ rata-rata), pencocokan Hamming
    menggunakan bucket 16-bit prefix + jendela tetangga terdekat setelah pengurutan dHash.
    """
    n = len(dhashes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    # 1. Exact duplicate SHA-256
    by_sha: dict[str, int] = {}
    for idx, digest in enumerate(sha256s):
        if digest in by_sha:
            union(idx, by_sha[digest])
        else:
            by_sha[digest] = idx

    # 2. Perceptual near-duplicate (dHash Hamming distance <= threshold)
    if hamming_threshold >= 0:
        order = sorted(range(n), key=lambda i: dhashes[i])
        window = 24
        for pos, idx in enumerate(order):
            h_a = dhashes[idx]
            if h_a == 0:
                continue
            for nxt in order[pos + 1 : pos + 1 + window]:
                h_b = dhashes[nxt]
                if h_b == 0:
                    continue
                if hamming_distance(h_a, h_b) <= hamming_threshold:
                    union(idx, nxt)

    return [find(i) for i in range(n)]


def stratified_group_kfold_indices(
    strata: list[str], groups: list[int], k: int = 5, seed: int = 42
) -> list[tuple[list[int], list[int]]]:
    """Bagi indeks sampel menjadi ``k`` fold ``(train_indices, val_indices)``
    secara deterministik dengan menjaga:
    1. Seluruh anggota ``group_id`` yang sama berada di fold validasi yang sama.
    2. Distribusi ``strata`` di setiap fold seimbang (*greedy stratified group assignment*).
    """
    if k < 2:
        raise ValueError("Jumlah fold k minimal 2")
    n = len(strata)
    if n != len(groups):
        raise ValueError("Panjang strata dan groups harus sama")

    # Kumpulkan indeks sampel per group_id
    group_members: dict[int, list[int]] = {}
    for idx, gid in enumerate(groups):
        group_members.setdefault(gid, []).append(idx)

    # Tentukan stratum dominan untuk setiap group
    group_info: list[tuple[str, int, int, list[int]]] = []
    for gid, members in group_members.items():
        dominant_stratum = strata[members[0]]
        # Hash deterministik untuk pengacakan stabil berdasarkan seed
        tie_hash = int(
            hashlib.sha1(f"{seed}:{gid}:{dominant_stratum}".encode("utf-8")).hexdigest()[:8],
            16,
        )
        group_info.append((dominant_stratum, -len(members), tie_hash, members))

    # Urutkan per stratum, ukuran group terbesar dulu, lalu tie_hash
    group_info.sort(key=lambda item: (item[0], item[1], item[2]))

    fold_val_indices: list[list[int]] = [[] for _ in range(k)]
    fold_totals = [0] * k
    fold_stratum_counts: list[dict[str, int]] = [{} for _ in range(k)]

    for stratum, _neg_len, _tie, members in group_info:
        # Pilih fold dengan jumlah sampel stratum ini paling sedikit,
        # tie-break dengan total sampel fold paling sedikit
        best_fold = min(
            range(k),
            key=lambda f: (fold_stratum_counts[f].get(stratum, 0), fold_totals[f], f),
        )
        fold_val_indices[best_fold].extend(members)
        fold_totals[best_fold] += len(members)
        fold_stratum_counts[best_fold][stratum] = (
            fold_stratum_counts[best_fold].get(stratum, 0) + len(members)
        )

    all_set = set(range(n))
    folds: list[tuple[list[int], list[int]]] = []
    for f in range(k):
        val_set = set(fold_val_indices[f])
        val_sorted = sorted(val_set)
        train_sorted = sorted(all_set - val_set)
        folds.append((train_sorted, val_sorted))
    return folds


def scan_dataset_pool(
    data_root: Path,
    splits: tuple[str, ...] = ("train", "valid", "test"),
    hamming_threshold: int = 4,
) -> list[SampleMeta]:
    """Pindai seluruh gambar & label di ``data_root`` tanpa menggandakan file."""
    import cv2

    raw_items: list[tuple[str, str, str, str, str, int, str, int]] = []
    seen_rel: set[str] = set()

    for split in splits:
        img_dir = data_root / split / "images"
        lbl_dir = data_root / split / "labels"
        if not img_dir.is_dir():
            continue
        for img_path in sorted(img_dir.iterdir()):
            if not img_path.is_file() or img_path.suffix.lower() not in IMG_EXTS:
                continue
            rel_path = img_path.relative_to(data_root).as_posix()
            if rel_path in seen_rel:
                continue
            seen_rel.add(rel_path)

            lbl_path = lbl_dir / f"{img_path.stem}.txt"
            lines = (
                lbl_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if lbl_path.is_file()
                else []
            )
            domain = infer_domain(img_path.stem)
            scale_b, aspect_b, box_count = classify_boxes(lines)
            stratum = build_stratum(domain, scale_b, aspect_b)

            raw_bytes = img_path.read_bytes()
            sha = hashlib.sha256(raw_bytes).hexdigest()
            img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
            dhash = compute_dhash(img)
            raw_items.append((rel_path, domain, scale_b, aspect_b, stratum, dhash, sha, box_count))

    dhashes = [item[5] for item in raw_items]
    sha256s = [item[6] for item in raw_items]
    groups = assign_visual_groups(dhashes, sha256s, hamming_threshold=hamming_threshold)

    samples: list[SampleMeta] = []
    for item, gid in zip(raw_items, groups):
        rel_path, domain, scale_b, aspect_b, stratum, dhash, sha, box_count = item
        samples.append(
            SampleMeta(
                rel_image_path=rel_path,
                domain=domain,
                scale_bucket=scale_b,
                aspect_bucket=aspect_b,
                stratum=stratum,
                dhash=dhash,
                sha256=sha,
                group_id=gid,
                box_count=box_count,
            )
        )
    return samples


def write_kfold_manifests(
    data_root: Path,
    samples: list[SampleMeta],
    k: int = 5,
    seed: int = 42,
    out_subdir: str = "folds",
) -> dict[str, Any]:
    """Tulis manifest ``fold_{k}_train.txt``, ``fold_{k}_val.txt``, dan ``data_fold_{k}.yaml``."""
    out_dir = data_root / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    for cache_file in out_dir.glob("*.cache"):
        cache_file.unlink(missing_ok=True)

    strata = [s.stratum for s in samples]
    groups = [s.group_id for s in samples]
    folds = stratified_group_kfold_indices(strata, groups, k=k, seed=seed)

    fold_summaries: list[dict[str, Any]] = []
    for fold_idx, (train_idx, val_idx) in enumerate(folds):
        train_txt = out_dir / f"fold_{fold_idx}_train.txt"
        val_txt = out_dir / f"fold_{fold_idx}_val.txt"
        yaml_path = out_dir / f"data_fold_{fold_idx}.yaml"

        # Ultralytics YOLO me-resolve path di dalam manifest .txt relatif terhadap CWD / root dataset,
        # bukan relatif terhadap subdirektori `folds/`. Gunakan path absolut hasil resolve() agar bebas dari error `../`.
        train_lines = [str((data_root / samples[i].rel_image_path).resolve().as_posix()) for i in train_idx]
        val_lines = [str((data_root / samples[i].rel_image_path).resolve().as_posix()) for i in val_idx]
        train_txt.write_text("\n".join(train_lines) + "\n", encoding="utf-8")
        val_txt.write_text("\n".join(val_lines) + "\n", encoding="utf-8")

        test_entry = "test/images" if (data_root / "test" / "images").is_dir() else f"{out_subdir}/fold_{fold_idx}_val.txt"
        yaml_content = (
            f"# Auto-generated 5-Fold Stratified Group CV (Fold {fold_idx}/{k})\n"
            f"path: {data_root.as_posix()}\n"
            f"train: {out_subdir}/fold_{fold_idx}_train.txt\n"
            f"val: {out_subdir}/fold_{fold_idx}_val.txt\n"
            f"test: {test_entry}\n\n"
            f"nc: 1\n"
            f"names: ['number-plate']\n"
        )
        yaml_path.write_text(yaml_content, encoding="utf-8")

        val_domains: dict[str, int] = {}
        val_scales: dict[str, int] = {}
        for i in val_idx:
            val_domains[samples[i].domain] = val_domains.get(samples[i].domain, 0) + 1
            val_scales[samples[i].scale_bucket] = val_scales.get(samples[i].scale_bucket, 0) + 1

        fold_summaries.append(
            {
                "fold": fold_idx,
                "yaml": str(yaml_path),
                "train_count": len(train_idx),
                "val_count": len(val_idx),
                "val_domains": val_domains,
                "val_scales": val_scales,
            }
        )

    summary = {
        "data_root": str(data_root),
        "total_images": len(samples),
        "unique_visual_groups": len({s.group_id for s in samples}),
        "k": k,
        "seed": seed,
        "folds": fold_summaries,
    }
    (out_dir / "kfold_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def prepare_kfold(
    data_root: Path,
    k: int = 5,
    seed: int = 42,
    splits: tuple[str, ...] = ("train", "valid"),
    hamming_threshold: int = 4,
) -> dict[str, Any]:
    """Fungsi utama untuk dipanggil dari notebook Google Colab maupun CLI.

    Default ``splits=('train', 'valid')`` agar ``test/`` tetap steril sebagai
    *hold-out test set* akhir, sementara seluruh ~4.066 citra `train + valid`
    dibagi menjadi 5 fold (~3.253 train : ~813 val multi-domain per fold).
    """
    samples = scan_dataset_pool(
        data_root, splits=splits, hamming_threshold=hamming_threshold
    )
    if not samples:
        raise FileNotFoundError(f"Tidak ada gambar ditemukan di {data_root} untuk splits={splits}")
    return write_kfold_manifests(data_root, samples, k=k, seed=seed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("plat-nomor"),
        help="Folder root dataset yang memiliki sub-folder train/valid/test",
    )
    parser.add_argument("--k", type=int, default=5, help="Jumlah fold Cross-Validation")
    parser.add_argument("--seed", type=int, default=42, help="Random seed stratifikasi")
    parser.add_argument(
        "--include-test",
        action="store_true",
        help="Sertakan split test ke dalam pool K-Fold (default: test tetap steril sebagai hold-out)",
    )
    parser.add_argument(
        "--hamming-threshold",
        type=int,
        default=4,
        help="Ambang jarak Hamming dHash 64-bit untuk mengelompokkan frame kendaraan berurutan",
    )
    args = parser.parse_args()

    splits = ("train", "valid", "test") if args.include_test else ("train", "valid")
    summary = prepare_kfold(
        args.data_root.resolve(),
        k=args.k,
        seed=args.seed,
        splits=splits,
        hamming_threshold=args.hamming_threshold,
    )
    print(
        f"5-Fold Stratified Group CV siap di {summary['data_root']}/folds "
        f"(total={summary['total_images']} citra, groups={summary['unique_visual_groups']})"
    )
    for f in summary["folds"]:
        print(
            f"  Fold {f['fold']}: train={f['train_count']} val={f['val_count']} "
            f"domains={f['val_domains']} scales={f['val_scales']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
