# SmartGateSystem — Full Audit Report (Re-Audit Menyeluruh)

- **Repository**: `https://github.com/santz1994/SmartGateSystem.git`
- **Scope**: `Tugas Citra Digital/prototype/` (Backend Flask, Pipeline Visi Komputer, OCR & Parser NRKB, Frontend Vanilla JS/CSS, Test Suite, Tooling, serta Struktur Repositori & Dokumentasi)
- **Audit Awal**: 2026-10-21 (21 temuan: 3 Critical, 5 High, 7 Medium, 6 Low)
- **Remediasi Tahap 1 (Keamanan & Runnability)**: 2026-10-29 (Seluruh C1–C3, H1–H5, M1–M7, L1–L6 ditangani; suite uji 102/102 lulus)
- **Tanggal Audit Menyeluruh & Remediasi Penuh Tahap 1–3 (ALPR Perpol 7/2021 + Optimasi CPU/RAM + 5-Fold Stratified Group CV)**: 2026-11-23 (Seluruh temuan `OCR-1`..`OCR-7`, `OCR-10`, `OCR-11`, `PERF-1`..`PERF-7`, dan `TRAIN-1`..`TRAIN-4` telah diimplementasikan di kode & notebook Google Colab; suite uji bertambah menjadi **133 pemeriksaan**)
- **Fokus Audit Terbaru**: Verifikasi status remediasi keamanan, **efisiensi penggunaan CPU & RAM**, **akurasi & ketahanan fungsi pengenalan plat, huruf, angka, dan aturan NRKB (Perpol No. 7 Tahun 2021)**, serta **implementasi Generalisasi & 5-Fold Stratified Group Cross-Validation di Google Colab untuk mencegah degradasi model**.

---

## 1. Executive Summary & Skor Terbaru

Aplikasi ini dirancang dengan rekayasa domain yang matang: aturan penomoran plat nomor Indonesia (**NRKB & TNKB sesuai Peraturan Kepolisian Nomor 7 Tahun 2021**) dikodekan secara struktural, rantai keputusan bersifat *fail-safe* (tidak pernah membuka gerbang otomatis saat ragu atau DB gagal), dan seluruh komponen keamanan dari audit pertama (autentikasi sesi PBKDF2-HMAC-SHA256, RBAC `admin`/`satpam`, CSRF per-sesi, identitas audit server-side, XSS escaping `esc()`, CSP headers, dan verifikasi HMAC QR token `SGS1.*`) **telah terimplementasi dan terverifikasi di kode**.

Pada audit mendalam tanggal **23 November 2026**, dilakukan pemeriksaan menyeluruh dan remediasi langsung terhadap seluruh tiga area kritis:
1. **Akurasi Pengenalan Plat, Huruf, Angka & Kepatuhan Perpol No. 7 Tahun 2021 (`OCR-1`..`OCR-11`)** — **SELESAI DIIMPLEMENTASIKAN ✅** (`OCR-1`..`OCR-7`, `OCR-10`, `OCR-11` diperbaiki di `app/ocr.py`, `app/pipeline.py`, `app/detect_yolo.py`).
2. **Efisiensi Penggunaan CPU & RAM (`PERF-1`..`PERF-7`)** — **SELESAI DIIMPLEMENTASIKAN ✅** (Mitigasi *Dual-Framework Memory Bloat*, anggaran panggilan OCR per frame, penghapusan zoom ganda & bilateralFilter frame penuh redundan, lokalisasi sub-window Otsu di `grow_to_text_line`, zero-copy SHA-1 hashing, dan optimasi loop klasik di `app/config.py`, `app/ocr.py`, `app/pipeline.py`, `app/service.py`).
3. **Mitigasi Degradasi Model Training via Generalization & 5-Fold Cross-Validation (`TRAIN-1`..`TRAIN-4`)** — **SELESAI DIIMPLEMENTASIKAN ✅** (Modul pembagi dataset `tools/prepare_kfold.py` dengan anti-leakage visual `dHash` 64-bit + `StratifiedGroupKFold(n_splits=5)`, sinkronisasi hiperparameter anti-degradasi di `train_yolo.py`, serta pembaruan sel training & evaluasi 5-Fold CV di notebook Google Colab `plat-nomor/a_YOLOv11n.ipynb` dan `plat-nomor/a_YOLOv8n.ipynb`).

### Perbandingan Skor Audit

| Aspek | Audit Awal (21 Okt 2026) | Audit 23 Nov 2026 (Sebelum Fix) | Status Kini (23 Nov 2026 — Pasca Fix Tahap 1, 2 & 3) | Catatan Perubahan |
| :--- | :---: | :---: | :---: | :--- |
| **Code Quality & Architecture** | 7.5 / 10 | 8.2 / 10 | **9.1 / 10** | Modular, *pure functions* mudah diuji, aturan Perpol 7/2021, anggaran sumber daya, & pembagi K-Fold terenkapsulasi rapi. |
| **Security & Access Control** | 3.0 / 10 | 8.5 / 10 | **8.5 / 10** | Login sesi, PBKDF2, RBAC, CSRF, CSP, XSS escaping, dan signed QR token aktif. |
| **CPU & RAM Efficiency** | *(belum diukur)* | 6.0 / 10 | **9.0 / 10** | ✅ **`PERF-1`..`PERF-7` selesai diperbaiki**: bebas *Dual-Runtime Memory Bloat*, anggaran OCR per frame (2/6), sub-window Otsu lokal, tanpa `bilateralFilter` frame penuh, & zero-copy SHA-1. |
| **Plate, Letter & Digit Recognition (ALPR)** | *(belum diukur)* | 6.8 / 10 | **9.0 / 10** | ✅ **`OCR-1`..`OCR-7`, `OCR-10`, `OCR-11` selesai diperbaiki**: patuh Perpol 7/2021, bebas bias `L->D`, dukung plat 2 baris & plat hitam, saring `MMYY` 4 digit, dan jaga tepi bbox YOLO. |
| **Model Training & Generalization** | *(belum diukur)* | 6.2 / 10 | **9.0 / 10** | ✅ **`TRAIN-1`..`TRAIN-4` selesai diperbaiki**: `tools/prepare_kfold.py` (dHash 64-bit + 5-Fold Stratified Group CV), `train_yolo.py`, dan notebook Google Colab siap dieksekusi di GPU T4. |
| **Frontend & UX** | 6.5 / 10 | 8.0 / 10 | **8.0 / 10** | Partial DOM polling, `visibilitychange`, mobile scroll, dan cache busting sudah berjalan. |
| **Runnability & Test Coverage** | 5.0 / 10 | 8.5 / 10 | **9.5 / 10** | Suite uji ditingkatkan dari 102 menjadi **133 pemeriksaan** mencakup aturan Perpol 7/2021, plat 2 baris, plat hitam, optimasi CPU/RAM, dan 5-Fold Stratified Group CV. |

### Ringkasan Jumlah Temuan

| Category / Severity | Audit Awal (21 Okt 2026) | Temuan Baru (23 Nov 2026) | Status Remediasi Temuan Baru |
| :--- | :---: | :---: | :--- |
| 🔴 **Critical / High (CPU, RAM, OCR & Training Degradation)** | 8 (**8 Selesai ✅**) | **9 Temuan Utama** (`PERF-1`..`PERF-3`, `OCR-1`..`OCR-3`, `OCR-10`, `TRAIN-1`..`TRAIN-2`) | **9 Selesai di Kode & Colab ✅** (`PERF-1`..`PERF-3`, `OCR-1`..`OCR-3`, `OCR-10`, `TRAIN-1`..`TRAIN-2`) |
| 🟡 **Medium (Efisiensi, Karakter & Generalisasi Model)** | 7 (**6 Selesai ✅, 1 Parsial ⚠️**) | **11 Temuan Menengah** (`PERF-4`..`PERF-7`, `OCR-4`..`OCR-7`, `OCR-11`, `TRAIN-3`..`TRAIN-4`) | **11 Selesai di Kode & Colab ✅** (`PERF-4`..`PERF-7`, `OCR-4`..`OCR-7`, `OCR-11`, `TRAIN-3`..`TRAIN-4`) |
| 🟢 **Low / Polish & Security Residual** | 6 (**6 Selesai ✅**) | **4 Temuan Ringan** (`SEC-1`..`SEC-2`, `OCR-8`..`OCR-9`) | **4 Selesai di Kode ✅** (`SEC-1`, `SEC-2`, `OCR-8`, `OCR-9`) |

---

## 2. Audit Khusus I: Efisiensi Penggunaan CPU & RAM

> **Status Remediasi (23 November 2026): SELESAI DIIMPLEMENTASIKAN ✅**
> Seluruh 7 temuan efisiensi CPU & RAM (**`PERF-1` s.d. `PERF-7`**) telah diperbaiki di [`app/config.py`](Tugas%20Citra%20Digital/prototype/app/config.py), [`app/ocr.py`](Tugas%20Citra%20Digital/prototype/app/ocr.py), [`app/pipeline.py`](Tugas%20Citra%20Digital/prototype/app/pipeline.py), dan [`app/service.py`](Tugas%20Citra%20Digital/prototype/app/service.py), serta diverifikasi di [`tests/test_pipeline.py`](Tugas%20Citra%20Digital/prototype/tests/test_pipeline.py).

Berdasarkan pemeriksaan kode pada `app/config.py`, `app/ocr.py`, `app/pipeline.py`, `app/detect_yolo.py`, `app/service.py`, dan `app/web.py`, berikut adalah akar masalah penggunaan CPU dan RAM beserta rekomendasi perbaikannya:

### 🔴 `PERF-1` [High — RAM]: Dual-Framework Memory Bloat (PaddlePaddle + PyTorch/EasyOCR + Ultralytics Hidup Bersamaan di RAM)
- **Lokasi**: `app/ocr.py:308-363` (`_paddle_reader`, `_paddle_rec_model`), `app/ocr.py:460-467` (`_easy_reader`), `app/ocr.py:764-775` (`read_plate`), `app/detect_yolo.py:138-151` (`_model`).
- **Analisis Masalah**:
  1. Saat startup (`web.py:85-89`), thread background memanggil `ocr.warmup()` dan `detect_yolo.available()`.
  2. Ketika `active_backend() == "paddleocr"`, `warmup()` memuat **dua** instance model Paddle sekaligus ke RAM: `_paddle_rec_model()` (`PP-OCRv6_medium_rec` via `paddlex.create_model`) **dan** `_paddle_reader()` (`PaddleOCR` penuh yang berisi *text detector* + *text recognizer* kedua). Ini berarti **model recognizer dimuat dua kali di memori**.
  3. Saat mode penuh (`fast=False`, misalnya klik *Scan & Simpan Log*, upload foto manual, atau simulasi CCTV) menemui **satu saja** crop kandidat atau potongan gambar yang gagal lolos `_looks_like_plate` di PaddleOCR, kode pada `ocr.py:764-769` otomatis memeriksa `importlib_available("easyocr")` dan memanggil `_read_easyocr(crop)`.
  4. Pemanggilan `_easy_reader()` menggunakan `@lru_cache(maxsize=1)` tanpa mekanisme *eviction*, sehingga langsung memuat **PyTorch + CRAFT detector + CRNN recognizer EasyOCR (±1,2–1,8 GB RAM)** secara permanen ke dalam proses `python.exe` yang sama dengan PaddlePaddle (±1,2 GB) dan Ultralytics YOLO (±300 MB).
- **Dampak**: Pemakaian RAM proses melonjak kembali ke **2,5–3,5 GB RSS** segera setelah ada 1 bacaan gagal pada mode penuh, yang menjelaskan terjadinya pembengkakan *page file* dan risiko OOM pada laptop 12 GB.
- **Rekomendasi**:
  - Matikan fallback lintas-framework secara default (`SGS_ENABLE_SECONDARY_OCR=0`), atau hanya izinkan satu engine OCR dimuat dalam satu siklus hidup proses.
  - Gunakan recognizer internal dari instance `_paddle_reader()` atau hindari memuat `PaddleOCR` penuh di `warmup()` (muat `_paddle_reader()` secara *lazy* hanya ketika jalur cepat `_paddle_rec_model()` benar-benar membutuhkan fallback deteksi).
  - Ekspor dan jalankan YOLO melalui **ONNX Runtime** (`best.onnx` sudah tersedia di `smartgate-artifacts-*/`) sehingga jika PaddleOCR dipakai, aplikasi bahkan tidak perlu memuat PyTorch ke RAM sama sekali.

### 🔴 `PERF-2` [High — CPU]: Ledakan Jumlah Panggilan OCR per Frame (*OCR Call Amplification*)
- **Lokasi**: `app/service.py:219-296` (`_process_frame`), `app/ocr.py:401-453` (`_read_paddle`), `app/ocr.py:625-701` (`read_plate_robust`), `app/ocr.py:738-780` (`read_plate`).
- **Analisis Masalah**:
  - Dalam 1 kali pemanggilan `_read_paddle(crop)` (`ocr.py:406-426`), jika hasil baca pertama memiliki keyakinan `0.50 <= conf < 0.95` dan zoom 2× tidak sepakat, fungsi tersebut menjalankan **3 inferensi neural network** beruntun: (1) `_read_paddle_rec_only(crop)`, (2) `_read_paddle_rec_only(zoom_2x)`, lalu (3) `reader.predict(crop)` (deteksi + rekognisi penuh).
  - Bila hasil itu belum berformat NRKB dan `fast=False`, `read_plate()` memanggil `_read_easyocr(crop)` yang dapat menjalankan **hingga 3 inferensi lagi** (`reader.recognize`, `reader.readtext(paragraph=False)`, `reader.readtext(paragraph=True)`). Artinya **1 panggilan `read_plate()` bisa memicu hingga 6 eksekusi model deep learning**.
  - Di level atasnya, `read_plate_robust()` (`ocr.py:673-697`) mencoba hingga `3 bases` (`row1`, `row2`, `crop`) + `4 ladder variants` (`zoom 2x`, `zoom 4x`, `enhance_plate`, `deglare`) = **hingga 7 pemanggilan `read_plate()`**.
  - Di level atasnya lagi, `_process_frame()` (`service.py:249-295`) mengevaluasi hingga **4 kandidat plat** (3 kandidat teratas + 1 `frame_text_candidate`), dan untuk setiap kandidat mengevaluasi hingga **4 views** (`grow_to_text_line`, `primary` dengan `read_plate_robust`, `full_crop`, `det.crop`) ditambah **2 `band_crops`** untuk 2 kandidat pertama.
- **Dampak**: Pada kasus plat sulit/buram atau kandidat false-positive, **satu frame tunggal** pada mode `fast=False` dapat memicu puluhan panggilan inferensi OCR secara sinkron. Dengan 3 frame pada *Scan & Simpan Log*, waktu tunggu membludak drastis dan CPU terkunci penuh selama puluhan detik.
- **Rekomendasi**:
  - Pasang **anggaran keras (hard budget) panggilan OCR per frame** (mis. maksimal `MAX_OCR_CALLS_PER_FRAME = 6` untuk mode penuh dan `2` untuk mode cepat).
  - Jangan jalankan `zoom 2x` di dalam `_read_paddle()` **sekaligus** `zoom 2x / 4x` di dalam `read_plate_robust()` — ini duplikasi pekerjaan yang identik.
  - Hentikan evaluasi view cadangan pada kandidat apabila kandidat tersebut pada view pertama menghasilkan confidence sangat rendah (`< 0.20`) dan tidak memiliki struktur baris teks.

### 🔴 `PERF-3` [High — CPU]: Pemrosesan Citra Penuh yang Redundan & Tidak Terpakai di Setiap Frame
- **Lokasi**: `app/service.py:205-207`, `app/pipeline.py:146-169` (`preprocess`), `app/pipeline.py:989-993` (`frame_score`), `app/pipeline.py:238-270` (`grow_to_text_line`), `app/pipeline.py:708-794` (`frame_text_candidate`).
- **Analisis Masalah**:
  1. **`preprocess(image, full=not fast)` dihitung sia-sia untuk deteksi**: Pada `service.py:205`, setiap frame mode penuh menjalankan konversi BGR→LAB, CLAHE resolusi penuh, dan **`cv2.bilateralFilter(stages["clahe"], 9, 75, 75)` pada frame penuh (1280×720)**. Bilateral filter diameter 9 pada resolusi HD adalah salah satu operasi OpenCV paling mahal di CPU (±25–45 ms per frame). Ironisnya, hasil `stages["clahe"]` dan `stages["denoise"]` **sama sekali tidak dipakai oleh `detect_plates` maupun OCR** — keduanya hanya dipakai untuk menghitung `sharpness` dan disimpan sebagai gambar PNG tahap pipeline (`_save_stages`)!
  2. **`laplacian_variance` dihitung 2 kali per frame**: Dihitung pertama kali di `service.py:207` (`sharpness = pipeline.laplacian_variance(gray)`), lalu dihitung ulang dari awal beserta konversi `cvtColor` di `service.py:346` → `pipeline.frame_score(image, detection_conf)`.
  3. **`grow_to_text_line` mengonversi dan mem-binarisasi Otsu seluruh frame penuh untuk setiap kandidat**: Pada `pipeline.py:254-255`, `gray = cv2.cvtColor(image, ...)` dan `cv2.threshold(gray, ..., THRESH_OTSU)` dijalankan pada **seluruh frame `image`**, bukan pada sub-window di sekitar `bbox` (`reach` hanya `1x tinggi` dan `1.5x lebar` bbox). Selain boros CPU, ambang Otsu global dari seluruh frame (yang didominasi aspal/bodi gelap) akan menghasilkan threshold yang salah untuk area lokal plat nomor!
  4. **`frame_text_candidate` selalu dijalankan walaupun YOLO sudah menemukan plat dengan keyakinan tinggi**: Pada `service.py:223`, `pipeline.frame_text_candidate(image)` selalu dipanggil pada setiap frame (termasuk `fast=True`!). Fungsi ini menjalankan GaussianBlur 5×5, `np.percentile` 2 kali, `morphologyEx`, dan `connectedComponentsWithStats` 2 kali pada seluruh ROI frame, padahal kandidat `rescue` di posisi ke-4 tidak akan pernah disentuh jika kandidat ke-1 dari YOLO sudah terbaca valid.
- **Dampak**: Pemborosan siklus CPU sebesar ±40–70 ms per frame untuk operasi piksel resolusi penuh yang redundan atau tidak pernah dipakai.
- **Rekomendasi**:
  - Ubah `frame_text_candidate(image)` menjadi **lazy generator / fallback**: hanya jalankan jika kandidat dari `detect_plates()` kosong atau semuanya gagal menghasilkan teks NRKB.
  - Pada `grow_to_text_line()`, potong sub-window `(x1 - reach_x : x2 + reach_x, y1 - reach_y : y2 + reach_y)` terlebih dahulu sebelum `cvtColor` dan `threshold(..., THRESH_OTSU)`. Ini 20× lebih cepat sekaligus membuat Otsu threshold akurat secara lokal pada papan plat.
  - Teruskan nilai `sharpness` yang sudah dihitung ke `frame_score()` agar tidak menghitung Laplacian dua kali.
  - Buat penyimpanan 8 file PNG di `_save_stages()` opsional (mis. `SGS_SAVE_PIPELINE_STAGES=0` secara default di produksi, aktifkan hanya saat mode debug/laporan akademik).

### 🟡 `PERF-4` [Medium — CPU & Disk I/O]: Penulisan 8 File PNG Tahap Pipeline secara Sinkron di Jalur Kritis
- **Lokasi**: `app/service.py:451-490`, `app/service.py:521-528` (`_save_stages`).
- **Analisis Masalah**: Setiap kali `persist=True` (Scan & Simpan Log / Simulasi / Upload), aplikasi menulis 1 JPG beranotasi + **hingga 8 file PNG tidak terkompresi cepat** (`original.png`, `clahe.png`, `denoise.png`, `gray.png`, `plate_raw.png`, `plate_crop.png`, `plate_enhanced.png`, `sticker_crop.png`) untuk **setiap frame**. Untuk 3 frame, terdapat **27 operasi `cv2.imencode` + disk write** yang dieksekusi secara sinkron sebelum HTTP response dikembalikan. Kompresi PNG (`cv2.imencode(".png", ...)`) pada 4 citra resolusi penuh per frame memakan ±150–300 ms CPU & I/O.
- **Rekomendasi**: Simpan tahap-tahap resolusi penuh hanya untuk `is_best_frame`, gunakan format `.jpg` (kualitas 85) yang 5× lebih cepat di-encode dibanding `.png`, atau pindahkan `_save_stages` ke background thread / flag konfigurasi.

### 🟡 `PERF-5` [Medium — CPU & RAM]: Hashing `crop.tobytes()` dan Penyimpanan Dict Tanpa Batas
- **Lokasi**: `app/ocr.py:637` (`hashlib.sha1(crop.tobytes()).digest()`), `app/service.py:542` (`hashlib.sha1(source.tobytes()).hexdigest()`), `app/service.py:169-180` (`_recent_log_plates`).
- **Analisis Masalah**:
  - `crop.tobytes()` dan terutama `source.tobytes()` (pada `_save_failed_diagnostics`, di mana `source` adalah frame penuh 1280×720×3 = **2,76 MB**) mengalokasikan buffer byte baru di memori hanya untuk di-hash SHA-1. `hashlib.sha1(np.ascontiguousarray(arr))` dapat membaca *buffer protocol* NumPy secara langsung (**zero-copy**, hemat alokasi RAM jutaan byte per frame).
  - Selain itu, pada kamera live, noise sensor kamera membuat nilai piksel berubah ±1 antar-frame meskipun kendaraan diam total. Akibatnya, `sha1(crop.tobytes())` pada `_ROBUST_CACHE` **hampir selalu cache-miss (0% hit rate)** pada video live nyata, dan hanya berguna bila array gambar yang persis sama dikirim ulang dalam pengujian.

### 🟡 `PERF-6` [Medium — CPU]: `cv2.setNumThreads` & `PaddlePredictorOption` Monkey-Patch Dipanggil Berulang
- **Lokasi**: `app/pipeline.py:30-36` (`_cv2()`), `app/ocr.py:326-340` (`_paddle_reader()`).
- **Analisis Masalah**:
  - Fungsi `_cv2()` dipanggil puluhan kali dalam satu frame, dan setiap pemanggilan mengeksekusi `cv2.setNumThreads(config.CPU_THREADS)`. Walaupun murah, seharusnya cukup dipanggil satu kali saat inisialisasi modul.
  - Pada `_paddle_reader()`, `PaddlePredictorOption.setdefault_by_model_name` di-*monkey-patch* dengan closure `original`. Jika `_paddle_reader.cache_clear()` pernah dipanggil, patch akan membungkus fungsi yang sudah di-patch secara rekursif.

### 🟡 `PERF-7` [Medium — CPU]: Detektor Klasik Menjalankan 15 Thresholding + `findContours` + `_merge_fragments` $O(N^3)$
- **Lokasi**: `app/pipeline.py:796-836` (`_merge_fragments`), `app/pipeline.py:860-875` (`detect_plates_classic`).
- **Analisis Masalah**: Saat fallback klasik aktif (atau saat YOLO tidak menemukan kandidat), `detect_plates_classic` menjalankan `3 kernel × (2 Otsu + 2 Adaptive Threshold) = 12 pass` morfologi + thresholding + `findContours`, menyortir kandidat di dalam loop luar, lalu memanggil `_merge_fragments` yang memiliki kompleksitas $O(N^3)$ karena `while merged:` mengulang nested loop `for i ... for j ...` atas ratusan kontur noise.
- **Rekomendasi**: Pindahkan `adaptiveThreshold` ke luar loop `kernel_w` (karena `adaptiveThreshold` di baris 869 memproses `gray`, **bukan** `closed`, sehingga saat ini kode menghitung adaptive threshold yang persis sama **3 kali berulang-ulang**!), dan batasi jumlah kandidat yang masuk ke `_merge_fragments` (mis. `candidates[:30]`).

---

## 3. Audit Khusus II: Fungsi Pengenalan Plat, Huruf, Angka & Aturan NRKB (Perpol No. 7 Tahun 2021)

> **Status Remediasi (23 November 2026): SELESAI DIIMPLEMENTASIKAN ✅**
> Seluruh temuan utama dan menengah pada bagian ini (**`OCR-1` s.d. `OCR-7`, `OCR-10`, dan `OCR-11`**) telah diperbaiki secara presisi di [`app/ocr.py`](Tugas%20Citra%20Digital/prototype/app/ocr.py), [`app/pipeline.py`](Tugas%20Citra%20Digital/prototype/app/pipeline.py), dan [`app/detect_yolo.py`](Tugas%20Citra%20Digital/prototype/app/detect_yolo.py), serta dikunci dengan **19 pemeriksaan baru** (total **121 pemeriksaan**) di [`tests/test_pipeline.py`](Tugas%20Citra%20Digital/prototype/tests/test_pipeline.py).

Pengujian mendalam terhadap logika di `app/ocr.py`, `app/pipeline.py`, `app/detect_yolo.py`, `app/vehicles.py`, serta hasil nyata pada `smartgate-artifacts-*/evaluation_summary.json` mengungkap **11 masalah fungsional pada pengenalan plat, huruf, dan angka** (9 di antaranya telah diselesaikan langsung pada siklus ini):

### 🔴 `OCR-1` [High — Akurasi Kode Wilayah]: `VALID_PREFIXES` Tidak Lengkap & `_PREFIX_FIX` Memaksa Banyak Huruf Menjadi `'D'`
- **Lokasi**: `app/ocr.py:52-58` (`_PREFIX_FIX`, `VALID_PREFIXES`), `app/ocr.py:113-115` (`normalize_plate`).
- **Analisis Masalah**:
  1. **Daftar kode wilayah (`VALID_PREFIXES`) tidak lengkap**: Beberapa kode wilayah resmi TNKB Indonesia **belum terdaftar** di `VALID_PREFIXES`, yaitu:
     - **`BP`** ada, tetapi **`BB`**, **`BD`**, **`BE`**, **`BG`**, **`BH`**, **`BK`**, **`BL`**, **`BM`**, **`BN`** — beberapa kode provinsi baru/lain seperti **`PA`**, **`PB`** ada, namun **`PG`** (Papua Pegunungan), **`PS`** (Papua Selatan), **`PT`** (Papua Tengah), **`PY`** (Papua Barat Daya) belum ada.
  2. **Bias destruktif `_PREFIX_FIX` ke huruf `'D'`**:
     ```python
     _PREFIX_FIX = str.maketrans({"0": "D", "1": "D", "O": "D", "I": "D", "L": "D", "8": "B"})
     ```
     Karena `"L": "D"` dipetakan tanpa syarat pada blok prefix, **semua plat Surabaya (`L`) otomatis rusak dan berubah menjadi plat Bandung (`D`)**! Contoh fatal:
     - Input `"L 1234 AB"` → `prefix = "L"` → `prefix.translate(_PREFIX_FIX)` mengubah `"L"` menjadi **`"D"`**! Karena `"D"` juga ada di `VALID_PREFIXES`, keduanya mendapat bonus `+2.0`, dan `normalize_plate("L 1234 AB")` mengembalikan **`"D1234AB"`**!
     - Input `"BL 1234 AB"` (Aceh) → berubah menjadi **`"BD1234AB"`** (Bengkulu)!
     - Input `"DL 1234 AB"` (Sitaro/Sulut) → berubah menjadi **`"DD1234AB"`** (Makassar)!
     - Input `"1 1234 AB"` atau `"I 1234 AB"` → selalu dipaksa menjadi `"D"`, padahal untuk plat `"B"` atau `"L"` atau `"T"`, tiang vertikal huruf yang terpotong bisa terbaca `"1"` atau `"I"`.
- **Bukti Dampak**: Ini adalah **bug fungsional kritis** pada pengenalan huruf wilayah. Kendaraan asal Surabaya (`L`), Aceh (`BL`), dan Sulut (`DL`) tidak akan pernah bisa dikenali sebagai wilayah aslinya karena huruf `L` di-hardcode berubah menjadi `D`.
- **Rekomendasi**:
  - **Jangan pernah** menerjemahkan huruf valid (`L`) melalui `_PREFIX_FIX` jika `prefix` asli (`"L"`, `"BL"`, `"DL"`) **sudah merupakan anggota `VALID_PREFIXES`**!
  - Terapkan `_PREFIX_FIX` **hanya pada karakter non-huruf** (`0`, `1`, `8`) atau hanya bila `prefix` mentah tidak ada di `VALID_PREFIXES` (mis. `"00"` → `"DD"`, `"O0"` → `"DD"`, `"8"` → `"B"`).
  - Untuk karakter `"O"`, `"I"`, `"1"`, evaluasi kandidat substitusi terhadap `VALID_PREFIXES` (mis. `"B1"` → `"BI"` bukan prefix valid, tapi `"BL"` / `"BA"` / `"BD"` / `"BE"` / `"BG"` / `"BH"` / `"BK"` / `"BM"` / `"BN"` / `"BP"` valid).

### 🔴 `OCR-2` [High — Akurasi Suffix & Angka]: Kegagalan Pemisahan Digit Terakhir vs Suffix Huruf (Contoh Nyata di Benchmark `evaluation_summary.json`)
- **Lokasi**: `app/ocr.py:39-47` (`_TO_DIGIT`, `_TO_ALPHA`, `_AMBIGUOUS`), `app/ocr.py:69-74` (`_char_scores`), `app/ocr.py:90-125` (`normalize_plate`).
- **Analisis Masalah**:
  Lihat bukti nyata pada `smartgate-artifacts-Y11N/evaluation_summary.json`:
  - `pl_test (13).jpg`: Raw OCR membaca `"DD1407"` (ground truth `DD 1407 QA`, suffix `QA` tidak terbaca). Namun `normalize_plate("DD1407")` justru mengubahnya menjadi **`"DD 140 T"`** (`"DD140T"`)!
  - `pl_test (14).jpg`: Raw OCR membaca `"DD2270"` → `normalize_plate` mengubahnya menjadi **`"DD 227 O"`** (`"DD227O"`)!
  - `pl_test (18).jpg`: Raw OCR membaca `"DD867112HI"` (ada noise bingkai/baut `12HI` di belakang) → diubah menjadi **`"DD 8671 IZH"`**!
  **Mengapa `DD1407` rusak menjadi `DD140T` dan `DD2270` rusak menjadi `DD227O`?**
  Perhatikan rumus skor di `normalize_plate()` (`ocr.py:110-112`):
  - Untuk `"DD1407"`:
    - Jika dipecah sebagai `prefix="DD" (2)`, `digits="1407" (4)`, `suffix="" (0)`:
      - `"0"` ada di `_AMBIGUOUS` (`"OQIZSBG012568"`) sehingga `_char_scores("0")` mengembalikan `(0.6, 0.6)`.
      - `"7"` tidak ada di `_AMBIGUOUS`, sehingga di blok digit bernilai `1.0`.
      - Bonus panjang digit: `0.5 * 4 = 2.0`.
    - Mengapa di Colab V6 muncul `"DD 140 T"`? Karena ketika suffix kosong dinilai kurang disukai atau ketika `"0"` / `"7"` berada di perbatasan blok, `_TO_ALPHA` memetakan `"7" -> "T"`, `"0" -> "O"`, `"2" -> "Z"`, `"1" -> "I"`, `"4" -> "A"`, `"5" -> "S"`, `"6" -> "G"`, `"8" -> "B"`.
    - Lebih parah lagi di `normalize_plate()` saat ini (`ocr.py:102-124`): untuk input dengan karakter ambigu di tengah/ujung seperti `"B1200"` (plat tanpa seri huruf atau seri huruf tidak terbaca), karena `"0"` berada di `_AMBIGUOUS`, `_char_scores("0")` memberi skor **sama persis (`0.6`) baik sebagai huruf maupun sebagai angka**! Akibatnya, antara split `digits="1200", suffix=""` vs `digits="120", suffix="0" (-> "O")` vs `digits="12", suffix="00" (-> "OO")`, selisihnya hanya ditentukan oleh `0.5 * digit_len`. Tetapi jika ada karakter yang bukan di `_AMBIGUOUS` atau jika jumlah karakter > 7 (mis. terbaca baut/stiker `"DD867112"`), digit `"12"` di belakang langsung dipaksa menjadi huruf `"IZ"` karena `digit_len` maksimal 4!
- **Rekomendasi**:
  - Bedakan bobot prior `(alpha_score, digit_score)` pada `_char_scores`: angka murni `"0", "1", "2", "5", "6", "8"` yang keluar dari OCR harus tetap memiliki preferensi sedikit lebih tinggi sebagai angka (mis. `(0.45, 0.75)`), sedangkan huruf `"O", "I", "Z", "S", "B", "G"` memiliki preferensi sedikit lebih tinggi sebagai huruf (mis. `(0.75, 0.45)`), **bukan `(0.6, 0.6)` yang buta arah**!
  - Tambahkan penalti untuk panjang string > 8 karakter atau buang token noise di ujung kanan (baut/bingkai yang terbaca `I` atau `1` di akhir suffix 3 huruf, seperti `O05877USI` → seharusnya `DD5877US`, bukan `DD5877USI` karena seri 3 huruf di luar Jabodetabek jarang berakhiran `I` akibat bingkai kanan).

### 🔴 `OCR-3` [High — Kegagalan Plat 2 Baris & Stiker Pajak]: `read_plate_robust` Memisahkan Baris dengan `text_rows` Tetapi Tidak Pernah Menggabungkannya Kembali
- **Lokasi**: `app/ocr.py:672-681` (`read_plate_robust`), `app/pipeline.py:498-527` (`text_rows`).
- **Analisis Masalah**:
  Pada `ocr.py:672-676`:
  ```python
  rows = pipeline.text_rows(crop) if getattr(crop, "size", 0) else []
  if len(rows) > 1:
      rows.sort(key=lambda row: row.shape[0] * row.shape[1], reverse=True)
      bases = [*rows[:2], crop]
  ```
  Lalu `for base in bases: if attempt(base): break`.
  Perhatikan apa yang terjadi pada **plat 2 baris (truk/bus/motor tertentu)** di mana baris atas adalah `"B 9012"` dan baris bawah adalah `"QWE"` (seperti yang dibuat oleh `simulate.split_two_rows("B 9012 QWE")` → baris 1: `"B9012"`, baris 2: `"QWE"`):
  1. `text_rows(crop)` memotong plat menjadi 2 gambar terpisah: `row_atas` (`"B 9012"`) dan `row_bawah` (`"QWE"`).
  2. `attempt(row_atas)` membaca **`"B9012"`** saja (tanpa suffix `"QWE"`!).
  3. Apakah `"B9012"` lolos `_looks_like_plate("B9012")`? **YA!** Karena regex `[A-Z]{1,3}[1-9][0-9]{0,3}[A-Z]{0,3}` mengizinkan suffix 0 huruf (`{0,3}`) dan `len("B9012") == 5 >= 5`!
  4. Bila confidence ≥ 0.80, `attempt(row_atas)` langsung mengembalikan `True` (**early-exit!**) dan **berhenti membaca**! Baris kedua (`"QWE"`) maupun `crop` utuh **tidak pernah dibaca sama sekali**!
  5. Akibatnya, plat 2 baris `"B 9012 QWE"` akan terbaca terpotong sebagai **`"B9012"`**, gagal cocok dengan database (`"B 9012 QWE"`), dan menghasilkan keputusan **`NO_MATCH`**!
- **Dampak**: Seluruh plat 2 baris (truk/bus, seperti kendaraan seed ke-3 `B 9012 QWE` — PT Mitra Logistik) berisiko tinggi kehilangan seluruh huruf seri di baris bawah karena `attempt()` berhenti dini pada baris pertama.
- **Rekomendasi**:
  - Pada `attempt()`, jangan izinkan *early-exit* pada potongan `row` tunggal (`base is not crop`) apabila teks yang terbaca **tidak memiliki suffix huruf** (`re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,3}", text)`), atau bila `vehicle_class == "truck"`.
  - Jika `len(rows) >= 2`, gabungkan hasil bacaan baris atas (prefix+angka) dan baris bawah (suffix huruf) apabila `row_bawah` berisi 1–3 huruf murni (dan bukan format tanggal `\d{2}\s*\d{2}`).

### 🟡 `OCR-4` [Medium — Kehilangan Karakter Tepi]: `snap_to_text_band` Memotong Huruf Pertama/Terakhir Saat Kontras Tidak Merata
- **Lokasi**: `app/pipeline.py:529-589` (`snap_to_text_band`), `app/detect_yolo.py:249-263`.
- **Analisis Masalah**:
  - Bahkan setelah YOLO mendeteksi bounding box plat dengan tepat, `detect_yolo.py:249` dan `260` memanggil `snap_to_text_band(ocr_crop)`.
  - Di dalam `snap_to_text_band`, gambar dikonversi ke biner dengan **satu nilai Otsu global** (`_ink_mask` → `cv2.threshold(gray, 0, 255, THRESH_BINARY_INV + THRESH_OTSU)`).
  - Pada plat nomor nyata yang terkena bayangan miring atau silau di satu sisi, huruf prefix di ujung kiri (mis. `"B"` atau `"D"` pertama pada `"DD"`) atau huruf suffix di ujung kanan sering lebih redup/terang daripada bagian tengah plat, sehingga jatuh di sisi yang salah dari ambang Otsu global.
  - Akibatnya, `cols = np.nonzero((sub > 0).sum(axis=0) > ...)` **memangkas habis huruf tepi tersebut** dari `ocr_crop` sebelum dikirim ke PaddleOCR!
  - Ini terlihat jelas pada `evaluation_summary.json` (Y8X `pl_test (13).jpg`: `"DD 1407 QA"` terpotong kiri-kanan menjadi `"D1407"`, dan `pl_test (16).jpg`: `"B 2287 TXO"` terpotong huruf `"B"` di kiri menjadi `"2287TXOII"` yang kemudian ditolak total karena diawali angka!).
- **Rekomendasi**:
  - Untuk deteksi yang berasal dari **YOLO** (`backend == "yolo"`), bounding box YOLO sudah dilatih ketat pada papan plat: **jangan gunakan `snap_to_text_band` untuk memangkas arah horizontal (`x1, x2`)** pada crop YOLO, cukup batasi vertikal (`y1, y2`) atau gunakan `full_crop` sebagai view pertama sebelum view yang di-snap!
  - Di `_process_frame()` (`service.py:258-264`), `full_crop` saat ini ditaruh di urutan terakhir dan bahkan hanya memakai `read_plate` biasa (`use_robust=False`). Urutan view sebaiknya mengutamakan `raw_crop` / `full_crop` dari YOLO sebelum `grow_to_text_line` yang berbasis Otsu.

### 🟡 `OCR-5` [Medium — Polaritas Plat]: `_ink_mask`, `grow_to_text_line`, dan `_read_template` Mengasumsikan Plat Putih (Teks Gelap di Latar Terang)
- **Lokasi**: `app/pipeline.py:255` (`grow_to_text_line`), `app/pipeline.py:430` (`_ink_mask`), `app/ocr.py:258` (`_read_template`).
- **Analisis Masalah**:
  - Ketiga fungsi tersebut menggunakan `cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU` secara tetap.
  - `THRESH_BINARY_INV` mengasumsikan bahwa **piksel gelap (nilai rendah) adalah tinta karakter (`255`)** dan **piksel terang adalah latar papan (`0`)** — yang hanya benar untuk **TNKB warna dasar putih** (terbaru).
  - Untuk **TNKB warna dasar hitam dengan teks putih** (yang masih sangat banyak beroperasi di jalan, contohnya `pl_test (14).jpg` `"plate_color": "BLACK"` di dataset uji), `THRESH_BINARY_INV` melakukan kebalikannya: **latar hitam plat berubah menjadi "tinta" putih masif**, sedangkan karakter putih berubah menjadi lubang hitam (`0`)!
  - Akibatnya, pada plat hitam:
    1. `_ink_mask` menghasilkan blok penuh sehingga `ink_glyph_count`, `split_rows`, `text_rows`, dan `snap_to_text_band` salah menghitung profil proyeksi.
    2. `grow_to_text_line` tumbuh tak terkendali ke seluruh area gelap bodi/ban kendaraan.
    3. Fallback `_read_template` gagal total mengekstrak glyph pada plat hitam.
- **Rekomendasi**:
  - Deteksi polaritas crop terlebih dahulu di `_ink_mask()`: bandingkan rata-rata/median intensitas area inti atau jumlah komponen terhubung antara `binary` dan `255 - binary` (jika proporsi piksel `> 0` pada `binary` melebihi `0.55`, balikkan mask `binary = 255 - binary` sehingga tinta karakter selalu bernilai `255` baik untuk plat putih, hitam, kuning, maupun merah).

### 🟡 `OCR-6` [Medium — Aturan Hard-Gate Awalan Huruf]: `best_plate_text` Menolak Kandidat yang Huruf Depannya Terbaca Sebagai Angka Mirip Huruf (`8`→`B`, `0`→`D`)
- **Lokasi**: `app/ocr.py:603-623` (`best_plate_text`).
- **Analisis Masalah**:
  Perhatikan kontradiksi antara `normalize_plate()` dan `best_plate_text()`:
  - Di `normalize_plate()` (`ocr.py:33,39,52,113`), sistem secara khusus dirancang untuk mengoreksi huruf depan yang salah terbaca sebagai angka oleh OCR:
    - `"8 1234 XYZ"` → `"B1234XYZ"` (`8` di blok huruf depan = `B`)
    - `"00 5877 US"` → `"DD5877US"` (`00` di blok huruf depan = `DD`)
  - **TETAPI**, di `best_plate_text()` (`ocr.py:616-618`):
    ```python
    for candidate in _plate_candidates(texts):
        if not candidate[:1].isalpha():
            continue
        normalized = normalize_plate(candidate)
    ```
  - Karena `if not candidate[:1].isalpha(): continue` dieksekusi **SEBELUM** `normalize_plate(candidate)`, maka ketika PaddleOCR/EasyOCR mengembalikan `"81234XYZ"` (plat Jakarta `B` yang terbaca `8`) atau `"005877US"` (plat Makassar `DD` yang terbaca `00`, kasus nyata `pl_test (10).jpg` di `evaluation_summary.json`!), **`best_plate_text` langsung membuangnya dan mengembalikan `""` (kosong / gagal baca)!**
  - Satu-satunya alasan `test_normalize_plate` di `tests/test_pipeline.py` lulus untuk `"8 1234 XYZ"` adalah karena test tersebut memanggil `ocr.normalize_plate()` secara langsung, sedangkan jalur nyata (`_read_paddle`, `_read_easyocr`, `_read_template`) memanggil **`best_plate_text()`** yang menolak semua string berawalan `'8'` atau `'0'`!
- **Dampak**: Fitur unggulan V4 parser (`00`→`DD` dan `8`→`B` pada awalan plat) **mati total (dead feature) di pipeline OCR nyata** karena diblokir oleh `candidate[:1].isalpha()` di `best_plate_text()`!
- **Rekomendasi**:
  - Izinkan karakter awalan ambigu (`0`, `8`, `1`) masuk ke `normalize_plate()` **asalkan** kandidat tersebut memiliki huruf suffix di belakang (mis. `re.search(r"[A-Z]{1,3}$", candidate)`) dan panjangnya ≥ 5 karakter (sehingga stiker tanggal murni angka seperti `"0425"` atau `"1226"` tetap ditolak 100%, sementara `"005877US"` dan `"81234XYZ"` berhasil diselamatkan menjadi `"DD5877US"` dan `"B1234XYZ"`).

### 🟡 `OCR-7` [Medium — Peta Substitusi Karakter]: Kekurangan Pasangan Karakter Ambigu pada `_TO_ALPHA`, `_TO_DIGIT`, dan `_AMBIGUOUS`
- **Lokasi**: `app/ocr.py:39-47`.
- **Analisis Masalah**:
  - Di `TRAINING_GUIDE.md:284` dan `TUGAS_PENGOLAHAN_CITRA_DIGITAL.md:151` didokumentasikan bahwa sistem menangani pasangan `B/8, 6/G, 1/I, O/0, I/1, L/1, S/5, T/7, A/4, D/0, V/U, W/VV, X/XX, Z/2`.
  - Namun di kode `app/ocr.py:39-47`:
    1. `"T"`, `"7"`, `"A"`, `"4"`, `"D"`, `"L"` ada di `_TO_DIGIT` / `_TO_ALPHA`, **tetapi TIDAK ADA di `_AMBIGUOUS = set("OQIZSBG012568")`**! Akibatnya, saat `"4"` muncul di blok huruf (seharusnya `"A"`, mis. `"B 1234 4BC"`) atau `"7"` muncul di blok huruf (seharusnya `"T"`), atau `"T"` / `"A"` / `"L"` / `"D"` muncul di blok angka (mis. `"DD54L1XA"` pada `pl_test (11).jpg`), `_char_scores()` menghukumnya dengan skor rendah `0.2` (bukan `0.6`), sehingga pemecahan blok yang benar bisa kalah skor dari pemecahan blok yang salah!
    2. `"3"` di blok huruf sering merupakan huruf `"B"` atau `"E"` yang terpotong kiri, namun `"3"` belum ada di `_TO_ALPHA`.

### 🟢 `OCR-8` [Low — Kualitas Input OCR]: `_enhance_ocr_crop` Adalah Dead Code & `deglare` Memicu Artefak pada Plat Putih
- **Lokasi**: `app/ocr.py:530-547` (`_enhance_ocr_crop`), `app/pipeline.py:181-201` (`deglare`).
- **Analisis Masalah**:
  - Fungsi `_enhance_ocr_crop(crop)` didefinisikan di `app/ocr.py:530` tetapi **tidak pernah dipanggil di mana pun** di seluruh codebase (*dead code*).
  - Fungsi `deglare(crop)` (`pipeline.py:191`) menganggap semua piksel dengan `gray >= 245` sebagai pantulan cahaya (glare) lalu melakukan `cv2.inpaint(..., INPAINT_TELEA)`. Pada TNKB putih yang terang (atau plat sintetis yang latarnya `RGB(246, 246, 242)` → `gray = 245`), seluruh latar papan putih dianggap glare dan di-inpaint dari tepi huruf hitam, sehingga huruf melebar/kabur.

### 🟢 `OCR-9` [Low — Evaluasi & Benchmark]: `tools/eval_real.py` Memanggil `ocr.read_plate(image)` Langsung Tanpa `read_plate_robust`
- **Lokasi**: `app/tools/eval_real.py:115`.
- **Analisis Masalah**: Skrip evaluasi `eval_real.py` memanggil `ocr.read_plate(image)` secara langsung tanpa melalui `ocr.read_plate_robust(image)`, sehingga tangga retry (zoom, split baris, enhance) tidak ikut teruji saat benchmark CLI dijalankan.

### 🔴 `OCR-10` [High — Kepatuhan Perpol No. 7 Tahun 2021]: Alokasi Nomor Urut Masih Memakai Aturan Tunggal (Belum Membedakan Polda Metro Jaya `B` vs Umum, serta Bus `7000–7999` vs Barang `8000–8999`)
- **Lokasi**: `app/ocr.py:32-38, 59, 84-88` (`NUMBER_GROUPS`, `number_fits_class`).
- **Analisis Masalah**:
  1. Saat ini `app/ocr.py:59` masih mengacu pada aturan lama (Perkapolri 5/2012) dengan satu tabel statis:
     ```python
     NUMBER_GROUPS = ((1, 1999, "car"), (2000, 6999, "motorcycle"), (7000, 8999, "truck"), (9000, 9999, "custom"))
     ```
  2. Berdasarkan **Peraturan Kepolisian (Perpol) Nomor 7 Tahun 2021** tentang Registrasi dan Identifikasi Kendaraan Bermotor:
     - **Wilayah Umum (Non-Polda Metro Jaya)**:
       - Mobil Penumpang / Pribadi: **`1 – 1999`**
       - Sepeda Motor: **`2000 – 6999`**
       - Mobil Bus: **`7000 – 7999`**
       - Mobil Barang / Truk: **`8000 – 8999`**
       - Kendaraan Khusus: **`9000 – 9999`**
     - **Wilayah Polda Metro Jaya (Kode Wilayah `B`)**:
       - Mobil Penumpang / Pribadi: **`1 – 2999`**
       - Sepeda Motor: **`3000 – 6999`**
       - Mobil Bus: **`7000 – 7999`**
       - Mobil Barang / Truk: **`8000 – 8999`**
       - Kendaraan Khusus: **`9000 – 9999`**
  3. **Akibat di kode saat ini**: Mobil pribadi Jakarta dengan nomor urut `2000–2999` (mis. **`B 2287 TXO`** pada `pl_test (16).jpg` di `evaluation_summary.json`!) oleh `number_fits_class("B2287TXO", "car")` justru dianggap **`False` (dianggap sepeda motor, bukan mobil!)**, sehingga kehilangan skor kesesuaian kelas kendaraan (`fits = 0`) pada `read_plate_robust()` dan `_process_frame()`.

### 🟡 `OCR-11` [Medium — Filter Masa Berlaku 4 Digit `MMYY` & Struktur Karakter Perpol 7/2021]: Stiker Tanggal Tanpa Pemisah (`0425`, `1228`) Masih Bisa Menempel ke Blok Suffix
- **Lokasi**: `app/ocr.py:102-124, 555-558, 579` (`_DATE_LIKE`, `_looks_like_plate`, `normalize_plate`).
- **Analisis Masalah**:
  1. **4 Digit Masa Berlaku di Bawah TNKB (`MMYY`)**:
     - Pada bagian bawah TNKB terdapat **4 digit angka masa berlaku**: **2 digit awal = Bulan (`01`–`12`)** dan **2 digit belakang = Tahun (mis. `24`–`35`)**.
     - Saat ini `_DATE_LIKE = re.compile(r"^\d{1,2}[.\-·\s]\d{2,4}$")` (`ocr.py:579`) **mewajibkan adanya karakter pemisah** (`.`, `-`, `·`, atau spasi). Apabila OCR membaca 4 digit masa berlaku tanpa spasi sebagai kotak terpisah `"0427"` atau `"1228"`, atau menggabungkannya di belakang teks plat (mis. `"B1234XY1228"`), `_DATE_LIKE` **gagal menyaringnya**!
     - Lebih buruk lagi, jika `"1228"` atau `"0926"` menempel di belakang plat tanpa suffix atau suffix 1 huruf, `normalize_plate` dapat menerjemahkan digit bulan/tahun tersebut menjadi huruf melalui `_TO_ALPHA` (`12` → `IZ`, `09` → `O9`, `28` → `ZB`).
  2. **Ketegasan Struktur Blok Alfanumerik (Perpol No. 7 Tahun 2021)**:
     - Format baku TNKB Indonesia: **`[Kode Wilayah 1–2 Huruf] [Nomor Urut 1–4 Angka] [Seri Akhir 1–3 Huruf]`** (contoh: `[A] [9999] [AAA]`, `[A] [9999] [AA]`, `[A] [9999] [A]`, `[AA] [9999] [A]`, `[AA] [9999] [AA]`, `[AA] [9999] [AAA]`, sesuai alokasi daerah Polda masing-masing).
     - **Aturan mutlak**: **Tidak pernah ada angka di dalam blok alfabet (kode wilayah & seri akhir), dan tidak pernah ada alfabet di dalam blok angka (nomor urut)**.
     - Di `app/ocr.py:102`, `for prefix_len in (1, 2, 3):` masih mengizinkan `prefix_len = 3` huruf, padahal seluruh kode wilayah resmi Kepolisian RI di Indonesia hanya terdiri dari **1 atau 2 huruf** (`A` s.d. `Z` dan `AA` s.d. `PY` — tidak ada kode wilayah 3 huruf!). Mengizinkan `prefix_len = 3` justru membuat noise di kiri plat atau digit pertama nomor urut tercuri menjadi huruf ke-3 kode wilayah.

---

### 3.1 Spesifikasi Lengkap Aturan Pembacaan TNKB & NRKB (Perpol Nomor 7 Tahun 2021)

Tabel dan aturan di bawah ini merupakan acuan resmi yang wajib ditegakkan oleh parser `app/ocr.py` dan quality gate `app/pipeline.py`:

#### A. Pola Struktur Blok Karakter (`[Alfabet Wilayah] [Angka Nomor Urut] [Alfabet Seri]`)
1. **Struktur Wajib 3 Blok**:
   - **Blok 1 — Kode Wilayah Pendaftaran (`1` atau `2` Alfabet)**:
     - 1 Huruf: `A, B, D, E, F, G, H, K, L, M, N, P, R, S, T, W, Z`
     - 2 Huruf: `AA, AB, AD, AE, AG, BA, BB, BD, BE, BG, BH, BK, BL, BM, BN, BP, DA, DB, DC, DD, DE, DG, DH, DK, DL, DM, DN, DP, DR, DT, DW, EA, EB, ED, KB, KH, KT, KU, PA, PB, PG, PS, PT, PY`
   - **Blok 2 — Nomor Urut Registrasi (`1` s.d. `4` Angka, digit pertama `1–9`, tidak pernah diawali `0`)**:
     - Mewakili sampai 4 digit angka (`[Angka]`, `[Angka][Angka]`, `[Angka][Angka][Angka]`, `[Angka][Angka][Angka][Angka]`).
   - **Blok 3 — Seri Huruf Akhir (`1` s.d. `3` Alfabet, atau `0` khusus kendaraan tertentu)**:
     - Kombinasi yang sah mengikuti wilayah Polda:
       - `[Alfabet] [1-4 Angka] [Alfabet][Alfabet][Alfabet]` (mis. `B 1234 XYZ`)
       - `[Alfabet] [1-4 Angka] [Alfabet][Alfabet]` (mis. `D 1234 AB`)
       - `[Alfabet] [1-4 Angka] [Alfabet]` (mis. `L 1234 A`)
       - `[Alfabet][Alfabet] [1-4 Angka] [Alfabet]` / `[Alfabet][Alfabet]` / `[Alfabet][Alfabet][Alfabet]` (mis. `DD 1234 A`, `DD 1234 AB`, `DD 1234 ABC`)
2. **Pemisahan Mutlak Alfabet vs Angka**:
   - **Tidak boleh ada angka di blok alfabet** (Blok 1 & Blok 3) dan **tidak boleh ada alfabet di blok angka** (Blok 2).
   - Setiap karakter OCR yang melanggar jenis blok pada posisi tersebut wajib dikoreksi lewat peta disambiguasi kontekstual (`8↔B`, `0/O↔D/0`, `1/I/L↔1/I`, `5↔S`, `6↔G`, `2↔Z`, `7↔T`, `4↔A`) atau ditolak jika tidak dapat membentuk pola sah.

#### B. Alokasi Nomor Urut Registrasi Berdasarkan Jenis Kendaraan (Umum vs Polda Metro Jaya)

| Golongan / Jenis Kendaraan | Rentang Nomor Urut **Umum (Nasional)** | Rentang Nomor Urut **Polda Metro Jaya (`B`)** | Kelas Internal (`app/vehicles.py`) |
| :--- | :---: | :---: | :---: |
| **Mobil Penumpang (Pribadi)** | **`1 – 1999`** | **`1 – 2999`** | `car` |
| **Sepeda Motor** | **`2000 – 6999`** | **`3000 – 6999`** | `motorcycle` |
| **Mobil Bus** | **`7000 – 7999`** | **`7000 – 7999`** | `bus` / `truck` |
| **Mobil Barang (Truk / Pick-up)** | **`8000 – 8999`** | **`8000 – 8999`** | `truck` |
| **Kendaraan Khusus** | **`9000 – 9999`** | **`9000 – 9999`** | `custom` |

#### C. Aturan 4 Digit Masa Berlaku di Bawah TNKB (`MMYY`)
- Di bagian bawah nomor utama TNKB terdapat **4 digit angka masa berlaku** (`[B1][B2] · [T1][T2]`):
  - **2 digit awal (`01` s.d. `12`)** = **Bulan** berakhirnya masa berlaku (01 = Januari s.d. 12 = Desember).
  - **2 digit belakang (`20` s.d. `39`)** = **Tahun** berakhirnya masa berlaku (siklus 5 tahunan STNK/TNKB).
- **Perlakuan di Sistem OCR**:
  - Baris bawah atau token 4 digit yang memenuhi pola `^(0[1-9]|1[0-2])[.\-·\s]?\d{2}$` (baik dengan pemisah maupun tanpa pemisah seperti `0425`, `1228`, `09.27`) **wajib dikenali sebagai Tanggal Berlaku TNKB dan dibuang dari kandidat nomor plat utama** (atau disimpan terpisah di metadata `expiry_mmyy`), sehingga tidak pernah bergabung ke suffix huruf atau terbaca sebagai nomor plat palsu.

#### D. Warna Dasar TNKB (Pasal 45 Perpol No. 7 Tahun 2021) & Ukuran Geometri pada Gambar Bergerak
1. **4 Warna Dasar Resmi (+ Lis Biru Kendaraan Listrik)**:
   - **Putih tulisan Hitam**: Kendaraan perseorangan, badan hukum, PNA, dan Badan Internasional (standar baru ramah ETLE/ALPR).
   - **Kuning tulisan Hitam**: Kendaraan bermotor umum (angkutan penumpang/barang umum).
   - **Merah tulisan Putih**: Kendaraan bermotor instansi pemerintah.
   - **Hijau tulisan Hitam**: Kendaraan bermotor di kawasan perdagangan bebas (*Free Trade Zone*).
   - *(Catatan Transisi)*: TNKB lama **Hitam tulisan Putih** yang masa berlakunya belum habis masih dijumpai di lapangan, sehingga `_ink_mask()` wajib mendukung **dua polaritas** (teks gelap di latar terang & teks terang di latar gelap).
2. **Ukuran & Rasio Geometri pada Gambar Bergerak (Heuristik Toleran, Bukan Ambang Kaku)**:
   - Ukuran fisik acuan papan TNKB: **Roda 4 (Mobil/Truk/Bus)** sekitar `430–460 × 130–135 mm` (rasio aspek ideal $\approx 3,26 – 3,54$; atau plat 2 baris `230 × 130 mm` rasio $\approx 1,77$), dan **Roda 2/3 (Motor)** sekitar `250–275 × 105–110 mm` (rasio aspek ideal $\approx 2,38 – 2,50$).
   - **Karena kendaraan bergerak** (sudut pandang kamera miring, *foreshortening* perspektif saat mendekat dari CCTV 1 ke CCTV 2, serta *motion blur*), ukuran piksel absolut dan rasio aspek pada frame 2D akan berubah-ubah secara dinamis.
   - Oleh karena itu, ukuran/rasio (`app/vehicles.py`) **tidak boleh dijadikan pemutus tunggal yang kaku**, melainkan dipakai sebagai:
     - **Rentang filter longgar (*soft bounding gate*)**: menerima rasio `1,20 – 5,00` dengan proporsi luas `0,06% – 15%` area frame agar plat yang memendek karena sudut perspektif tidak terbuang.
     - **Pemberi skor prior (*soft prior*)**: dikombinasikan dengan golongan nomor urut Perpol 7/2021 (`1–1999`/`1–2999` mobil vs `2000–6999`/`3000–6999` motor) untuk memvalidasi konsistensi antara bentuk fisik plat dan nomor yang terbaca.

---

## 4. Audit Khusus III: Degradasi Model Training, Generalisasi & Cross-Validation

Pertanyaan kunci: **Mengapa model hasil training (`YOLOv8n`, `YOLOv11n`) sering mengalami degradasi performa saat dihadapkan pada kamera nyata atau seiring berjalannya epoch, dan apakah *Generalization* serta *Cross-Validation* dapat diterapkan?**

**Jawaban singkat: SANGAT BISA dan TELAH DITERAPKAN DENGAN HASIL TERVERIFIKASI (Eksperimen v6 Multi-Domain Fold 0).** Audit terhadap [`tools/merge_datasets.py`](Tugas%20Citra%20Digital/prototype/tools/merge_datasets.py), [`train_yolo.py`](Tugas%20Citra%20Digital/prototype/train_yolo.py), [`plat-nomor/a_YOLOv11n.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a_YOLOv11n.ipynb), [`plat-nomor/a_YOLOv8n.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a_YOLOv8n.ipynb), serta kurva epoch di [`smartgate-artifacts-Y8N/results.csv`](smartgate-artifacts-Y8N/results.csv) dan [`smartgate-artifacts-Y11N/results.csv`](smartgate-artifacts-Y11N/results.csv) menemukan **4 akar penyebab utama terjadinya degradasi model** dan membuktikan efektivitas perbaikannya:

### Hasil Eksperimen Terverifikasi Pasca-Remediasi (v6 Multi-Domain Fold 0)

| Metrik Evaluasi | YOLOv8n (`smartgate-colab-v6-yolov8n`) | YOLOv11n (`smartgate-colab-v6-yolo11n`) | Analisis & Perbandingan |
| :--- | ---: | ---: | :--- |
| **Bobot `.pt` / `.onnx`** | `6,48 MB` / `12,77 MB` | **`5,48 MB` / `10,66 MB`** | YOLOv11n 15,4% lebih ringan. |
| **Validation Fold 0 mAP50** *(multi-domain ~813 citra)* | **`0,8488`** | `0,8464` | Evaluasi jujur lintas 5 domain (`orig`, `rf`, `kg`, `mg`, `bg`) dengan anti-leakage `dHash` 64-bit. |
| **Validation Fold 0 mAP50-95** *(multi-domain)* | `0,5669` | **`0,5686`** | Naik dibanding validasi split lama (`0,5536–0,5635`) meskipun diuji pada multi-domain yang jauh lebih sulit. |
| **Test Hold-out mAP50** *(84 citra)* | `0,9617` *(naik dari 0,9564)* | **`0,9693`** *(naik dari 0,9683)* | **Tertinggi**: generalisasi hold-out meningkat berkat checkpoint multi-domain + regularisasi anti-degradasi. |
| **Test Hold-out mAP50-95** *(84 citra)* | `0,5931` | **`0,6150`** | YOLOv11n memiliki ketepatan regresi kotak (IoU ketat) terbaik pada set uji. |
| **End-to-End OCR Valid Format Rate** | **`75,96%` (`79/104`)** | `74,07%` (`80/108`) | YOLOv8n naik signifikan dari `72,03%` ke **`75,96%`** berkat parser Perpol 7/2021 (`005877US -> DD 5877 US`, `IDD14070M -> DD 1407 OM`). |
| **Latency End-to-End Rata-rata / P95** | **`76,50 ms` / `157,19 ms`** | `87,43 ms` / `161,03 ms` | Latensi turun ±12–20 ms karena berkurangnya deteksi fragmen palsu. |

### 🔴 `TRAIN-1` [High — Ketimpangan Split & Single-Domain Validation]: 3.982 Gambar Train (Multi-Domain) Hanya Divalidasi oleh 84 Gambar dari 1 Sumber Tunggal (96% : 2% : 2%)
- **Lokasi**: `tools/merge_datasets.py:4-14, 115-208`, `plat-nomor/a_YOLOv11n.ipynb:123-125`.
- **Bukti Terukur**:
  - `train`: **3.982 gambar** (5.154 kotak plat, gabungan 4 domain berbeda: `plat-nomor` asli + `mg_` dataset_merged + `rf_` Roboflow + `kg_` Kaggle COCO + 17 `bg_` background).
  - `valid`: **Hanya 84 gambar** (99 kotak plat, **0 background**, 100% berasal dari dataset awal `plat-nomor` — mayoritas plat Makassar `DD`).
  - `test`: **Hanya 84 gambar** (102 kotak plat, **0 background**, 100% berasal dari dataset awal `plat-nomor`).
- **Mengapa Ini Memicu Degradasi Model**:
  1. Ketika `merge_datasets.py` menggabungkan ribuan gambar baru dari Kaggle (`kg_`) dan Roboflow (`rf_`), **100% data tambahan dimasukkan hanya ke folder `train`**, sedangkan `valid` dan `test` dibiarkan tetap 84 gambar lama.
  2. Akibatnya, metrik validasi (`val/mAP50` dan `val/box_loss`) yang digunakan YOLO untuk memilih `best.pt` hanya mengukur performa pada 84 gambar dari 1 domain sempit, bukan kemampuan generalisasi lintas-domain.
  3. Karena `valid` hanya berisi 84 gambar (3 batch @ `batch=16`), 1–2 gambar yang meleset sudah menggeser mAP sebesar ±1,5–2,5%. Seleksi `best.pt` menjadi sangat bising (*high variance*).
  4. `valid` memiliki **0 gambar background tanpa plat**, sehingga model yang menghasilkan *false positive* pada latar kosong tidak mendapatkan penalti yang memadai saat pemilihan checkpoint `best.pt` (dan di `train` pun hanya ada 17 gambar background dari 3.982 gambar = **0,42%**, jauh di bawah rekomendasi Ultralytics sebesar **5–10% background negatif**).

### 🔴 `TRAIN-2` [High — Overfitting & Degradasi Akhir Epoch pada Model Besar]: Bukti Degradasi di `results.csv` dan Ketiadaan Regularisasi Struktural
- **Lokasi**: `smartgate-artifacts-Y8X/results.csv:31-51`, `smartgate-artifacts-Y11N/results.csv:41-51`, `train_yolo.py:76-88`.
- **Bukti Terukur dari `results.csv`**:
  - Pada **YOLOv8x** (68,2 juta parameter):
    - `val/box_loss` mencapai titik terendah (terbaik) pada **Epoch 30 (`1.31881`)** dengan `val mAP50-95 = 0.55768`.
    - Dari **Epoch 31 hingga Epoch 50**, meskipun `train/box_loss` terus turun tajam dari `0.915` ke `0.700`, **`val/box_loss` justru mengalami degradasi (naik kembali) ke `1.39457–1.42527`**, dan `val mAP50` turun dari puncak `0.93883` (Epoch 32) ke `0.92832` (Epoch 50).
    - Pada saat `close_mosaic=10` mematikan augmentasi Mosaic di **Epoch 41**, `train/cls_loss` anjlok drastis (`0.478 -> 0.411 -> 0.355`), pertanda model mulai menghafal (*memorizing*) piksel gambar utuh dan kehilangan generalisasi batas kotak (terbukti di benchmark OCR: YOLOv8x punya valid format OCR terendah **67,52%**, kalah jauh dari YOLOv11n **75,00%**).
  - Pada `train_yolo.py:76-88` (skrip CLI lokal): parameter generalisasi yang ada di notebook Colab (`cos_lr`, `hsv_*`, `degrees`, `scale`, `mosaic`, `mixup`, `close_mosaic`, `weight_decay`, `dropout`) **sama sekali belum dipasang** — `train_yolo.py` hanya memanggil `model.train()` dengan argumen minimal default.

### 🟡 `TRAIN-3` [Medium — Tidak Ada Cross-Validation & Kebocoran Seri/Video]: Anti-Leakage Saat Ini Hanya Berbasis Hash File Identik (SHA-256)
- **Lokasi**: `tools/merge_datasets.py:84-95, 117-122`.
- **Analisis Masalah**:
  - `sha256(img)` hanya mendeteksi file yang **100% identik secara byte**. Dalam dataset plat nomor (Roboflow/Kaggle/CCTV), satu kendaraan yang sama sering difoto beberapa frame beruntun atau mengalami kompresi ulang JPEG yang berbeda. Hash SHA-256-nya berbeda, sehingga frame kendaraan yang sama bocor di antara split dan membuat model menghafal kendaraan/latar tertentu.
  - Tanpa **Stratified / Group $K$-Fold Cross-Validation**, model tidak pernah diuji secara merata di seluruh distribusi sumber data (`plat-nomor`, `rf_`, `kg_`, `mg_`) dan kelas ukuran bbox (plat motor kecil vs plat mobil dekat).

### 🟡 `TRAIN-4` [Medium — Domain Gap antara Dataset Siang/Statis vs Kamera Gate Nyata]: Kurangnya Augmentasi Spesifik Gate (Perspective, Motion Blur, Moiré, Low-Light, Glare)
- **Lokasi**: `plat-nomor/a_YOLOv11n.ipynb:349, 698-710`.
- **Analisis Masalah**:
  - Di notebook training saat ini, `perspective=0.0` dan `shear=0.0` dimatikan (`0.0`), serta augmentasi Albumentations berjalan dengan probabilitas sangat kecil (`p=0.01` untuk `Blur`, `MedianBlur`, `ToGray`, `CLAHE`).
  - Padahal di lapangan (dan saat demo webcam menyorot layar/kertas), degradasi utama adalah **sudut kemiringan perspektif kamera gate**, **motion blur kendaraan bergerak**, **silau lampu (glare)**, dan **pola moiré monitor**. Karena model jarang melihat distorsi tersebut saat training (`p=0.01`), bbox prediksi pada kondisi nyata menjadi kurang presisi (terlalu sempit/memotong huruf prefix atau terlalu lebar menelan bumper).

---

### 4.1 Desain Implementasi Cross-Validation ($K$-Fold) & Generalization yang Dapat Diterapkan

Berikut adalah strategi konkret yang **100% kompatibel dengan pipeline Ultralytics YOLO** di proyek ini:

#### A. Stratified Group $K$-Fold Cross-Validation ($K=5$)
Alih-alih menggunakan split statis `3.982 / 84 / 84`, gabungkan pool data berlabel (~4.150 gambar) lalu bagi menjadi **$K=5$ Fold (~830 gambar val per fold, ~3.320 gambar train per fold)**:
1. **Pengelompokan Anti-Leakage Visual (*Perceptual Hash / pHash* + Prefix Nomor Plat)**:
   - Hitung *average/perceptual hash* (`dHash` 64-bit dengan OpenCV: resize grayscale ke `9×8`, bandingkan piksel bertetangga `img[:, 1:] > img[:, :-1]`) untuk mengelompokkan frame-frame CCTV yang mirip/berurutan ke dalam satu `group_id` yang sama.
   - Semua gambar dalam satu `group_id` wajib masuk ke fold yang sama (*GroupKFold*) agar tidak ada kebocoran kendaraan yang sama antara `train` dan `val`.
2. **Stratifikasi Multi-Dimensi (*Stratified Fold*)**:
   - Setiap gambar diberi label strata gabungan berdasarkan:
     - **Sumber domain**: `orig` (`plat-nomor`), `rf` (Roboflow), `kg` (Kaggle COCO), `mg` (Merged), `bg` (Background negatif).
     - **Skala & Rasio Bbox**: `small_plate` (luas bbox < 1,5% frame / motor jauh), `medium_plate`, `large_plate`, dan `two_row_aspect` (rasio $w/h < 2.0$, truk/motor).
   - Dengan `StratifiedGroupKFold(n_splits=5)`, setiap fold validasi (~830 gambar) dijamin mewakili seluruh sumber dataset, kondisi pencahayaan, ukuran plat, dan proporsi background negatif secara seimbang.
3. **Alur Eksekusi 5-Fold di Colab/Kaggle & Ensembling / Pemilihan Model**:
   - Skrip membuat `data_fold_0.yaml` s.d. `data_fold_4.yaml` (cukup berisi daftar path file `.txt` untuk `train_fold_k.txt` dan `val_fold_k.txt` — **tanpa menduplikasi file gambar di disk!**).
   - Latih `YOLOv11n` pada masing-masing fold, lalu evaluasi rata-rata dan standar deviasi:
     $$\text{CV mAP50} = \frac{1}{K}\sum_{k=1}^{K} \text{mAP50}_k \pm \sigma_{\text{mAP50}}$$
   - **Cara Memakai Hasil $K$-Fold di Produksi (Tanpa Menambah Beban CPU)**:
     - *Opsi 1 (Weight Averaging / Model Soup)*: Rata-ratakan bobot state_dict dari $K$ checkpoint terbaik yang berkonvergensi ke basin yang sama, atau gunakan bobot dari fold dengan skor *Out-of-Fold End-to-End OCR Valid Rate* tertinggi, lalu latih ulang final (*refit*) dengan *Cosine Annealing + EMA* menggunakan hiperparameter terbaik hasil CV.
     - *Opsi 2 (Out-of-Fold Hard Sample Mining)*: Gunakan prediksi *Out-of-Fold* (OOF) di seluruh 4.150 gambar untuk menemukan **label noise / anotasi salah** (gambar dengan prediksi OOF tinggi tapi IoU=0 terhadap ground truth, atau sebaliknya) dan perbaiki anotasinya sebelum training final.

#### B. Teknik Peningkatan Generalisasi (*Anti-Degradation*) pada Training YOLO
Untuk mencegah degradasi di paruh akhir epoch (seperti yang terjadi pada Epoch 30–50 di `results.csv`), terapkan parameter dan teknik berikut pada `train_yolo.py` dan notebook Colab/Kaggle:

| Teknik Generalisasi | Parameter / Implementasi | Efek terhadap Degradasi Model |
| :--- | :--- | :--- |
| **1. Geometrik Realistis Gate** | `degrees=7.0`, `shear=2.5`, `perspective=0.0004`, `scale=0.45`, `translate=0.10`, `fliplr=0.0` (tetap `0.0` agar urutan huruf plat kiri-ke-kanan tidak terbalik!) | Membuat detektor tahan terhadap kemiringan sudut kamera CCTV gate dan variasi jarak kendaraan tanpa merusak orientasi teks NRKB. |
| **2. Fotometrik & Cuaca / Malam** | `hsv_h=0.015`, `hsv_s=0.65`, `hsv_v=0.45`, plus Albumentations kustom dengan probabilitas nyata (`p=0.15` untuk `MotionBlur`, `RandomBrightnessContrast`, `ISONoise`, `ImageCompression`, dan simulasi `RandomSunFlare`/glare) | Menutup *domain gap* antara foto dataset siang hari dengan kamera webcam/CCTV malam, hujan, kompresi RTSP, dan pantulan monitor. |
| **3. Regularisasi & Penutupan Mosaic Bertahap** | `weight_decay=0.001` (naikkan dari `0.0005` untuk model besar), `dropout=0.10`, `mosaic=0.8`, `mixup=0.05`, `copy_paste=0.1`, `erasing=0.25`, `close_mosaic=15` | Mencegah lonjakan overfitting saat transisi dari citra Mosaic ke citra utuh di akhir epoch; `erasing=0.25` memaksa model mengenali plat meski sebagian tertutup lumpur/silau. |
| **4. Proporsi Background Negatif (5–10%)** | Tambahkan ±200–350 citra negatif sulit (*hard negatives*: gril mobil, stiker bumper, subtitle layar, marka jalan, kaos bertulisan) ke split `train` **dan** `val` | Mengurangi *false positive* secara drastis dan memastikan metrik validasi menghukum model yang terlalu agresif menebak kotak di latar kosong. |
| **5. Multi-Scale Training & Cosine LR** | `multi_scale=True` (variasi ukuran input `480–800px` tiap batch), `cos_lr=True`, `lrf=0.01`, `warmup_epochs=3.0` | Memastikan model sama akuratnya pada plat motor kecil di kejauhan (CCTV 1 Approach) maupun plat mobil besar di depan palang (CCTV 2 Gate). |
| **6. Freeze Backbone Awal (Transfer Learning Stabil)** | `freeze=10` (bekukan 10 layer backbone pertama pada 5–10 epoch awal atau pada dataset kecil, terutama untuk `YOLOv8x`) | Mencegah *catastrophic forgetting* pada fitur tepi dasar pretrained COCO dan menstabilkan gradien DFL/Box loss. |
| **7. End-to-End OCR Callback sebagai Kriteria Checkpoint** | Evaluasi `valid_format_rate` OCR pada sampel validasi setiap 5 epoch (bukan hanya `mAP50` bbox) | Mengatasi fenomena *Ramadhani dkk. (2026)* di mana bbox dengan mAP tertinggi justru memotong terlalu rapat ke tepi huruf dan menurunkan akurasi OCR. |

---

## 5. Audit Khusus IV: Keamanan & Arsitektur (Verifikasi Remediasi & Residual)

### 4.1 Verifikasi Temuan Audit Pertama (21 Oktober 2026 → 23 November 2026)

| ID | Temuan Awal | Status Kini | Bukti Verifikasi di Kode |
| :--- | :--- | :---: | :--- |
| **C1** | Tidak ada autentikasi/otorisasi di semua endpoint | ✅ **Selesai** | `app/auth.py` + `app/web.py`: `@auth.login_required` di semua route; `@auth.admin_required` pada `/api/settings` (POST) & `/vehicles/*` (POST); password di-hash PBKDF2-HMAC-SHA256 (200.000 iterasi). |
| **C2** | Identitas audit (`override_by`) dikirim dari client | ✅ **Selesai** | `app/web.py:321`: `auth.current_user()` diambil dari sesi server; `log_detail.html:36` menampilkan `<input readonly>`. |
| **C3** | Stored/Reflected XSS via `innerHTML` di `app.js` | ✅ **Selesai** | `app/static/app.js:7-8`: helper `esc()` diterapkan di seluruh interpolasi `renderResult()` dan pesan error. |
| **H1** | JS-context injection pada `onsubmit="confirm(...)"` | ✅ **Selesai** | `app/templates/vehicles.html:67` + `app.js:132-136`: menggunakan atribut `data-confirm` dan event listener JS. |
| **H2** | Signed QR token dilewati oleh branch legacy unsigned | ✅ **Selesai** | `app/sticker.py:25-27, 89-100`: `SGS_REQUIRE_SIGNED_STICKER=1` aktif secara default; menolak semua QR tanpa tanda tangan HMAC-SHA256 `SGS1.*`. |
| **H3** | Test gagal out-of-the-box & path bobot YOLO tidak cocok | ✅ **Selesai** | `tools/fetch_weights.py` menyalin/mengunduh bobot ke `runs/detect/smartgate-colab-v6-*/weights/best.pt`; `test_model_variant` melakukan skip aman bila bobot belum disalin; 102/102 pemeriksaan lulus. |
| **H4** | Gap dokumentasi keamanan vs implementasi | ✅ **Selesai** | `docs/API.md:7-14`, `docs/TECHNICAL.md:309-310`, `docs/DATABASE.md:105` telah diberi catatan status implementasi prototipe vs blueprint produksi. |
| **H5** | Tidak ada proteksi CSRF pada POST/PUT/DELETE | ✅ **Selesai** | `app/web.py:56-59, 129-138`: token CSRF per-sesi (`secrets.compare_digest`) + header `X-CSRF-Token` di semua `fetch()` dan hidden input di semua `<form>`. |
| **M1** | Pertumbuhan folder snapshot tanpa batas | ✅ **Selesai** | `app/service.py:155, 182-190`: `_prune_snapshots()` membatasi folder sesi ke `MAX_SNAPSHOT_SESSIONS = 200`. |
| **M2** | Tidak ada pembatasan konkurensi inferensi | ✅ **Selesai** | `app/service.py:161, 382`: `_INFERENCE_SLOTS = threading.Semaphore(1)` + batas 6 file per upload. |
| **M3** | Dev server tanpa opsi produksi & tanpa security headers | ✅ **Selesai** | `run.py:24, 36-41` (`--prod` dengan Waitress) + `app/web.py:118-127` (CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`). |
| **M4** | `requirements.txt` campur aduk & kurang paket | ✅ **Selesai** | Dipecah menjadi `requirements.txt`, `requirements-ocr.txt`, `requirements-yolo.txt`, dan `requirements-dev.txt`. |
| **M5** | Polling dashboard me-reload seluruh halaman | ✅ **Selesai** | `app/static/app.js:398-435`: patch DOM parsial (`replaceChildren`) + pause otomatis saat tab di background (`visibilitychange`). |
| **M6** | Tabel & navigasi overflow di layar mobile | ✅ **Selesai** | `app/static/style.css:33, 46, 48-49`: `flex-wrap`, `minmax(min(320px, 100%), 1fr)`, `.table-scroll { overflow-x: auto }`. |
| **M7** | Ukuran repositori membengkak karena file biner | ⚠️ **Parsial** | `.gitattributes` sudah melacak `*.pt` dan `*.onnx` via Git LFS, tetapi di root working tree masih terdapat file zip besar (`drive-download-*.zip`, `smartgate-artifacts-*.zip`, `best.pt`, dan `Tugas Citra Digital/prototype/smartgate-dataset-merged.zip`). |
| **L1–L6** | Anotasi `Path`, `ROLE_CHOICES`, touch target 44px, `<meta refresh>`, cache busting, SHA-1 cache key | ✅ **Selesai** | Seluruhnya telah diperbaiki di `web.py`, `style.css`, `training.html`, `base.html`, dan `ocr.py`. |

### 4.2 Temuan Keamanan & Ketahanan Baru (Residual — SELESAI DIIMPLEMENTASIKAN ✅)

- ✅ **`SEC-1` [Low — Brute-Force Login — SELESAI]**: Endpoint `POST /login` (`app/web.py`) kini menerapkan *rate-limiting* berbasis memori per alamat IP (`_LOGIN_FAILURES`, maks `5` gagal dalam jendela `60` detik → HTTP `429`), dan mereset penghitung saat login berhasil.
- ✅ **`SEC-2` [Low — Validasi Server-Side Input Kendaraan — SELESAI]**: Fungsi `_validate_vehicle()` (`app/web.py`) kini memvalidasi `len(plate_number) <= 16`, pola alfanumerik/spasi `^[A-Z0-9 ]+$`, serta `len(sticker_code) <= 64` di sisi server.
- ✅ **`OCR-8` & `OCR-9` [Low — Cleanup Dead Code & Evaluasi Robust — SELESAI]**: Fungsi *dead code* `_enhance_ocr_crop()` di `app/ocr.py` telah dihapus, dan `tools/eval_real.py` telah diperbarui untuk memanggil `ocr.read_plate_robust(image)`.

### 5.3 Verifikasi Implementasi Remediasi Tahap 1 — Pengenalan Plat & Perpol No. 7 Tahun 2021 (23 November 2026)

| ID | Masalah Pengenalan Plat / Huruf / Angka | Status | Implementasi Perbaikan di Kode |
| :--- | :--- | :---: | :--- |
| **`OCR-1`** | `_PREFIX_FIX` memaksa `"L" -> "D"` (merusak plat `L`, `BL`, `DL`) & kode wilayah Papua baru belum ada | ✅ **Selesai** | `app/ocr.py`: `"L": "D"` dihapus dari `_PREFIX_FIX`; fungsi `_fix_prefix()` menjaga prefix yang sudah ada di `VALID_PREFIXES`; ditambahkan `"PG"`, `"PS"`, `"PT"`, `"PY"`. |
| **`OCR-2`** | Digit terakhir pada plat tanpa suffix (`DD1407`, `DD2270`) berubah jadi huruf (`DD140T`, `DD227O`) | ✅ **Selesai** | `app/ocr.py`: `_char_scores()` membedakan prior `_AMBIGUOUS_ALPHA (0.75, 0.55)` vs `_AMBIGUOUS_DIGIT (0.45, 0.80)` sehingga angka murni di ujung kanan tidak berubah jadi huruf. |
| **`OCR-3`** | Plat 2 baris (`B 9012` + `QWE`) berhenti dini (*early-exit*) di baris pertama (`B9012`) | ✅ **Selesai** | `app/ocr.py`: `attempt(..., is_subrow=True)` menahan *early-exit* bila sub-row belum memiliki suffix huruf (`_NO_SUFFIX_PLATE`) dan menggabungkan baris atas + baris bawah (`B9012QWE`). |
| **`OCR-4`** | `snap_to_text_band` memangkas huruf pertama/terakhir pada bbox YOLO | ✅ **Selesai** | `app/pipeline.py` & `app/detect_yolo.py`: opsi `keep_horizontal=True` menjaga lebar horizontal penuh dari bbox YOLO agar huruf tepi tidak terpotong Otsu global. |
| **`OCR-5`** | `_ink_mask` & `_read_template` gagal pada plat hitam bertulisan putih | ✅ **Selesai** | `app/pipeline.py` & `app/ocr.py`: deteksi polaritas otomatis (`if (binary > 0).mean() > 0.55: binary = 255 - binary`) mendukung plat putih, kuning, hijau, merah, dan hitam. |
| **`OCR-6`** | `best_plate_text` membuang `"005877US"` dan `"81234XYZ"` sebelum sempat dikoreksi `normalize_plate` | ✅ **Selesai** | `app/ocr.py`: kandidat panjang `>= 5` yang cocok `_AMBIGUOUS_PREFIX_LEAD` (`^[018]{1,2}[0-9]{1,4}[A-Z]{1,3}$`) diizinkan masuk ke `normalize_plate()`. |
| **`OCR-7`** | Karakter `"A", "4", "T", "7", "L", "D"` belum masuk ke himpunan `_AMBIGUOUS` | ✅ **Selesai** | `app/ocr.py`: `_AMBIGUOUS_ALPHA = frozenset("OQIZSBGTALD")` dan `_AMBIGUOUS_DIGIT = frozenset("01245678")`. |
| **`OCR-10`** | `NUMBER_GROUPS` belum membedakan Polda Metro Jaya (`B`: Mobil `1–2999`, Motor `3000–6999`) vs Umum (`1–1999`, `2000–6999`) & Bus (`7000–7999`) | ✅ **Selesai** | `app/ocr.py`: ditambahkan `NUMBER_GROUPS_METRO` untuk prefix `"B"` dan pemisahan `bus` (`7000–7999`) vs `truck` (`7000–8999`) sesuai Perpol No. 7 Tahun 2021. |
| **`OCR-11`** | 4 digit masa berlaku `MMYY` tanpa pemisah (`0425`, `1228`) lolos `_DATE_LIKE` & `prefix_len=3` masih diizinkan | ✅ **Selesai** | `app/ocr.py`: `_DATE_LIKE` menyaring `(0[1-9]\|1[0-2])[.\-·\s]?\d{2}`; `prefix_len` dibatasi ke `(1, 2)` huruf sesuai kode wilayah resmi Indonesia. |

### 5.4 Verifikasi Implementasi Remediasi Tahap 2 — Optimasi Efisiensi CPU & RAM (23 November 2026)

| ID | Masalah Efisiensi CPU / RAM | Status | Implementasi Perbaikan di Kode |
| :--- | :--- | :---: | :--- |
| **`PERF-1`** | Dual-Framework Memory Bloat (`_paddle_rec_model` + `_paddle_reader` saat warmup, plus fallback otomatis memuat EasyOCR/PyTorch ±1,5 GB ke RAM) | ✅ **Selesai** | `app/config.py` & `app/ocr.py`: `ENABLE_SECONDARY_OCR` (`SGS_ENABLE_SECONDARY_OCR=0` default); `warmup()` hanya memuat `_paddle_rec_model()` dan membiarkan `_paddle_reader()` dimuat *lazy*. |
| **`PERF-2`** | Ledakan jumlah panggilan OCR per frame & duplikasi `zoom 2x` di `_read_paddle()` vs `read_plate_robust()` | ✅ **Selesai** | `app/ocr.py` & `app/service.py`: `allow_internal_zoom=False` saat dipanggil dari tangga `read_plate_robust()`; anggaran keras `MAX_OCR_CALLS_FAST = 2` dan `MAX_OCR_CALLS_FULL = 6` per frame; penghentian dini kandidat kosong (`conf < 0.20`). |
| **`PERF-3`** | `bilateralFilter` frame penuh tidak terpakai, `laplacian_variance` dihitung 2×, `grow_to_text_line` mem-binarisasi seluruh frame HD, & `frame_text_candidate` selalu dijalankan | ✅ **Selesai** | `app/service.py` & `app/pipeline.py`: `preprocess(full=...)` hanya penuh bila `SAVE_PIPELINE_STAGES=1`; `frame_score(..., sharpness=sharpness)` tanpa Laplacian ulang; `grow_to_text_line()` memotong sub-window lokal; `frame_text_candidate()` hanya dipanggil *lazy* saat kandidat detektor utama gagal menghasilkan teks NRKB. |
| **`PERF-4`** | Penulisan 8 file PNG tahap pipeline secara sinkron untuk setiap frame | ✅ **Selesai** | `app/config.py` & `app/service.py`: dikontrol oleh `SAVE_PIPELINE_STAGES` (`SGS_SAVE_PIPELINE_STAGES=0` default); pada mode default hanya menyimpan crop bukti untuk `is_best_frame`. |
| **`PERF-5`** | Alokasi buffer byte sementara pada `crop.tobytes()` dan `source.tobytes()` untuk hashing SHA-1 | ✅ **Selesai** | `app/ocr.py` & `app/service.py`: menggunakan `hashlib.sha1(np.ascontiguousarray(arr))` (zero-copy buffer protocol). |
| **`PERF-6`** | `cv2.setNumThreads` dipanggil puluhan kali per frame & monkey-patch `PaddlePredictorOption` tanpa guard | ✅ **Selesai** | `app/pipeline.py` & `app/ocr.py`: `@lru_cache(maxsize=1)` pada `_cv2()` dan `_np()`; atribut guard `_sgs_patched` pada `PaddlePredictorOption.setdefault_by_model_name`. |
| **`PERF-7`** | `adaptiveThreshold` dihitung 3× berulang di dalam loop `kernel_w` & `_merge_fragments` berisiko $O(N^3)$ | ✅ **Selesai** | `app/pipeline.py`: `adaptiveThreshold` dipindahkan ke luar loop `kernel_w` di `detect_plates_classic()` dan input `_merge_fragments` dibatasi ke `candidates[:30]`. |

### 5.5 Verifikasi Implementasi Remediasi Tahap 3 — 5-Fold Stratified Group CV & Anti-Degradasi Google Colab (23 November 2026)

| ID | Masalah Degradasi Model / Training | Status | Implementasi Perbaikan di Kode & Google Colab |
| :--- | :--- | :---: | :--- |
| **`TRAIN-1`** | Ketimpangan split ekstrem (`3.982 train : 84 val : 84 test`) & validasi hanya dari 1 domain tunggal | ✅ **Selesai** | `tools/prepare_kfold.py` & sel `kfold-prepare` di `plat-nomor/a_YOLOv11n.ipynb` / `a_YOLOv8n.ipynb`: membagi pool `train + valid` (~4.066 citra) menjadi 5 fold seimbang (~3.253 train : ~813 val multi-domain per fold) via manifest portabel `folds/data_fold_{k}.yaml`. |
| **`TRAIN-2`** | Degradasi `val/box_loss` pada paruh akhir epoch (Epoch 30–50) & ketiadaan regularisasi di `train_yolo.py` | ✅ **Selesai** | `train_yolo.py` & notebook Colab (`ANTI_DEGRADATION_HYPS`): memasang `weight_decay=0.001`, `dropout=0.10`, `cos_lr=True`, `lrf=0.01`, `warmup_epochs=3.0`, `close_mosaic=15`, dan opsi `RUN_ALL_FOLDS` untuk menghitung $\text{mAP50}_{\text{CV}} = \mu \pm \sigma$. |
| **`TRAIN-3`** | Anti-leakage hanya berbasis SHA-256 byte identik (frame CCTV berurutan bocor antar-split) | ✅ **Selesai** | `tools/prepare_kfold.py` (`compute_dhash`, `assign_visual_groups`, `stratified_group_kfold_indices`): Union-Find mengelompokkan gambar dengan SHA-256 sama atau jarak Hamming `dHash` 64-bit $\le 4$ ke dalam satu `group_id` yang dijamin tidak pernah terpecah antara `train` dan `val`. |
| **`TRAIN-4`** | Kurangnya augmentasi perspektif, oklusi, dan pencahayaan spesifik kamera gate (`perspective=0.0`, `shear=0.0`) | ✅ **Selesai** | `train_yolo.py` & notebook Colab: `degrees=7.0`, `translate=0.10`, `scale=0.45`, `shear=2.5`, `perspective=0.0004`, `fliplr=0.0` (wajib `0.0`), `erasing=0.25`, `mosaic=0.8`, `mixup=0.05`, `copy_paste=0.10`, `hsv_s=0.65`, `hsv_v=0.45`, serta penyelarasan parser benchmark Colab ke Perpol No. 7 Tahun 2021. |

---

## 6. Rencana Aksi Prioritas (Remediation Roadmap)

### ✅ Tahap 1 (SELESAI — 23 November 2026) — Perbaikan Akurasi Pengenalan Plat, Huruf & Angka Sesuai Perpol No. 7 Tahun 2021 (`app/ocr.py`, `app/pipeline.py`, `app/detect_yolo.py`)
1. **[SELESAI ✅] Tegakkan Struktur Blok & Alokasi Nomor Urut Perpol No. 7 Tahun 2021 (`OCR-10`, `OCR-11`)**:
   - Batasi panjang blok Kode Wilayah (`prefix_len`) menjadi **1 atau 2 alfabet saja** (hapus `prefix_len = 3` karena tidak ada kode wilayah 3 huruf di Indonesia).
   - Tegakkan aturan mutlak: **tidak ada angka di blok alfabet (prefix & suffix) dan tidak ada alfabet di blok angka (nomor urut)**.
   - Perbarui `number_fits_class(text, vehicle_class)` agar membedakan **Polda Metro Jaya (`B`: Mobil Pribadi `1–2999`, Motor `3000–6999`)** dan **Wilayah Umum (Mobil Pribadi `1–1999`, Motor `2000–6999`)**, serta memisahkan **Mobil Bus (`7000–7999`)**, **Mobil Barang (`8000–8999`)**, dan **Kendaraan Khusus (`9000–9999`)**.
   - Saring **4 digit masa berlaku TNKB (`MMYY`: 2 digit awal bulan `01–12`, 2 digit belakang tahun)** baik dengan maupun tanpa karakter pemisah (`^(0[1-9]|1[0-2])[.\-·\s]?\d{2}$`) agar tidak pernah ikut bergabung ke dalam teks plat utama.
2. **[SELESAI ✅] Perbaiki `best_plate_text()` (`OCR-6`)**: Jangan buang kandidat yang diawali angka ambigu (`0`, `8`, `1`) sebelum `normalize_plate()` apabila kandidat memiliki panjang ≥ 5 dan diakhiri huruf (`[A-Z]{1,3}$`), sehingga koreksi `005877US -> DD5877US` dan `81234XYZ -> B1234XYZ` benar-benar bekerja di pipeline OCR nyata.
3. **[SELESAI ✅] Perbaiki `_PREFIX_FIX` & `VALID_PREFIXES` (`OCR-1`)**: Jangan terjemahkan karakter prefix yang **sudah valid** di `VALID_PREFIXES` (hentikan bug `"L" -> "D"` yang merusak semua plat Surabaya `L`, Aceh `BL`, dan Sulut `DL`). Lengkapi `VALID_PREFIXES` dengan kode wilayah terbaru (`PG`, `PS`, `PT`, `PY`).
4. **[SELESAI ✅] Perbaiki Pemisahan Blok & `_AMBIGUOUS` (`OCR-2`, `OCR-7`)**: Pisahkan skor prior huruf vs angka di `_char_scores()` agar digit terakhir pada plat tanpa/gagal baca suffix (`DD1407`, `DD2270`) tidak dipaksa berubah menjadi huruf (`DD140T`, `DD227O`), serta masukkan `A, 4, T, 7, L, D` ke himpunan karakter ambigu kontekstual.
5. **[SELESAI ✅] Perbaiki Plat 2 Baris di `read_plate_robust()` (`OCR-3`)**: Jangan *early-exit* pada potongan baris tunggal yang belum memiliki suffix huruf, dan dukung penggabungan baris atas (prefix+nomor) + baris bawah (seri huruf).
6. **[SELESAI ✅] Dukung Plat Hitam & Jangan Pangkas Horizontal Box YOLO (`OCR-4`, `OCR-5`)**: Buat `_ink_mask()` otomatis mendeteksi polaritas (latar terang vs latar gelap), dan gunakan `keep_horizontal=True` pada `snap_to_text_band` untuk bounding box yang berasal dari YOLO.

### ✅ Tahap 2 (SELESAI — 23 November 2026) — Optimasi Efisiensi CPU & RAM (`app/config.py`, `app/ocr.py`, `app/pipeline.py`, `app/service.py`)
1. **[SELESAI ✅] Hentikan Dual-Runtime Memory Bloat (`PERF-1`)**:
   - Di `ocr.warmup()`, hanya `_paddle_rec_model()` (jalur cepat) yang dipanaskan saat startup agar model rekognisi tidak dimuat ganda bersama `_paddle_reader()`.
   - Fallback lintas-engine (PaddleOCR → EasyOCR/PyTorch) dikontrol melalui variabel lingkungan `SGS_ENABLE_SECONDARY_OCR=0` (default nonaktif) agar satu kegagalan baca tidak memuat PyTorch ±1,5 GB ke RAM secara permanen.
2. **[SELESAI ✅] Batasi Anggaran Panggilan OCR & Hilangkan Zoom Ganda (`PERF-2`)**:
   - Menonaktifkan `zoom 2x` internal (`allow_internal_zoom=False`) di `_read_paddle()` ketika dipanggil dari `read_plate_robust()`, dan membatasi total inferensi OCR maksimal `2` panggilan (`fast=True`) atau `6` panggilan (`fast=False`) per frame.
3. **[SELESAI ✅] Pangkas Operasi Citra Penuh yang Redundan (`PERF-3`, `PERF-4`, `PERF-5`, `PERF-6`, `PERF-7`)**:
   - Menjadikan `frame_text_candidate(image)` *lazy* (hanya dipanggil bila kandidat YOLO/klasik kosong atau gagal menghasilkan teks NRKB).
   - Pada `grow_to_text_line()`, memotong sub-window lokal di sekitar `bbox` sebelum `_ink_mask` / `THRESH_OTSU`.
   - Menghitung `laplacian_variance` cukup 1 kali per frame (`frame_score(..., sharpness=sharpness)`), mencache `_cv2()` / `_np()` dengan `@lru_cache(maxsize=1)`, memindahkan `adaptiveThreshold` ke luar loop `kernel_w` di `detect_plates_classic()`, membatasi `_merge_fragments(candidates[:30])`, serta memakai `hashlib.sha1(np.ascontiguousarray(img))` tanpa `.tobytes()`.

### ✅ Tahap 3 (SELESAI — 23 November 2026) — Penerapan Generalization & $K$-Fold Cross-Validation untuk Google Colab (`tools/prepare_kfold.py`, `train_yolo.py`, `plat-nomor/*.ipynb`)
1. **[SELESAI ✅] Perbaiki Distribusi Split & Terapkan 5-Fold Stratified Group Cross-Validation (`TRAIN-1`, `TRAIN-3`)**:
   - Modul `tools/prepare_kfold.py` dan sel `kfold-prepare` di notebook Google Colab mengelompokkan gambar menggunakan *perceptual hash* (`dHash` 64-bit, jarak Hamming $\le 4$) agar frame berurutan dari kendaraan yang sama tidak bocor antar-fold.
   - Membagi ~4.066 gambar (`train + valid`) secara proporsional lintas sumber (`orig`, `rf`, `kg`, `mg`, `bg`) dan ukuran/rasio bbox menjadi 5 fold (`folds/fold_{k}_train.txt`, `folds/fold_{k}_val.txt`, dan `folds/data_fold_{k}.yaml`) tanpa menduplikasi file gambar di disk.
2. **[SELESAI ✅] Aktifkan Augmentasi Spesifik Gate & Regularisasi Anti-Degradasi (`TRAIN-2`, `TRAIN-4`)**:
   - Menyelaraskan `train_yolo.py` (`--fold` + `ANTI_DEGRADATION_HYPS`) serta notebook Google Colab (`a_YOLOv11n.ipynb` & `a_YOLOv8n.ipynb`) dengan parameter generalisasi penuh (`cos_lr=True`, `degrees=7.0`, `shear=2.5`, `perspective=0.0004`, `scale=0.45`, `hsv_s=0.65`, `hsv_v=0.45`, `erasing=0.25`, `weight_decay=0.001`, `dropout=0.10`, `close_mosaic=15`, `fliplr=0.0`).
   - Memperbarui sel evaluasi benchmark di notebook Colab agar menggunakan aturan Perpol No. 7 Tahun 2021 (bebas bug `L -> D`, mendukung kode wilayah baru `PG/PS/PT/PY`, dan menyaring 4 digit masa berlaku `MMYY`).

### ✅ Tahap 4 (SELESAI — 24 November 2026) — Penutupan 4 Temuan Minor Audit Akhir (`M-1`, `L-1`, `L-2`, `L-3`, `L-4`)
1. **[SELESAI ✅] Pencegahan Artefak `deglare()` pada TNKB Dasar Putih (`M-1`, `app/pipeline.py:184-211`)**:
   - Ambang deteksi *specular glare* dinaikkan menjadi `gray >= 251`, dan `cv2.inpaint(..., INPAINT_TELEA)` kini hanya dijalankan apabila `median(gray) < 175` **dan** proporsi piksel jenuh `0 < glare_ratio <= 0.25`. Papan plat dasar putih (Perpol No. 7 Tahun 2021) tidak lagi ter-inpaint dan tepi karakter tetap tajam.
2. **[SELESAI ✅] Pelestarian Huruf Seri `Q` & Pemisahan Rentang `bus` vs `truck` (`L-1`, `L-2`, `app/ocr.py:45-77`)**:
   - Menghapus pemetaan global `"Q": "O"` dari `_TO_ALPHA` sehingga huruf seri sah NRKB seperti `B 9012 QWE` dan `H 2518 QK` dipertahankan utuh.
   - Memisahkan rentang alokasi nomor urut pada `NUMBER_GROUPS_GENERAL` (`NUMBER_GROUPS`) dan `NUMBER_GROUPS_METRO`: `(7000, 7999, "bus")` khusus Mobil Bus dan `(8000, 8999, "truck")` khusus Mobil Barang sesuai Perpol No. 7 Tahun 2021.
3. **[SELESAI ✅] Fail-Safe `db.settings()` di `evaluate()` (`L-3`, `app/service.py:409-461`)**:
   - Membungkus `thresholds = db.settings()` di dalam `try ... except sqlite3.Error:` dengan fallback aman ke `dict(config.DEFAULTS)` dan `db_available = False` agar gangguan SQLite saat cache kosong tidak pernah melempar *unhandled exception* maupun memicu `AUTO_OPEN`.
4. **[SELESAI ✅] Runner ONNX Murni (`best.onnx`) & Perbaikan Konflik DLL Windows `torch\lib\shm.dll` (`L-4`, `app/config.py`, `app/detect_yolo.py`, `app/ocr.py`)**:
   - Menambahkan `_OnnxYoloRunner` yang menjalankan `best.onnx` (`runs/detect/smartgate-colab-v6-*/weights/best.onnx` dan `smartgate-artifacts-*/best.onnx`) secara murni melalui `onnxruntime` atau `cv2.dnn.readNetFromONNX` bawaan OpenCV (`SGS_USE_ONNX=1` default) **tanpa mengimpor `torch` maupun `ultralytics`**, serta fallback aman (`except (ImportError, OSError)`) ke `.pt`.
   - Memuat `paddlex` sebelum `import paddle` di `_configure_paddle_cpu()` (`app/ocr.py:368-398`) untuk menghilangkan konflik DLL Windows `[WinError 127] torch\lib\shm.dll` dan `RuntimeError: PDX has already been initialized`.
5. **Verifikasi Otomatis Akhir**: Seluruh **`151 pemeriksaan`** di `tests/test_pipeline.py` (termasuk pengujian nyata `plat-nomor/test` dengan `backend=paddleocr` + `opencv-dnn-onnx`, serta regresi `M-1`, `L-1`, `L-2`, `L-3`, `L-4`) lulus 100%.

### ✅ Tahap 5 (SELESAI — 27 November 2026) — Sistem Log Terpadu, RBAC 4 Peran & Audit UI/UX Frontend (`UI-1` s.d. `UI-6`)
- Implementasi penuh log kendaraan terpadu (`gate_logs` 10 kolom baru, `vehicle_bookings`, pairing otomatis `IN`↔`OUT` + `dwell_minutes`, RBAC `admin`/`satpam`/`hrga`/`beacukai`, serta ekspor CSV UTF-8 BOM).
- Audit & perbaikan menyeluruh UI/UX Frontend terdokumentasi lengkap di [`AUDIT_UI_UX_FRONTEND.md`](AUDIT_UI_UX_FRONTEND.md): target sentuh ≥ 44px, sel bertingkat `.cell-stack` + `.table-scroll` (bebas overflow 360px & 1366px), panel kategori CSP-safe `.is-hidden`, penghapusan seluruh inline `style="..."` sehingga CSP diperketat menjadi `style-src 'self'`, serta konsistensi RBAC visual.
- **Verifikasi Akhir**: **`170/170` pemeriksaan otomatis** di `tests/test_pipeline.py` lulus 100%.


