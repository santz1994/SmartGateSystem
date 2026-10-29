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
pip install -r requirements.txt        # inti + backend OCR (PaddleOCR)
pip install -r requirements-yolo.txt   # opsional: deteksi YOLO
python tools\fetch_weights.py          # isi bobot ke runs/detect/ (bobot tidak berada di git)
python run.py
```

Buka `http://localhost:5000` — **login dulu**: semua halaman & `/api/*`
terproteksi. Akun seed: `admin`/`admin123` (role admin) dan `satpam1`/`satpam123`
(role satpam). **Ganti password sebelum dipakai di luar localhost** — set env
`SGS_ADMIN_PASSWORD` / `SGS_SATPAM_PASSWORD` lalu `python run.py --reset-db`.
Kunci sesi: env `SGS_SECRET_KEY` (disarankan); tanpa env, file `data/secret_key`
dibuat otomatis.

Environment lain: `SGS_OCR_BACKEND`, `SGS_YOLO_WEIGHTS`, `SGS_DETECTION_ROI`,
`SGS_CLAHE_CLIP_LIMIT`, `SGS_REQUIRE_SIGNED_STICKER` (default `1` = QR stiker
wajib bertanda tangan `SGS1.*`), `SGS_CPU_THREADS` (batas thread inferensi),
`SGS_MAX_CONCURRENT_INFER` (default `1` = tanpa scan paralel). Kesehatan
sistem: `GET /api/health` (butuh login). Deploy produksi: `python run.py --prod`
(waitress) di belakang reverse proxy. Catatan: backend OCR (`SGS_OCR_BACKEND`)
& varian YOLO dibaca saat aplikasi start — ganti env butuh restart.

Performa di laptop uji (Dell Inspiron 5570, i5-8250U, CPU saja): scan cepat
±1,4 detik, scan penuh 3 frame ±5 detik, CPU saat scan ±53% — detail di
[docs/LAPORAN_KP_TEMUAN.md](docs/LAPORAN_KP_TEMUAN.md). Halaman `/camera`
menyediakan pemilih perangkat kamera untuk presentasi 1 webcam.

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

Catatan ukuran repo (M7): bobot `*.pt`/`*.onnx` kini dilacak **Git LFS**
(`.gitattributes`). Bobot lama pada riwayat commit tetap blob biasa — migrasi
riwayat (`git lfs migrate`) bersifat opsional dan butuh koordinasi (force push).
Untuk ke depan: terbitkan bobot lewat **GitHub Releases**, lalu isi dengan
`python tools/fetch_weights.py`.

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

Suite assert tanpa framework (102 pemeriksaan): aturan NRKB, fusi, voting,
moiré monitor, distraktor layar/video, rantai kepercayaan QR, dan identitas
audit. `pytest` tidak diperlukan. Pemeriksaan bobot YOLO di-skip (bukan gagal)
bila `runs/detect/` belum diisi `tools/fetch_weights.py`.

---

## Referensi

- Harani, N. H., Prianto, C., dan Hasanah, M. (2019). *Deteksi Objek dan
  Pengenalan Karakter Plat Nomor Kendaraan Indonesia Menggunakan Metode
  Convolutional Neural Network (CNN) Berbasis Python*. Jurnal Teknik Informatika,
  Vol. 11, No. 3. [PDF](docs/artc/658-Article%20Text-963-1-10-20200213.pdf)
- Subekti, I., Hariyono, R. C. S., dan Sorikhi. (2025). *Pengenalan Plat Nomor
  Kendaraan Menggunakan Algoritma Convolutional Neural Network Berbasis
  Tensorflow*. Remik: Riset dan E-Jurnal Manajemen Informatika Komputer, Vol. 9,
  No. 3. DOI: [10.33395/remik.v9i3.15169](https://doi.org/10.33395/remik.v9i3.15169).
  [PDF](docs/artc/15169-Article%20Text-24310-1-10-20250811.pdf)
- Forum Komunitas Axelera AI, [*Home Assistant CCTV Object and Motion Detection
  Using Metis*](https://community.axelera.ai/the-axelera-forum-52/home-assistant-cctv-object-and-motion-detection-using-metis-1226) ·
  [`axelera-ai-hub/voyager-sdk`](https://github.com/axelera-ai-hub/voyager-sdk) ·
  [`graffitiwriter/Metis-for-Home-Assistant-Motion-Detection`](https://github.com/graffitiwriter/Metis-for-Home-Assistant-Motion-Detection)
  — referensi NPU (Axelera Metis), zona deteksi, dan cascaded pipeline LPR
  untuk pengembangan lanjutan.
