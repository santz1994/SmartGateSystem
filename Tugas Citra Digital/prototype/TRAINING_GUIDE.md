# Panduan Training YOLOv8 untuk Deteksi Plat Nomor Indonesia

## Dataset yang Tersedia

Proyek ini memiliki 2 dataset utama di folder `prototype/`:

### 1. `plat-nomor/` (Roboflow Universe - **RECOMMENDED untuk training YOLO**)
- Format: YOLO (images + labels .txt)
- Split: train (393), valid (84), test (84)
- Kelas: `number-plate` (1 kelas)
- Sumber: Roboflow Universe `saya-tidak-suka-comvis/plat-nomor-bpqge`
- File config: `plat-nomor/data.yaml`

### 2. `datasets/detection/` (COCO format)
- Format: COCO JSON (`annotations/annotations.json`)
- 1377 gambar, 2128 anotasi
- Kelas: `plate_number`
- Cocok untuk evaluasi deteksi (mAP)

### 3. `datasets/text/` (OCR dataset)
- 1863 crop plat + `label.csv` (ground truth teks)
- Format plat: `H2512AOC`, `BH2618MA`, dll (tanpa kode wilayah)
- Cocok untuk training/evaluasi OCR

---

## Cara Training YOLOv8

### Opsi A: Google Colab (Gratis, GPU T4) — **RECOMMENDED**

1. Buka [Google Colab](https://colab.research.google.com/)
2. Runtime → Change runtime type → GPU T4
3. Upload folder `plat-nomor/` ke Colab (atau clone dari Roboflow)
4. Jalankan notebook berikut:

```python
# Install dependencies
!pip install ultralytics -q

# Training
from ultralytics import YOLO

model = YOLO('yolov8n.pt')  # nano: cepat, ringan. Ganti 'yolov8s.pt' untuk akurasi lebih baik

results = model.train(
    data='/content/plat-nomor/data.yaml',  # sesuaikan path
    epochs=50,
    imgsz=640,
    batch=16,
    device=0,          # GPU
    project='runs/detect',
    name='train',
    patience=20,
    save=True,
    plots=True,
)

# Best weights akan di: /content/runs/detect/train/weights/best.pt
# Download file ini ke lokal
```

### Opsi B: Local GPU (Windows/Linux dengan CUDA)

```bash
# 1. Buat virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install ultralytics torch torchvision --index-url https://download.pytorch.org/whl/cu118

# 3. Training
python train_yolo.py --epochs 50 --imgsz 640 --batch 16 --device 0
```

### Opsi C: CPU Only (Lambat, untuk testing kecil)

```bash
python train_yolo.py --epochs 10 --imgsz 640 --batch 8 --device cpu
```

---

## Setelah Training: Pakai di Prototype

1. Copy file `best.pt` ke folder prototype (atau simpan di mana saja)
2. Set environment variable:

```powershell
# PowerShell
$env:SGS_YOLO_WEIGHTS = "D:\Project\Smart Gate System\Tugas Citra Digital\prototype\runs\detect\train\weights\best.pt"

# Atau permanent (User scope)
[Environment]::SetEnvironmentVariable("SGS_YOLO_WEIGHTS", "D:\...\best.pt", "User")
```

3. Restart Flask app:
```bash
python run.py
```

4. Cek status di `/api/health` atau dashboard — harus muncul `"backend": "yolo"`

---

## Evaluasi Model

### Evaluasi Deteksi (mAP) pada `datasets/detection/`

```bash
# Convert COCO ke YOLO format dulu (script terpisah), lalu:
yolo val model=runs/detect/train/weights/best.pt data=datasets/detection/data.yaml
```

### Evaluasi OCR (End-to-End)

```bash
# Gunakan script eval_real.py yang sudah ada
python tools/eval_real.py --part both --limit 200
```

---

## Tips Training

| Parameter | Rekomendasi | Catatan |
|-----------|-------------|---------|
| Model base | `yolov8n.pt` (nano) | Cepat, cukup untuk plat. Naik ke `yolov8s.pt` kalau butuh akurasi lebih |
| Epochs | 50-100 | Early stopping `patience=20` akan berhenti otomatis |
| Image size | 640 | Standar YOLO. Naik ke 1280 kalau plat sangat kecil |
| Batch | 16 (GPU 8GB) | Turunkan kalau OOM |
| Augmentasi | Default YOLO sudah cukup | Mosaic, mixup, HSV, flip, dll otomatis aktif |

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `Access denied` install pip | Pakai `python -m pip install --user` atau buat venv |
| CUDA out of memory | Turunkan `batch` ke 8 atau 4 |
| mAP rendah | Naikkan `epochs`, pakai model `yolov8s.pt`/`yolov8m.pt`, perbanyak data |
| Plat tidak terdeteksi malam | Tambah augmentasi `hsv_h`, `hsv_s`, `hsv_v` di training |

---

## File Penting

- `train_yolo.py` — Script training CLI
- `plat-nomor/data.yaml` — Config dataset YOLO
- `app/detect_yolo.py` — Backend YOLO di prototype (auto-load via `SGS_YOLO_WEIGHTS`)
- `tools/eval_real.py` — Evaluasi end-to-end (deteksi + OCR)