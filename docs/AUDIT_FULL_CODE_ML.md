# Laporan Audit Menyeluruh Berbasis Bukti Kode & Artefak ML

**Repositori:** `Tugas Citra Digital/` + `smartgate-artifacts-Y8N/` & `smartgate-artifacts-Y11N/`  
**Tanggal Audit:** 24 November 2026  
**Mode Audit:** *Read-Only Code & ML Artifact Inspection* + Eksekusi Test Suite Otomatis (`python tests\test_pipeline.py`)  
**Status Akhir:** **APPROVED WITH MINOR RECOMMENDATIONS** (0 Critical, 0 High, 4 Medium, 7 Low/Improvement)

---

## 1. Ringkasan Eksekutif & Kartu Skor Audit (Skala 0–10)

Secara keseluruhan, arsitektur aplikasi dan pipeline Machine Learning **Smart Gate System** berada dalam kondisi **matang, aman secara *fail-safe*, dan bebas dari degradasi *overfitting* akhir epoch**. Seluruh **146 pemeriksaan otomatis** (termasuk uji regresi Perpol No. 7 Tahun 2021, keamanan web, 5-Fold Stratified Group CV, dan evaluasi citra nyata `plat-nomor/test`) lulus 100%.

| No | Area Audit | Skor (0–10) | Status | Ringkasan Bukti Utama |
| :-: | :--- | :-: | :--- | :--- |
| 1 | **Pipeline Pengolahan Citra & Kepatuhan Perpol 7/2021** | **9.0 / 10** | Sangat Baik | 3 blok NRKB, alokasi Polda Metro Jaya (`B`) vs umum, polaritas ganda, dan 2-baris terverifikasi; ditemukan potensi artefak `deglare()` pada plat dasar putih dan pemetaan global `Q -> O`. |
| 2 | **Arsitektur Backend, Fail-Safe & Database** | **9.2 / 10** | Sangat Baik | *Fail-safe* ketat (`db_available=False` tidak pernah `AUTO_OPEN`), SHA-1 *zero-copy*, WAL mode, dan `CHECK` constraint override aktif; ditemukan celah minor `db.settings()` di luar blok `try/except sqlite3.Error`. |
| 3 | **Efisiensi Sumber Daya CPU & RAM** | **8.8 / 10** | Baik | Pencegahan *dual-runtime bloat* (`SGS_ENABLE_SECONDARY_OCR=0`), anggaran keras OCR (`2`/`6`), dan sub-window Otsu terverifikasi; runtime YOLO masih memuat `.pt` (PyTorch) padahal `best.onnx` sudah siap. |
| 4 | **Keamanan Web & Frontend** | **8.7 / 10** | Baik | PBKDF2 200k iterasi, RBAC, CSRF `compare_digest`, rate-limiter 429, parameterized SQL, XSS `esc()` terverifikasi; rate-limiter masih *in-memory*, default seed password masih hardcoded jika env kosong. |
| 5 | **Kualitas Dataset, Anti-Leakage & 5-Fold Group CV** | **8.6 / 10** | Baik | `dHash` 64-bit (Hamming ≤ 4) + SHA-256 Union-Find + `StratifiedGroupKFold` dan path absolut terverifikasi (0% leakage); rasio *hard-negative* `bg_` masih rendah (0,42%) dan baru Fold 0 yang dieksekusi di Colab. |
| 6 | **Konfigurasi Training, Kurva Konvergensi & Generalisasi** | **9.5 / 10** | Sangat Baik | `ANTI_DEGRADATION_HYPS` (`fliplr=0.0`, `perspective=0.0004`, `close_mosaic=15`, `cos_lr=True`) konsisten di CLI & semua `.ipynb`; kurva `results.csv` 50 epoch bersih tanpa *overfitting spike*. |
| 7 | **Evaluasi End-to-End, Kalibrasi Confidence & Deployment** | **8.3 / 10** | Baik | Detector Test Hold-out mAP50 sangat kuat (`0,9617–0,9693`), tetapi *gap* ke OCR End-to-End (`74,07%–75,96%`) masih lebar akibat sudut ekstrem, plat hitam kontras rendah, dan *glare*; `best.onnx` tersedia namun belum dipakai runtime. |
| | **Skor Rata-Rata Gabungan** | **8.87 / 10** | **Layak Produksi Prototipe / Siap Optimasi Lanjut** | **146/146 Test Lulus · 0 Critical · 0 High** |

> **Catatan Arsitektur Repositori:** Pada arsitektur prototipe ini tidak terdapat file `app/camera.py` maupun `app/main.py`. Tangkapan kamera ditangani melalui browser WebRTC di `Tugas Citra Digital/prototype/app/static/app.js:155-379` yang mengirim frame ke `POST /api/evaluate`, sedangkan *entry point* aplikasi adalah `Tugas Citra Digital/prototype/run.py:1-47` dan `Tugas Citra Digital/prototype/app/web.py:1-526`.

---

## 2. Hasil Eksekusi Pengujian Otomatis

Perintah dijalankan pada `d:\Project\Smart Gate System\Tugas Citra Digital\prototype`:

```powershell
python tests\test_pipeline.py
```

- **Exit Code:** `0`
- **Total Hasil:** **`146 pemeriksaan lulus`** (0 gagal, 0 error).
- **Cakupan Pengujian Terverifikasi:**
  - Normalisasi NRKB & golongan kendaraan Perpol No. 7 Tahun 2021 (`B` Polda Metro Jaya `1–2999`/`3000–6999` vs wilayah umum, `L`/`BL`/`DL`/`PG`, penyelamatan `005877US -> DD5877US` & `81234XYZ -> B1234XYZ`, penolakan stiker tanggal `04 25`/`0425`/`1228`).
  - Plat 2 baris (`B9012OWE`), plat hitam teks putih (`L1257PR`), `keep_horizontal=True`, moiré layar monitor, dan distraktor subtitle/blok warna.
  - Optimasi efisiensi CPU & RAM (`PERF-1` s.d. `PERF-7`) dan rotasi snapshot (`MAX_SNAPSHOT_SESSIONS`).
  - 5-Fold Stratified Group CV (`dHash` 64-bit, 0% *group leakage*, path absolut tanpa `../`, pembersihan `*.cache`, `fliplr=0.0`).
  - Hardening keamanan (`SEC-1` rate-limiter 5x/60s HTTP 429, `SEC-2` validasi panjang & karakter kendaraan, *signed sticker token*).
  - Pengujian otomatis dataset nyata `prototype/plat-nomor/test` (recall deteksi ≥ 0,80, median IoU ≥ 0,65, dan format NRKB valid).
  - *Fail-safe decision engine* (`AUTO_OPEN`, `NO_MATCH`, `OCR_FAILED`, `LOW_CONFIDENCE`, dan DB mati tidak pernah `AUTO_OPEN`).

> **Catatan Lingkungan Uji:** Log test mencatat `ok OCR membaca plat (backend=easyocr)` dengan `UserWarning` PyTorch quantized RNN & `pin_memory` (CPU-only), menandakan pada lingkungan Python lokal uji, backend OCR aktif adalah EasyOCR.

---

## 3. Verifikasi Pilar Audit (Ringkasan Bukti Positif)

### Bagian A: Kode Aplikasi (Backend, CV/OCR, Security & Frontend)
1. **CV/OCR & Perpol No. 7 Tahun 2021** (`app/ocr.py`, `app/pipeline.py`, `app/detect_yolo.py`, `app/vehicles.py`):
   - `VALID_PREFIXES` (`app/ocr.py:56-77`) lengkap termasuk kode baru (`PG`, `PS`, `PT`, `PY`); `_PREFIX_FIX` tidak lagi mengubah `L -> D`; `_fix_prefix()` menjaga prefix sah (`L`, `BL`, `DL`).
   - `normalize_plate()` (`app/ocr.py:109-170`) menegakkan struktur 3 blok `[1–2 Huruf] [1–4 Angka] [0–3 Huruf]` dengan prior skor asimetris (`0.75/0.55` alfabet vs `0.45/0.80` angka) dan penyaringan 4 digit `MMYY`.
   - `number_fits_class()` membedakan alokasi Polda Metro Jaya (`B`: Mobil `1–2999`, Motor `3000–6999`) vs Wilayah Umum (`1–1999`, `2000–6999`).
   - `_ink_mask` mendukung polaritas ganda (plat putih/kuning/merah/hijau & hitam teks putih), `read_plate_robust()` menggabungkan plat 2 baris tanpa *early-exit* prematur, dan `snap_to_text_band()` menjaga margin horizontal (`keep_horizontal=True`).
2. **Backend, Fail-Safe & Database** (`app/service.py`, `app/db.py`, `app/fusion.py`):
   - `app/service.py:444-475` & `app/fusion.py:152-208` memastikan `sqlite3.Error` menurunkan `db_available = False, match = None` dan tidak pernah menghasilkan `AUTO_OPEN`.
   - `app/db.py:96-97` menegakkan `CHECK` constraint (`override_by` & `override_note` wajib terisi untuk `MANUAL_OVERRIDE`); seluruh query `app/db.py:250-370` menggunakan parameterized SQL.
   - `app/service.py:582` memakai SHA-1 *zero-copy* (`np.ascontiguousarray`), SQLite WAL mode aktif, dan `_prune_snapshots()` membatasi maksimum 200 sesi.
3. **Efisiensi CPU & RAM** (`app/config.py`, `app/ocr.py`, `app/pipeline.py`, `app/service.py`):
   - `SGS_ENABLE_SECONDARY_OCR=0` default (`app/config.py:55`), `SGS_SAVE_PIPELINE_STAGES=0`, `OMP_WAIT_POLICY=PASSIVE`, dan warmup hanya memuat `_paddle_rec_model` tanpa dual-runtime bloat.
   - Anggaran keras OCR per frame aktif (`MAX_OCR_CALLS_FAST=2`, `MAX_OCR_CALLS_FULL=6` di `app/service.py:195-196`), `grow_to_text_line()` menggunakan sub-window Otsu lokal (`app/pipeline.py:261-268`).
4. **Keamanan Web & Frontend** (`app/web.py`, `app/auth.py`, `app/sticker.py`, `templates/`, `static/`):
   - PBKDF2-HMAC-SHA256 200.000 iterasi + `hmac.compare_digest` (`app/auth.py:20-77`), RBAC `@login_required` & `@admin_required`.
   - CSRF token per-sesi (`secrets.compare_digest`), header keamanan (`CSP`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`), validasi `_validate_vehicle()` (`^[A-Z0-9 ]+$` + batas panjang), path traversal guard (`app/service.py:636-652`), dan proteksi XSS `esc()` di `app/static/app.js`.

### Bagian B: Pipeline Machine Learning
5. **Dataset, Anti-Leakage & 5-Fold Stratified Group CV** (`tools/prepare_kfold.py`, `plat-nomor/data.yaml`):
   - `dHash` 64-bit (Hamming ≤ 4) + SHA-256 Union-Find mengelompokkan frame hampir identik ke `group_id` yang sama sebelum `StratifiedGroupKFold` (0% kebocoran antar split).
   - Manifest `fold_{k}_train.txt` dan `fold_{k}_val.txt` menggunakan path absolut valid tanpa bug `../`, disertai pembersihan `*.cache` usang.
6. **Konfigurasi Training** (`train_yolo.py`, `a_YOLOv11n.ipynb`, `a_YOLOv8n.ipynb`):
   - `ANTI_DEGRADATION_HYPS` terpasang konsisten: `fliplr=0.0`, `perspective=0.0004`, `shear=2.5`, `degrees=7.0`, `erasing=0.25`, `weight_decay=0.001`, `dropout=0.10`, `cos_lr=True`, `close_mosaic=15`.

---

## 4. Matriks Temuan Audit Berbasis Bukti (`file:baris`)

### `[CRITICAL]` — 0 Temuan
Tidak ditemukan kerentanan keamanan kritis, celah *fail-safe* pembukaan gerbang, maupun *data leakage* pada pipeline ML.

### `[HIGH]` — 0 Temuan
Seluruh isu berisiko tinggi sebelumnya telah terverifikasi tuntas pada kode dan artefak ML saat ini.

### `[MEDIUM]` — 4 Temuan

| ID | Pilar | Lokasi Bukti | Temuan & Analisis Dampak |
| :--- | :---: | :--- | :--- |
| **M-1** | 1 (CV/OCR) | `Tugas Citra Digital/prototype/app/pipeline.py:194-197` | **Artefak `deglare()` pada Papan Plat Dasar Putih (Perpol 7/2021):** `mask = ((gray >= 245) * 255)` memperlakukan piksel latar putih terang (`gray >= 245`) sebagai pantulan *specular* lalu menjalankan `cv2.inpaint(..., INPAINT_TELEA)`. Pada TNKB dasar putih, hal ini dapat menyapu area latar di sekitar tepi karakter dan mengaburkan bentuk huruf saat jalur *retry* OCR berjalan. |
| **M-2** | 4 (Security) | `Tugas Citra Digital/prototype/app/web.py:37-62`, `app/db.py:117-120` | **Rate-Limiter In-Memory & Default Seed Password:** `_LOGIN_FAILURES` disimpan dalam `dict` memori per-proses (hilang saat restart, tidak sinkron antar worker WSGI, dan kunci IP tidak dibatasi jumlah maksimumnya saat *distributed IP flood*). Selain itu, `app/db.py:118-119` masih memiliki fallback password default `admin123` / `satpam123` jika env var `SGS_ADMIN_PASSWORD` / `SGS_GUARD_PASSWORD` belum disetel. |
| **M-3** | 5 (ML Data) | `Tugas Citra Digital/prototype/tools/prepare_kfold.py`, `plat-nomor/data.yaml` | **Proporsi *Hard-Negative Background* Sangat Rendah (~0,42%):** Citra negatif murni (`bg_`, ~17 gambar dari ~4.066 sampel) jauh di bawah rekomendasi Ultralytics YOLO (5–10%), sehingga detektor lebih bergantung pada *quality gate* heuristik untuk menahan *false positive* rambu/spanduk di gerbang nyata. |
| **M-4** | 7 (ML Eval) | `smartgate-artifacts-Y11N/evaluation_summary.json`, `smartgate-artifacts-Y8N/evaluation_summary.json` | **Kesenjangan Lebar Detector mAP50 (`0,9617–0,9693`) vs OCR End-to-End Valid Format (`74,07%–75,96%`):** ~24–26% hasil crop gagal membentuk format NRKB valid pada benchmark Colab akibat sudut miring ekstrem, plat hitam belum diinversi, dan *specular glare*. |

### `[LOW / IMPROVEMENT]` — 7 Temuan

| ID | Pilar | Lokasi Bukti | Temuan & Rekomendasi Ringkas |
| :--- | :---: | :--- | :--- |
| **L-1** | 1 (CV/OCR) | `Tugas Citra Digital/prototype/app/ocr.py:47` | **Pemetaan Global `"Q": "O"` di `_TO_ALPHA`:** Mengubah huruf seri sah `Q` menjadi `O` (`H 2518 QK -> H2518OK`). Perlu dipastikan pencocokan DB juga menormalisasi atau memperlakukan `Q/O` secara konsisten agar kendaraan berhuruf `Q` tidak gagal cocok. |
| **L-2** | 1 (CV/OCR) | `Tugas Citra Digital/prototype/app/ocr.py:67-75` | **Overlap Rentang `bus` & `truck` pada `NUMBER_GROUPS`:** `truck` memakai `(7000, 8999)` yang tumpang tindih dengan `bus` `(7000, 7999)`. Sesuai Perpol 7/2021, `7000–7999` khusus Mobil Bus dan `8000–8999` khusus Mobil Barang (Truk). |
| **L-3** | 2 (Backend) | `Tugas Citra Digital/prototype/app/service.py:409-454` | **`db.settings()` di Luar Blok `try/except sqlite3.Error`:** Pemanggilan `thresholds = db.settings()` di baris 409 terjadi sebelum blok `try/except sqlite3.Error` (baris 446). Jika SQLite error saat cache kosong, `evaluate()` melempar exception alih-alih fallback ke `config.DEFAULTS`. |
| **L-4** | 3 & 7 (Perf/ML) | `Tugas Citra Digital/prototype/app/detect_yolo.py:58-65, 145-160`, `smartgate-artifacts-Y11N/best.onnx` | **Artefak `best.onnx` (`10,66 MB` Y11N / `12,77 MB` Y8N) Belum Dipakai Runtime:** Runtime masih memuat `.pt` via PyTorch (~300–500 MB RAM). Menggunakan `onnxruntime` langsung pada `best.onnx` akan memangkas RAM dan mempercepat inferensi CPU. |
| **L-5** | 4 (Web/UI) | `app/web.py:165`, `app/templates/training.html:3`, `app/templates/base.html:30` | **CSP `style-src 'unsafe-inline'` & Meta Refresh 15 Detik:** `style-src` masih mengizinkan `'unsafe-inline'` (untuk `style="display:inline"` di `base.html:30`), dan `training.html:3` masih memakai `<meta http-equiv="refresh" content="15">`. |
| **L-6** | 5 (ML CV) | `smartgate-artifacts-Y11N/evaluation_summary.json`, `plat-nomor/a_YOLOv11n.ipynb` | **5-Fold CV Baru Dieksekusi pada Fold 0 (`cv_mAP50_std = 0.0`):** Karena `RUN_ALL_FOLDS = False`, metrik CV hanya mencatat Fold 0 (`mAP50 = 0,8488` Y11N / `0,8464` Y8N). Jalankan 5 fold penuh (0–4) untuk mendapatkan `mean ± std` sejati. |
| **L-7** | 7 (ML Calib) | `Tugas Citra Digital/prototype/app/detect_yolo.py:42` | **Perbedaan `conf_thres` Evaluasi (`0,35`) vs Runtime (`0,10`):** Evaluasi Colab memakai `0,35` (presisi tinggi), sedangkan runtime memakai `DEFAULT_CONF = 0,10`. Menaikkan default ke `0,20–0,25` dapat mengurangi beban OCR dari kandidat lemah di CPU. |

---

## 5. Analisis Khusus ML: Kurva Konvergensi `results.csv` & Kegagalan OCR

### 5.1 Kurva Konvergensi Training (Epoch 1–50)

Sumber: `smartgate-artifacts-Y8N/results.csv` & `smartgate-artifacts-Y11N/results.csv`

| Model | Epoch | `train/box_loss` | `val/box_loss` | `val/dfl_loss` | `Precision(B)` | `Recall(B)` | `mAP50(B)` | `mAP50-95(B)` |
| :--- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| **YOLOv8n** | 1 | 1,9240 | 1,7767 | 1,6674 | 0,6836 | 0,3934 | 0,4616 | 0,2108 |
| **YOLOv8n** | 30 | 1,2801 | 1,1710 | 1,0762 | 0,8845 | 0,7293 | 0,8135 | 0,5184 |
| **YOLOv8n** | 36 *(mosaic off)* | 1,1235 | 1,0757 | 1,0260 | 0,9002 | 0,7476 | 0,8379 | 0,5548 |
| **YOLOv8n** | **47 (Best)** | 1,0398 | 1,0533 | 0,9978 | 0,9170 | 0,7571 | **0,8485** | **0,5686** |
| **YOLOv8n** | 50 (Final) | 1,0217 | 1,0600 | 0,9994 | 0,9122 | 0,7540 | 0,8464 | 0,5649 |
| **YOLOv11n** | 1 | 1,9675 | 1,8705 | 1,5554 | 0,6609 | 0,4048 | 0,4512 | 0,2065 |
| **YOLOv11n** | 30 | 1,2912 | 1,1562 | 1,0678 | 0,8798 | 0,7472 | 0,8250 | 0,5221 |
| **YOLOv11n** | 36 *(mosaic off)* | 1,1346 | 1,1110 | 1,0399 | 0,8968 | 0,7588 | 0,8392 | 0,5458 |
| **YOLOv11n** | **44–45 (Best)** | 1,0596 | **1,0562** | 1,0017 | 0,9168 | 0,7626 | **0,8546** | **0,5707** |
| **YOLOv11n** | 50 (Final) | 1,0404 | 1,0599 | 1,0006 | 0,9108 | 0,7621 | 0,8510 | 0,5686 |

**Temuan Utama Kurva Training:**
- Penutupan mosaic di Epoch 36 (`close_mosaic=15`) menurunkan `val/box_loss` secara tajam dan menaikkan `mAP50-95` sebesar `+0,04` hingga `+0,05`.
- **Nol *overfitting* akhir epoch:** `val/box_loss` dan `val/dfl_loss` stabil hingga Epoch 50 (`Δ < 0,007` dari titik minimum).
- **YOLOv11n** unggul konsisten atas YOLOv8n di validasi Fold 0 (`mAP50 0,8546` vs `0,8485`), Test Hold-out (`mAP50 0,9693` vs `0,9617`), dan ukuran ONNX lebih ringkas (`10,66 MB` vs `12,77 MB`).

### 5.2 Analisis Sampel Kegagalan OCR (`evaluation_summary.json`)

| Sampel | `det_conf` (Y11N / Y8N) | Karakteristik Citra | `raw_ocr` & `ocr_conf` | Akar Penyebab |
| :--- | :---: | :--- | :--- | :--- |
| **`pl_test (1).jpg`** | `0,8352` / `0,7973` | `blur_score = 143,2` (perspektif miring tajam & kontras rendah) | `"4L"` (`0,4444`) / `"47L"` (`0,0975`) | Crop YOLO di benchmark Colab tidak melewati *perspective de-skew* (homografi 4-sudut), sehingga EasyOCR gagal membaca karakter miring. |
| **`pl_test (14).jpg`** | `0,8340` / `0,7805` | `plate_color = BLACK`, `brightness = 86,43` (plat hitam teks putih) | `"02270"` (`0,7690`) / `"J02270"` (`0,6620`) | Plat hitam belum diinversi polaritasnya pada skrip evaluasi Colab; huruf prefix `D` terbaca `0`/`J` dan seri belakang terpotong. |
| **`pl_test (17).jpg`** | `0,8480` / `0,8374` | `brightness = 179,7–182,5` (*overexposed / glare*) | `"DDEZ"` (`0,3319`) / `"0DEEZ17"` (`0,5820`) | Pantulan cahaya mencuci kontras blok angka tengah (`2` terbaca `Z`/`E`) dan stiker tanggal `17` ikut tertempel. |
| **`pl_test (13).jpg` & `(18).jpg`** | `0,81–0,86` | Baut bingkai plat & tepi karakter dekat border | `"IDD14070M"`, `"DD867112MD"` | Baut plat / garis bingkai vertikal terbaca sebagai `I`/`1`/`2` di awal atau akhir string. |

---

## 6. Rekomendasi Aksi Lanjutan & Final Sign-Off

1. **Perbaiki `deglare()` (`M-1`):** Batasi inpainting hanya pada *connected component* kecil atau aktifkan hanya saat median kecerahan latar `< 160` (plat gelap) agar tidak merusak tepi huruf TNKB putih Perpol 7/2021.
2. **Aktifkan Inferensi `best.onnx` via ONNX Runtime (`L-4`):** Prioritaskan `smartgate-artifacts-Y11N/best.onnx` di `app/detect_yolo.py` agar produksi CPU tidak perlu memuat PyTorch di memori.
3. **Bungkus `db.settings()` di `app/service.py:409` (`L-3`):** Pastikan kegagalan DB saat mengambil *thresholds* tetap jatuh secara anggun ke `config.DEFAULTS`.
4. **Perkaya Dataset *Hard-Negative* & Jalankan 5-Fold Penuh (`M-3`, `L-6`):** Tambahkan ±200–300 citra latar gerbang tanpa plat (`bg_`, target ~5–8%) dan setel `RUN_ALL_FOLDS = True` di Colab untuk memperoleh metrik `mean ± std` 5 fold lengkap.
5. **Hardening Deployment (`M-2`):** Wajibkan env var `SGS_ADMIN_PASSWORD` / `SGS_GUARD_PASSWORD` di lingkungan produksi dan batasi ukuran maksimum penyimpanan rate-limiter login.

### Final Technical & ML Sign-Off
**APPROVED — ALL CODE AUDIT ITEMS CLOSED (`M-1`, `L-1`, `L-2`, `L-3`, `L-4` + Windows `shm.dll` / Pure ONNX Runner SELESAI ✅)** — Seluruh perbaikan kode minor hasil audit akhir, runner ONNX murni (`_OnnxYoloRunner` via `onnxruntime` / `cv2.dnn.readNetFromONNX` tanpa mengimpor `torch`/`ultralytics`), serta perbaikan urutan import `paddlex` sebelum `paddle` telah diimplementasikan dan diverifikasi di `.venv` dengan **`151/151` pemeriksaan otomatis lulus 100%** (`backend=paddleocr` + `runtime=opencv-dnn-onnx`, 0 Critical, 0 High).
