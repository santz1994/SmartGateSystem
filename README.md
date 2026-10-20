# Smart Gate System

Sistem gerbang otomatis berbasis pengenalan plat nomor Indonesia: YOLOv8 untuk
deteksi plat + OCR (PaddleOCR/EasyOCR) dengan koreksi aturan NRKB, difusi bukti
plat + stiker, dan keputusan fail-safe (tidak pernah `AUTO_OPEN` saat komponen
kritis gagal). Hasil OCR yang melanggar struktur NRKB ditolak keras
(dianggap tidak terbaca), dan distraktor layar/video (subtitle, blok warna)
tidak mengambil slot pembacaan.

## Struktur Repositori

| Folder | Isi |
| --- | --- |
| [`docs/`](docs/) | Spesifikasi produksi: [PRD](docs/PRD.md), [TECHNICAL](docs/TECHNICAL.md), [SYSTEM_FLOW](docs/SYSTEM_FLOW.md), [API](docs/API.md), [DATABASE](docs/DATABASE.md) · bahan presentasi: [PRESENTASI](docs/PRESENTASI.md) |
| [`Tugas Citra Digital/`](Tugas%20Citra%20Digital/) | Tugas mata kuliah pengolahan citra digital + laporan |
| [`Tugas Citra Digital/prototype/`](Tugas%20Citra%20Digital/prototype/) | Prototype Flask (aplikasi utama) |
| `smartgate-artifacts*/` | Artefak training hasil unduhan Colab (bobot + laporan eval) |

## Menjalankan Prototype

```powershell
cd "Tugas Citra Digital/prototype"
python run.py
```

Buka `http://localhost:5000` (dashboard, `/camera` webcam, `/training`
monitoring run, `/logs` audit). Backend OCR/ detektor dapat dikonfigurasi lewat
environment: `SGS_OCR_BACKEND`, `SGS_YOLO_WEIGHTS`, `SGS_DETECTION_ROI`,
`SGS_CLAHE_CLIP_LIMIT`. Kesehatan sistem: `GET /api/health`.

## Model Detektor Aktif (V5)

Run aktif `smartgate-colab-v5` (YOLOv8n, dataset gabungan Roboflow + Kaggle
COCO + background, anti-leakage):

| Metrik | Nilai |
| --- | ---: |
| Test mAP50 / mAP50-95 | 94,91% / 59,99% |
| Valid format rate OCR (V4 parser) | 73,95% |
| Latency rata-rata / P95 | 98,22 ms / 176,99 ms |

Bobot: `Tugas Citra Digital/prototype/runs/detect/smartgate-colab-v5/weights/best.pt`
(dipilih otomatis; override via `SGS_YOLO_WEIGHTS`). V4 parser menambah koreksi
blok prefix (`00/O0` → `DD`, kode wilayah valid di `VALID_PREFIXES`).

## Training

Notebook Colab: [`plat-nomor/a.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a.ipynb)
(merge dataset + train + evaluasi OCR + ekspor artefak). Panduan lengkap:
[`TRAINING_GUIDE.md`](Tugas%20Citra%20Digital/prototype/TRAINING_GUIDE.md).
Laporan tugas: [`TUGAS_PENGOLAHAN_CITRA_DIGITAL.md`](Tugas%20Citra%20Digital/TUGAS_PENGOLAHAN_CITRA_DIGITAL.md).

## Uji

```powershell
cd "Tugas Citra Digital/prototype"
python tests\test_pipeline.py
```

Suite assert tanpa framework (80+ pemeriksaan): aturan NRKB, fusi, voting,
moiré monitor, dan distraktor layar/video. `pytest` tidak diperlukan.
