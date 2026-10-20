#!/usr/bin/env python3
"""
Script training YOLOv8 untuk deteksi plat nomor Indonesia.

Dataset: plat-nomor/ (format YOLO dari Roboflow)
Struktur:
  plat-nomor/
  ├── data.yaml
  ├── train/images/  train/labels/
  ├── valid/images/  valid/labels/
  └── test/images/   test/labels/

Jalankan di environment yang punya GPU (Colab, local GPU, dll):
  python train_yolo.py --epochs 50 --imgsz 640 --batch 16

Hasil bobot (best.pt) disimpan di runs/detect/train/weights/best.pt
Lalu set env var untuk pakai di prototype:
  $env:SGS_YOLO_WEIGHTS = "runs/detect/train/weights/best.pt"
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 for Indonesian license plate detection")
    parser.add_argument("--data", default="plat-nomor/data.yaml", help="Path to data.yaml")
    parser.add_argument("--model", default="yolov8n.pt", help="Base model (n/s/m/l/x)")
    parser.add_argument("--epochs", type=int, default=50, help="Number of epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--device", default="0", help="Device (0 for GPU, cpu for CPU)")
    parser.add_argument("--project", default="runs/detect", help="Project directory")
    parser.add_argument("--name", default="train", help="Run name")
    parser.add_argument("--patience", type=int, default=20, help="Early stopping patience")
    parser.add_argument(
        "--target-map50", type=float, default=0.98,
        help="Stop training otomatis saat val mAP50 mencapai target (0 = nonaktif)",
    )
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: {data_path} not found")
        return 1

    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        return 1

    print(f"Loading base model: {args.model}")
    model = YOLO(args.model)

    # Early stop kustom: berhenti begitu target mAP50 tercapai, agar waktu
    # komputasi (GPU/Colab) tidak terbuang untuk epoch yang tidak perlu.
    if args.target_map50 > 0:
        def stop_at_target(trainer):
            map50 = (trainer.metrics or {}).get("metrics/mAP50(B)", 0.0)
            if map50 >= args.target_map50:
                trainer.stop = True
                print(f"\nTarget mAP50 {args.target_map50:.2f} tercapai ({map50:.4f}) — training dihentikan.")

        model.add_callback("on_fit_epoch_end", stop_at_target)

    print(f"Starting training...")
    print(f"  data: {args.data}")
    print(f"  epochs: {args.epochs}")
    print(f"  imgsz: {args.imgsz}")
    print(f"  batch: {args.batch}")
    print(f"  device: {args.device}")

    results = model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        patience=args.patience,
        save=True,
        plots=True,
        val=True,
    )

    best_pt = Path(args.project) / args.name / "weights" / "best.pt"
    last_pt = Path(args.project) / args.name / "weights" / "last.pt"

    print("\nTraining completed!")
    print(f"Best weights: {best_pt}")
    print(f"Last weights: {last_pt}")

    if best_pt.exists():
        print(f"\nTo use in prototype, set environment variable:")
        print(f"  $env:SGS_YOLO_WEIGHTS = \"{best_pt.absolute()}\"")
        print(f"Then restart the Flask app.")

    return 0


if __name__ == "__main__":
    exit(main())