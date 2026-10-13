#!/usr/bin/env python3
"""
Convert COCO annotations (datasets/detection/annotations/annotations.json)
to YOLO format for evaluation with trained YOLO model.

Output: datasets/detection/yolo_format/
  ├── images/ (symlinks or copies)
  └── labels/ (.txt files)
  └── data.yaml
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def main():
    coco_json = Path("datasets/detection/annotations/annotations.json")
    img_dir = Path("datasets/detection/images")
    out_dir = Path("datasets/detection/yolo_format")
    out_img = out_dir / "images"
    out_lbl = out_dir / "labels"

    if not coco_json.exists():
        print(f"ERROR: {coco_json} not found")
        return 1

    print("Loading COCO annotations...")
    with open(coco_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Map image_id -> (filename, width, height)
        images = {img["id"]: (img["file_name"], float(img["width"]), float(img["height"])) for img in data["images"]}

    # Category mapping (COCO category_id -> YOLO class index)
    # COCO has 1 category: plate_number (id=0) -> YOLO class 0
    cat_map = {cat["id"]: i for i, cat in enumerate(data["categories"])}
    print(f"Categories: {cat_map}")

    # Clean output
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_img.mkdir(parents=True)
    out_lbl.mkdir(parents=True)

    # Process annotations
    ann_by_img = {}
    for ann in data["annotations"]:
        img_id = ann["image_id"]
        if img_id not in images:
            continue
        ann_by_img.setdefault(img_id, []).append(ann)

    print(f"Converting {len(ann_by_img)} images...")
    for img_id, anns in ann_by_img.items():
        fname, w, h = images[img_id]
        src = img_dir / fname
        dst = out_img / fname

        # Copy or symlink image
        if src.exists():
            shutil.copy2(src, dst)
        else:
            print(f"WARNING: {src} not found, skipping")
            continue

        # Write YOLO label
        lbl_path = out_lbl / (Path(fname).stem + ".txt")
        with open(lbl_path, "w") as f:
            for ann in anns:
                cls = cat_map[ann["category_id"]]
                x, y, bw, bh = ann["bbox"]
                # COCO: [x_min, y_min, width, height] (absolute)
                # YOLO: [x_center, y_center, width, height] (normalized 0-1)
                xc = (x + bw / 2) / w
                yc = (y + bh / 2) / h
                nw = bw / w
                nh = bh / h
                f.write(f"{cls} {xc:.6f} {yc:.6f} {nw:.6f} {nh:.6f}\n")

    # Write data.yaml
    yaml_content = f"""path: {out_dir.absolute()}
train: images
val: images

nc: 1
names: ['plate_number']
"""
    (out_dir / "data.yaml").write_text(yaml_content)

    print(f"Done! Output: {out_dir}")
    print(f"  Images: {len(list(out_img.glob('*')))}")
    print(f"  Labels: {len(list(out_lbl.glob('*')))}")
    print(f"  data.yaml written")
    return 0


if __name__ == "__main__":
    exit(main())