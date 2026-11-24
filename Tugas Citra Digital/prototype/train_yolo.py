#!/usr/bin/env python3
"""
Script training YOLOv8 / YOLOv11 untuk deteksi plat nomor Indonesia
dengan dukungan 5-Fold Stratified Group Cross-Validation & Generalisasi
Anti-Degradasi (TRAIN-1 s.d. TRAIN-4).

Catatan: Pelatihan penuh dan evaluasi 5-Fold dirancang untuk dijalankan di
Google Colab (GPU T4) melalui `plat-nomor/a_YOLOv11n.ipynb` atau `a_YOLOv8n.ipynb`.

Contoh pemakaian (di GPU / Colab):
  python tools/prepare_kfold.py --data-root plat-nomor --k 5
  python train_yolo.py --model yolo11n.pt --fold 0 --epochs 50 --imgsz 640 --batch 16
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

# Hiperparameter Generalisasi & Anti-Degradasi Spesifik Kamera Gate (TRAIN-2, TRAIN-4).
# Dipakai bersama oleh train_yolo.py dan notebook Google Colab.
ANTI_DEGRADATION_HYPS: dict[str, Any] = {
    "cos_lr": True,
    "lrf": 0.01,
    "warmup_epochs": 3.0,
    "weight_decay": 0.001,
    "dropout": 0.10,
    "box": 7.5,
    # Augmentasi geometrik realistis kamera gate (fliplr WAJIB 0.0 agar urutan huruf plat tidak terbalik!)
    "degrees": 7.0,
    "translate": 0.10,
    "scale": 0.45,
    "shear": 2.5,
    "perspective": 0.0004,
    "fliplr": 0.0,
    "flipud": 0.0,
    # Komposisi & ketahanan oklusi/silau
    "mosaic": 0.8,
    "mixup": 0.05,
    "copy_paste": 0.10,
    "erasing": 0.25,
    "close_mosaic": 15,
    # Fotometrik siang/malam/pantulan layar
    "hsv_h": 0.015,
    "hsv_s": 0.65,
    "hsv_v": 0.45,
}


def resolve_data_yaml(data_arg: str, fold: int | None) -> Path:
    """Pilih file YAML dataset (atau `folds/data_fold_{k}.yaml` bila `--fold` diisi)."""
    base_yaml = Path(data_arg)
    if fold is None:
        return base_yaml
    data_root = base_yaml.parent if base_yaml.suffix in {".yaml", ".yml"} else base_yaml
    fold_yaml = data_root / "folds" / f"data_fold_{fold}.yaml"
    if not fold_yaml.is_file():
        from tools.prepare_kfold import prepare_kfold

        prepare_kfold(data_root.resolve())
    return fold_yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Train YOLOv8/v11 for Indonesian license plate detection")
    parser.add_argument("--data", default="plat-nomor/data.yaml", help="Path to data.yaml")
    parser.add_argument("--fold", type=int, default=None, help="Indeks fold 5-Fold CV (0..4)")
    parser.add_argument("--model", default="yolo11n.pt", help="Base model (yolo11n.pt / yolov8n.pt)")
    parser.add_argument("--epochs", type=int, default=50, help="Number of epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--device", default="0", help="Device (0 for GPU, cpu for CPU)")
    parser.add_argument("--project", default="runs/detect", help="Project directory")
    parser.add_argument("--name", default="train", help="Run name")
    parser.add_argument("--patience", type=int, default=15, help="Early stopping patience")
    parser.add_argument(
        "--target-map50", type=float, default=0.98,
        help="Stop training otomatis saat val mAP50 mencapai target (0 = nonaktif)",
    )
    args = parser.parse_args()

    data_path = resolve_data_yaml(args.data, args.fold)
    if not data_path.exists():
        print(f"ERROR: {data_path} not found")
        return 1

    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install ultralytics")
        return 1

    run_name = f"{args.name}-fold{args.fold}" if args.fold is not None else args.name
    print(f"Loading base model: {args.model}")
    model = YOLO(args.model)

    if args.target_map50 > 0:
        def stop_at_target(trainer: Any) -> None:
            map50 = (trainer.metrics or {}).get("metrics/mAP50(B)", 0.0)
            if map50 >= args.target_map50:
                trainer.stop = True
                print(f"\nTarget mAP50 {args.target_map50:.2f} tercapai ({map50:.4f}) — training dihentikan.")

        model.add_callback("on_fit_epoch_end", stop_at_target)

    print("Starting training with anti-degradation generalization hyperparameters...")
    print(f"  data: {data_path}")
    print(f"  fold: {args.fold}")
    print(f"  epochs: {args.epochs}")
    print(f"  imgsz: {args.imgsz}")
    print(f"  batch: {args.batch}")
    print(f"  device: {args.device}")

    model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=run_name,
        patience=args.patience,
        save=True,
        plots=True,
        val=True,
        seed=42,
        **ANTI_DEGRADATION_HYPS,
    )

    best_pt = Path(args.project) / run_name / "weights" / "best.pt"
    last_pt = Path(args.project) / run_name / "weights" / "last.pt"

    print("\nTraining completed!")
    print(f"Best weights: {best_pt}")
    print(f"Last weights: {last_pt}")

    if best_pt.exists():
        print("\nTo use in prototype, set environment variable:")
        print(f"  $env:SGS_YOLO_WEIGHTS = \"{best_pt.absolute()}\"")
        print("Then restart the Flask app.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
