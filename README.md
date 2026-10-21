# Smart Gate System

Sistem gerbang otomatis berbasis pengenalan plat nomor Indonesia: YOLOv8 untuk
deteksi plat + OCR (PaddleOCR/EasyOCR) dengan koreksi aturan NRKB, dan
keputusan fail-safe (tidak pernah `AUTO_OPEN` saat komponen kritis gagal). Hasil
OCR yang melanggar struktur NRKB ditolak keras (dianggap tidak terbaca), dan
distraktor layar/video (subtitle, blok warna) tidak mengambil slot pembacaan.
Stiker QR dan RFID adalah **rencana pengembangan mendatang / bahan skripsi** —
lihat [docs/PRESENTASI.md](docs/PRESENTASI.md) bagian Rencana Pengembangan.

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

## Model Detektor (3 varian, bisa dipilih saat runtime)

Run `smartgate-colab-v6-*` (dataset gabungan final 3.982 gambar, anti-leakage).
Ketiganya terpasang dan dapat ditukar langsung dari halaman **/training**
("Pilih Model Deteksi Aktif") untuk membandingkan kecepatan & ketepatan:

| Metrik | YOLOv8n | YOLOv8x | YOLOv11n |
| --- | ---: | ---: | ---: |
| Test mAP50 | 0,9564 | 0,9580 | **0,9683** |
| Valid format OCR | 72,03% | 67,52% | **75,00%** |
| Latency avg / P95 | 96 / 176 ms | 189 / 263 ms | 100 / 192 ms |
| Bobot best.pt | 6,5 MB | 136,7 MB | **5,5 MB** |

**YOLOv11n = rekomendasi** (deteksi & OCR terbaik, bobot terkecil). Bobot:
`runs/detect/smartgate-colab-v6-<varian>/weights/best.pt` (dipilih otomatis;
override via `SGS_YOLO_WEIGHTS` / `SGS_YOLO_VARIANT`). V4 parser menambah
koreksi blok prefix (`00/O0` → `DD`, kode wilayah valid di `VALID_PREFIXES`).

## Training

Notebook Colab: [`plat-nomor/a_YOLOv8n.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a_YOLOv8n.ipynb)
/ [`plat-nomor/a_YOLOv11n.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a_YOLOv11n.ipynb)
(train + evaluasi OCR + ekspor artefak; dataset gabungan dari
`tools/merge_datasets.py`). Panduan lengkap:
[`TRAINING_GUIDE.md`](Tugas%20Citra%20Digital/prototype/TRAINING_GUIDE.md).
Laporan tugas: [`TUGAS_PENGOLAHAN_CITRA_DIGITAL.md`](Tugas%20Citra%20Digital/TUGAS_PENGOLAHAN_CITRA_DIGITAL.md).

## Uji

```powershell
cd "Tugas Citra Digital/prototype"
python tests\test_pipeline.py
```

Suite assert tanpa framework (80+ pemeriksaan): aturan NRKB, fusi, voting,
moiré monitor, dan distraktor layar/video. `pytest` tidak diperlukan.
