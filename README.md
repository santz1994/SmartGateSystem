# Smart Gate System

Sistem gerbang otomatis berbasis pengenalan plat nomor Indonesia (**ALPR / ANPR**): menggunakan **YOLOv8 / YOLOv11** untuk deteksi plat nomor, **PaddleOCR / EasyOCR** dengan parser struktur **TNKB & NRKB sesuai Peraturan Kepolisian (Perpol) Nomor 7 Tahun 2021** untuk pengenalan karakter (kode wilayah, nomor urut registrasi, seri huruf akhir, dan pemisahan 4 digit masa berlaku `MMYY`), serta logika keputusan **fail-safe** (tidak pernah melakukan `AUTO_OPEN` saat komponen kritis gagal atau keyakinan di bawah ambang).

Hasil OCR yang melanggar tata bahasa plat Indonesia ditolak keras (dianggap tidak terbaca dan dialihkan ke satpam), sementara distraktor visual seperti subtitle video, layar monitor, atau blok warna disaring melalui *plate border score* dan *glyph plausibility gate*. Fitur stiker QR bertanda tangan kriptografis (`SGS1.*`) disertakan sebagai penguat bukti (*confidence fusion*), sedangkan integrasi RFID & mikrokontroler ESP32 disiapkan dalam spesifikasi arsitektur produksi ([`docs/`](docs/)).

---

## Struktur Repositori

| Path | Isi & Peran |
| :--- | :--- |
| [`docs/`](docs/) | Seluruh dokumentasi & laporan (`.md`) + daftar pustaka Mendeley: [PRD](docs/PRD.md), [TECHNICAL](docs/TECHNICAL.md), [SYSTEM_FLOW](docs/SYSTEM_FLOW.md), [API](docs/API.md), [DATABASE](docs/DATABASE.md), [PRESENTASI](docs/PRESENTASI.md), [LAPORAN_KP_TEMUAN](docs/LAPORAN_KP_TEMUAN.md), [TUGAS_PENGOLAHAN_CITRA_DIGITAL](docs/TUGAS_PENGOLAHAN_CITRA_DIGITAL.md), [TRAINING_GUIDE](docs/TRAINING_GUIDE.md), [SmartGateSystem-audit-report](docs/SmartGateSystem-audit-report.md), [AUDIT_FULL_CODE_ML](docs/AUDIT_FULL_CODE_ML.md), dan [AUDIT_UI_UX_FRONTEND](docs/AUDIT_UI_UX_FRONTEND.md) |
| [`Tugas Citra Digital/prototype/`](Tugas%20Citra%20Digital/prototype/) | **Aplikasi utama (Flask Prototype)**: pipeline pengolahan citra, detektor YOLO/OpenCV, engine OCR + normalisasi NRKB, dashboard satpam, kamera live, dan test suite |
| `smartgate-artifacts-*/` | Artefak hasil training Colab/Kaggle (`best.pt`, `best.onnx`, `evaluation_summary.json`, `results.csv`, `confusion_matrix.png`) untuk YOLOv8n dan YOLOv11n |

---

## Menjalankan Aplikasi (Prototype)

```powershell
cd "Tugas Citra Digital/prototype"

# 1. Pasang dependensi inti + backend OCR default (PaddleOCR)
pip install -r requirements.txt

# 2. (Opsional tapi disarankan) Pasang runtime deteksi YOLO
pip install -r requirements-yolo.txt

# 3. Salin/unduh bobot YOLO ke runs/detect/smartgate-colab-v6-*/weights/best.pt
python tools\fetch_weights.py

# 4. Jalankan server (development atau produksi via Waitress)
python run.py
# atau mode produksi:
python run.py --prod --host 127.0.0.1 --port 5000
```

Buka `http://localhost:5000` dan login terlebih dahulu (seluruh halaman dan endpoint `/api/*` dilindungi autentikasi sesi + RBAC + CSRF):
- **Admin**: `admin` / `admin123` (akses penuh: pengaturan model/ambang `/api/settings`, `/training`, CRUD master kendaraan `/vehicles`, jadwal `/bookings`, dan seluruh log audit)
- **Satpam**: `satpam1` / `satpam123` (dashboard live, kamera, foto manual, simulasi, pencatatan log keluar-masuk `IN`/`OUT`, `MANUAL_OVERRIDE` / `REJECTED`, dan lihat log)
- **HRGA**: `hrga1` / `hrga123` (*read-only* pada log audit & master kendaraan, manajemen jadwal/izin kendaraan `/bookings`, serta ekspor CSV laporan; ditolak 403 dari kontrol gerbang & pengaturan AI)
- **Bea Cukai**: `beacukai1` / `beacukai123` (*read-only* khusus pengawasan logistik/kepabeanan — default terfilter `CARGO_LOGISTIC` — melihat snapshot bukti plat & dokumen BC, serta ekspor CSV; ditolak 403 dari seluruh aksi mutasi)

> **Keamanan Kredensial**: Ganti password default sebelum menjalankan di jaringan lokal dengan mengatur variabel lingkungan `SGS_ADMIN_PASSWORD`, `SGS_SATPAM_PASSWORD`, `SGS_HRGA_PASSWORD`, `SGS_BEACUKAI_PASSWORD`, dan `SGS_SECRET_KEY`, lalu jalankan `python run.py --reset-db`.

### Sistem Log Kendaraan Terpadu & Kepatuhan (Satpam, HRGA, Bea Cukai)
- **Pairing Otomatis `IN` ↔ `OUT` & Durasi Kunjungan (`dwell_minutes`)**: Setiap log `OUT` otomatis dipasangkan ke log `IN` terbuka terbaru dengan plat sama dan menghitung durasi kunjungan (`paired_log_id`, `dwell_minutes`).
- **Klasifikasi Kunjungan & Dokumen Pabean**: Mendukung kategori `COMPANY_CAR`, `EMPLOYEE`, `CARGO_LOGISTIC`, dan `GUEST`, lengkap dengan jenis dokumen (`BC 2.3`, `BC 2.5`, `BC 2.7`, `BC 4.0`, `BC 4.1`, `SURAT_JALAN`), nomor dokumen/aju, dan nomor segel (*seal*).
- **Penjadwalan Kendaraan (`vehicle_bookings`)**: Jadwal aktif dari HRGA otomatis mengisi metadata kategori, tujuan/PIC, dan nomor dokumen BC ke `gate_logs` saat kendaraan dipindai di gerbang.
- **Ekspor Laporan Excel-Ready**: Endpoint `GET /api/logs/export.csv` menghasilkan berkas CSV UTF-8 dengan BOM sesuai filter aktif (`q`, `direction`, `visit_category`, `status=UNCLOSED_IN`, `bc_doc_type`, `date_from`, `date_to`). Lihat rincian perubahan di [`CHANGELOG.md`](CHANGELOG.md).

---

## Arsitektur Pengenalan Plat, Huruf, dan Angka (ALPR Pipeline)

Pipeline pengenalan dirancang berlapis di [`app/pipeline.py`](Tugas%20Citra%20Digital/prototype/app/pipeline.py), [`app/detect_yolo.py`](Tugas%20Citra%20Digital/prototype/app/detect_yolo.py), [`app/ocr.py`](Tugas%20Citra%20Digital/prototype/app/ocr.py), dan [`app/fusion.py`](Tugas%20Citra%20Digital/prototype/app/fusion.py):

1. **Seleksi Spasial & ROI Gerbang (`detection_roi` & `filter_gate_zone`)**:
   - Memotong area atas frame kamera lebar (`SGS_DETECTION_ROI=0.05,0.35,0.95,1.0`) sebelum pra-pemrosesan agar wajah/jaket/latar atas tidak memicu false positive dan menghemat komputasi CPU.
   - Menyaring kandidat di luar zona gerbang dan memilih kendaraan terdekat kamera.
2. **Deteksi Plat & Gerbang Kualitas Visual (`detect_plates`)**:
   - Menggunakan model YOLO aktif (`yolo11n` / `yolov8n`) dengan fallback detektor morfologi-kontur OpenCV klasik.
   - Setiap kandidat wajib lolos *geometry gate* (rasio aspek & proporsi luas), *texture gate* (tepi Canny pada kanal LAB), *plate border score* (bingkai gelap mengelilingi bidang plat untuk menolak subtitle/video), serta *glyph plausibility* (jumlah karakter minimum per baris sesuai profil kelas kendaraan di `app/vehicles.py`).
3. **Penyempitan Pita Teks & Restorasi Crop (`snap_to_text_band`, `pad_crop`, `enhance_plate`, `deglare`)**:
   - Memangkas bodi/lampu dari kandidat plat, mengembalikan margin tepi (`pad_crop`) agar lengan huruf seperti `Y`, `G`, `4` tidak terpotong, serta menerapkan median blur 3×3 (anti-moiré monitor), CLAHE, penutupan morfologi, dan *unsharp mask* pada saat retry.
4. **Pengenalan Karakter & Koreksi Struktur NRKB (`read_plate_robust`, `normalize_plate`, `best_plate_text`)**:
   - **Jalur Cepat (Recognizer-Only)**: Memakai `PP-OCRv6_medium_rec` langsung pada pita teks plat tanpa *text detector* (~6× lebih cepat di CPU), dengan verifikasi silang zoom 2× pada tingkat keyakinan menengah.
   - **Pemisahan 4 Digit Masa Berlaku (`MMYY`)**: Memisahkan baris bawah / 4 digit angka masa berlaku TNKB (2 digit awal bulan `01–12`, 2 digit belakang tahun, mis. `12·28`, `04 27`) dari baris nomor plat utama.
   - **Disambiguasi Huruf vs Angka Berbasis Blok (Perpol No. 7 Tahun 2021)**: Memecah string ke struktur `[Kode Wilayah 1–2 Huruf] [Nomor Urut 1–4 Angka] [Seri Akhir 1–3 Huruf]` dengan aturan mutlak **tidak ada angka pada blok alfabet dan tidak ada alfabet pada blok angka**. Sengketa karakter mirip (`B/8`, `D/0/O`, `I/1/L`, `S/5`, `G/6`, `Z/2`, `T/7`, `A/4`, `Q/O`) diputus sesuai posisinya di blok huruf atau blok angka, divalidasi terhadap daftar kode wilayah `VALID_PREFIXES` dan alokasi nomor urut registrasi (Umum vs Polda Metro Jaya).
   - **Hard Gate & Multi-Frame Voting (`vote_plate`)**: Teks yang tetap melanggar format NRKB (mis. nomor diawali `0` atau tanpa kode wilayah huruf) ditolak sebagai `OCR_FAILED`; pada sesi multi-frame, voting mayoritas berbobot kamera gate (`2.0×`) menentukan hasil akhir.

### Aturan Pembacaan TNKB & NRKB (Peraturan Kepolisian Nomor 7 Tahun 2021)

Sistem menegakkan aturan identifikasi plat nomor kendaraan Indonesia mengacu pada **Perpol Nomor 7 Tahun 2021** tentang Registrasi dan Identifikasi Kendaraan Bermotor:

1. **Pola Struktur Karakter TNKB**:
   - Struktur baku terdiri atas 3 blok: **`[Kode Wilayah (Alfabet)] [Nomor Urut (1–4 Angka)] [Seri Akhir (Alfabet)]`**.
   - Kombinasi yang sah mengikuti alokasi daerah Polda masing-masing:
     - **Kode Wilayah 1 Huruf**: `[A] [9999] [AAA]`, `[A] [9999] [AA]`, atau `[A] [9999] [A]` (contoh: `B 1234 XYZ`, `D 1234 AB`, `L 1234 A` — dengan nomor urut 1 s.d. 4 digit angka).
     - **Kode Wilayah 2 Huruf**: `[AA] [9999] [A]`, `[AA] [9999] [AA]`, atau `[AA] [9999] [AAA]` (contoh: `DD 1234 A`, `DD 1234 AB`, `DD 2760 XCL`, `KT 1234 AB`).
2. **Pemisahan Mutlak Alfabet dan Angka**:
   - **Tidak pernah ada angka pada blok alfabet** (kode wilayah & seri akhir) dan **tidak pernah ada alfabet pada blok angka** (nomor urut).
   - Digit pertama nomor urut tidak pernah diawali angka `0` (`1–9999`).
3. **Alokasi Nomor Urut Registrasi Berdasarkan Jenis Kendaraan (Umum vs Polda Metro Jaya)**:

   | Jenis Kendaraan | Wilayah Umum (Non-Metro Jaya) | Wilayah Polda Metro Jaya (Kode `B`) |
   | :--- | :---: | :---: |
   | **Mobil Penumpang / Pribadi** | **`1 – 1999`** | **`1 – 2999`** |
   | **Sepeda Motor** | **`2000 – 6999`** | **`3000 – 6999`** |
   | **Mobil Bus** | **`7000 – 7999`** | **`7000 – 7999`** |
   | **Mobil Barang (Truk / Pick-up)** | **`8000 – 8999`** | **`8000 – 8999`** |
   | **Kendaraan Khusus** | **`9000 – 9999`** | **`9000 – 9999`** |

4. **4 Digit Angka Masa Berlaku di Bawah TNKB (`MMYY`)**:
   - Empat digit angka kecil di bagian bawah TNKB adalah **tanggal masa berlaku (5 tahunan)**: **2 digit awal adalah Bulan (`01`–`12`)** dan **2 digit belakang adalah Tahun (mis. `26`–`31`)**.
   - Baris atau token 4 digit `MMYY` ini disaring agar tidak pernah dianggap sebagai nomor plat maupun tergabung menjadi seri huruf akhir.
5. **Ukuran Fisik, Warna Dasar, dan Toleransi Gambar Bergerak**:
   - **Warna Dasar (Pasal 45 Perpol 7/2021)**: Putih tulisan hitam (perseorangan/badan hukum), Kuning tulisan hitam (angkutan umum), Merah tulisan putih (instansi pemerintah), Hijau tulisan hitam (kawasan perdagangan bebas / FTZ), ditambah lis biru untuk kendaraan listrik (EV), serta dukungan masa transisi plat lama Hitam tulisan putih.
   - **Toleransi Ukuran pada Gambar Bergerak**: Ukuran fisik plat roda 4 (`±430–460 × 130–135 mm`, rasio ideal $\approx 3,26–3,54$; atau 2 baris rasio $\approx 1,77$) dan roda 2 (`±250–275 × 105–110 mm`, rasio ideal $\approx 2,38–2,50$) mengalami distorsi perspektif (*foreshortening*), perubahan skala jarak, dan *motion blur* saat kendaraan bergerak melewati kamera. Oleh karena itu, rasio dan ukuran piksel digunakan sebagai **patokan luwes (*soft prior* & rentang filter `1,20–5,00`)** yang dipadukan dengan golongan nomor urut kendaraan, bukan sebagai pemutus tunggal yang kaku.

---

## Perbandingan Model Detektor (v6 Multi-Domain Fold 0 — Runtime-Switchable)

Kedua model dilatih dengan protokol **5-Fold Stratified Group Cross-Validation (Fold 0: ~3.253 train : ~813 val multi-domain, anti-leakage `dHash` 64-bit + SHA-256)** dan regularisasi anti-degradasi selama 50 epoch di Google Colab GPU T4. Bobot ditempatkan di `runs/detect/smartgate-colab-v6-yolo11n/weights/best.pt` dan `runs/detect/smartgate-colab-v6-yolov8n/weights/best.pt` serta dapat diganti langsung saat runtime dari halaman **`/training`**:

| Metrik Evaluasi | YOLOv8n (`smartgate-colab-v6-yolov8n`) | YOLOv11n (`smartgate-colab-v6-yolo11n`) |
| :--- | ---: | ---: |
| **Validation Fold 0 mAP50** *(multi-domain)* | **0,8488** | 0,8464 |
| **Validation Fold 0 mAP50-95** *(multi-domain)* | 0,5669 | **0,5686** |
| **Test Hold-out mAP50** *(84 citra)* | 0,9617 | **0,9693** |
| **Test Hold-out mAP50-95** *(84 citra)* | 0,5931 | **0,6150** |
| **End-to-End OCR Valid Format Rate** | **75,96% (79/104)** | 74,07% (80/108) |
| **Latency End-to-End Rata-rata / P95** | **76,50 ms / 157,19 ms** | 87,43 ms / 161,03 ms |
| **Ukuran Bobot `best.pt` / `best.onnx`** | 6,48 MB / 12,77 MB | **5,48 MB / 10,66 MB** |

### Strategi Generalisasi & Cross-Validation (Mitigasi Degradasi Model)

Untuk mengatasi fenomena *model degradation* (penurunan akurasi pada kamera nyata / overfitting di paruh akhir epoch akibat ketimpangan split `3.982 train : 84 val : 84 test`), pipeline pelatihan mendukung peningkatan **Generalization** dan **Cross-Validation** berikut (detail analisis di [`docs/SmartGateSystem-audit-report.md`](docs/SmartGateSystem-audit-report.md#4-audit-khusus-iii-degradasi-model-training-generalisasi--cross-validation) dan panduan teknis di [`docs/TRAINING_GUIDE.md`](docs/TRAINING_GUIDE.md)):

1. **5-Fold Stratified Group Cross-Validation (`K=5`)**:
   - Mengelompokkan gambar dengan *perceptual hash* (`dHash` 64-bit) agar frame berurutan dari kendaraan yang sama tidak bocor antar-fold (*GroupKFold*), sekaligus menjaga proporsi sumber domain (`plat-nomor`, `rf_`, `kg_`, `mg_`, `bg_`) dan skala ukuran bbox plat di setiap fold (~830 gambar validasi multi-domain per fold).
   - Memungkinkan *Out-of-Fold (OOF) Hard Sample & Label Noise Mining* untuk membersihkan anotasi yang meleset sebelum *refit* model final.
2. **Regularisasi & Augmentasi Spesifik Gate (Anti-Degradasi)**:
   - **Geometrik Perspektif Tanpa Flip Horizontal**: `degrees=7.0`, `shear=2.5`, `perspective=0.0004`, `scale=0.45`, dan **`fliplr=0.0`** (wajib `0.0` agar urutan karakter plat tidak terbalik cermin).
   - **Ketahanan Oklusi, Cuaca & Layar**: `erasing=0.25` (Random Erasing agar tahan silau/kotoran), `hsv_s=0.65`, `hsv_v=0.45`, `mosaic=0.8`, `mixup=0.05`, `close_mosaic=15`, `weight_decay=0.001`, serta `multi_scale=True` + `cos_lr=True`.
   - **Hard-Negative Background (5–10%) & Seleksi Berbasis OCR**: Menambahkan gambar negatif sulit (gril, bumper, subtitle video, marka jalan) ke split `train` & `val`, serta mengevaluasi *End-to-End Valid Format OCR Rate* saat memilih checkpoint `best.pt`.

---

## Efisiensi Penggunaan CPU & RAM serta Konfigurasi

Pada perangkat CPU standar tanpa GPU diskrit (diuji pada Intel Core i5-8250U, 4C/8T, RAM 12 GB — lihat [`docs/LAPORAN_KP_TEMUAN.md`](docs/LAPORAN_KP_TEMUAN.md)), aplikasi menerapkan pengendalian sumber daya berikut:

- **Pembatasan Thread Inferensi (`SGS_CPU_THREADS`)**: Membatasi thread pool OpenMP, MKL, OpenBLAS, PyTorch, OpenCV, dan Paddle ke setengah core logis (`OMP_WAIT_POLICY=PASSIVE`) agar thread pool tidak saling berebut CPU. Pemakaian CPU saat scan turun dari ~90–96% menjadi **±53%**.
- **Jalur Cepat vs Jalur Penuh (`fast=1` vs `fast=0`)**:
  - *Auto Scan Kamera* (`fast=1`, `persist=0`) mengambil 1 frame, melewati bilateral filter frame penuh, menggunakan recognizer-only, dan membatasi percobaan retry → latensi **±1,4 detik/scan**.
  - *Scan & Simpan Log* (`fast=0`, `persist=1`) mengambil 3 frame berurutan untuk voting mayoritas, menjalankan tangga retry lengkap, dan menyimpan bukti audit → latensi **±5 detik**.
- **Semaphore Inferensi (`SGS_MAX_CONCURRENT_INFER=1`)**: Mencegah antrean request paralel melumpuhkan CPU/RAM.
- **Warmup Satu Backend & Rotasi Snapshot**: Hanya memanaskan backend OCR utama saat startup (RAM proses stabil di **±1,2 GB RSS** selama backend sekunder tidak dipicu) dan membatasi direktori snapshot ke `MAX_SNAPSHOT_SESSIONS = 200`.

### Ringkasan Temuan Audit & Status Remediasi Terbaru (23 November 2026)

Detail lengkap hasil pengecekan menyeluruh terhadap efisiensi CPU/RAM, akurasi pengenalan plat/huruf/angka, serta strategi pelatihan model terdokumentasi di **[`docs/SmartGateSystem-audit-report.md`](docs/SmartGateSystem-audit-report.md)**:

1. **[SELESAI DIIMPLEMENTASIKAN ✅] Fungsi Pengenalan Plat, Huruf & Angka Sesuai Perpol No. 7 Tahun 2021 (`OCR-1` s.d. `OCR-7`, `OCR-10`, `OCR-11`)**:
   - **Bebas Bias Wilayah (`OCR-1`)**: Menghapus pemetaan `"L" -> "D"` pada `_PREFIX_FIX` dan menjaga kode wilayah yang sudah terdaftar di `VALID_PREFIXES` (plat Surabaya `L`, Aceh `BL`, dan Sulut `DL` tidak lagi berubah menjadi `D`, `BD`, `DD`), serta menambahkan kode wilayah Papua baru (`PG`, `PS`, `PT`, `PY`).
   - **Struktur Blok & Alokasi Nomor Urut Perpol 7/2021 (`OCR-2`, `OCR-7`, `OCR-10`)**: Membatasi kode wilayah ke `1–2` huruf, membedakan prior skor huruf vs angka pada `_char_scores()` agar plat tanpa suffix (`DD1407`, `DD2270`) tidak berubah menjadi huruf (`DD140T`, `DD227O`), serta menerapkan alokasi khusus **Polda Metro Jaya (`B`: Mobil `1–2999`, Motor `3000–6999`)** vs **Wilayah Umum (Mobil `1–1999`, Motor `2000–6999`)** dan pemisahan Bus (`7000–7999`) vs Barang (`8000–8999`).
   - **Penyaringan 4 Digit Masa Berlaku `MMYY` Tanpa Pemisah (`OCR-11`)**: Menyaring token bulan+tahun baik dengan pemisah maupun 4 digit rapat (`0425`, `1228`) lewat `_DATE_LIKE`.
   - **Penyelamatan Awalan Angka Ambigu (`OCR-6`)**: Mengizinkan kandidat panjang `>= 5` berawalan `0/1/8` dan berakhiran huruf seri masuk ke `normalize_plate()` di `best_plate_text()`, sehingga `"005877US" -> "DD5877US"` dan `"81234XYZ" -> "B1234XYZ"` bekerja penuh di jalur OCR nyata.
   - **Penggabungan Plat 2 Baris (`OCR-3`)**: Menahan *early-exit* pada potongan sub-baris pertama yang belum memiliki seri huruf dan menggabungkan baris atas (`B 9012`) + baris bawah (`QWE`) menjadi `"B9012QWE"`.
   - **Dukungan Plat Hitam & Perlindungan Tepi Horizontal YOLO (`OCR-4`, `OCR-5`)**: Deteksi polaritas otomatis di `_ink_mask()` dan `_read_template()` untuk plat dasar hitam tulisan putih, serta `keep_horizontal=True` pada `snap_to_text_band()` di `app/detect_yolo.py`.
2. **[SELESAI DIIMPLEMENTASIKAN ✅] Efisiensi RAM & CPU (`PERF-1` s.d. `PERF-7`)**:
   - **Pencegahan Dual-Framework Memory Bloat (`PERF-1`)**: `ocr.warmup()` hanya memuat `_paddle_rec_model()` saat startup (tanpa menduplikasi `_paddle_reader()`), dan fallback lintas-framework ke EasyOCR/PyTorch dikontrol lewat `SGS_ENABLE_SECONDARY_OCR=0` (default nonaktif) agar proses tetap hemat di **±1,2 GB RSS** dan tidak membengkak ke ±3,5 GB saat ada frame gagal baca.
   - **Anggaran Panggilan OCR & Penghapusan Zoom Ganda (`PERF-2`)**: Menerapkan *hard budget* inferensi OCR per frame (`MAX_OCR_CALLS_FAST = 2`, `MAX_OCR_CALLS_FULL = 6`), menghentikan evaluasi view cadangan pada kandidat kosong (`conf < 0.20`), serta menonaktifkan `zoom 2x` internal di `_read_paddle()` saat dipanggil dari tangga retry `read_plate_robust()`.
   - **Pemangkasan Operasi Citra Penuh Redundan (`PERF-3`, `PERF-4`)**: Melewati `bilateralFilter` + CLAHE resolusi penuh kecuali `SGS_SAVE_PIPELINE_STAGES=1` diaktifkan; meneruskan `sharpness` pra-hitung ke `frame_score()`; memotong sub-window lokal pada `grow_to_text_line()` sebelum Otsu thresholding; serta memanggil `frame_text_candidate()` secara *lazy* hanya bila kandidat detektor utama gagal menghasilkan teks NRKB.
   - **Zero-Copy Hashing & Optimasi Detektor Klasik (`PERF-5`, `PERF-6`, `PERF-7`)**: Menggunakan `hashlib.sha1(np.ascontiguousarray(arr))` tanpa `.tobytes()`, mencache `_cv2()` dengan `@lru_cache(maxsize=1)`, mengeluarkan `adaptiveThreshold` dari loop `kernel_w` di `detect_plates_classic()`, dan membatasi input `_merge_fragments(candidates[:30])`.
3. **[SELESAI DIIMPLEMENTASIKAN ✅] Generalisasi Model & 5-Fold Cross-Validation untuk Google Colab (`TRAIN-1` s.d. `TRAIN-4`)**:
   - **Modul Pembagi Dataset `tools/prepare_kfold.py` (`TRAIN-1`, `TRAIN-3`)**: Mengelompokkan frame berurutan dari kendaraan yang sama menggunakan *perceptual hash* (`dHash` 64-bit, jarak Hamming $\le 4$) + `SHA-256` ke dalam satu `group_id` (*GroupKFold*), lalu membagi pool dataset secara berstrata lintas sumber domain (`orig`, `rf`, `kg`, `mg`, `bg`), skala luas bbox, dan rasio aspek menjadi 5 fold portabel (`folds/data_fold_0.yaml` s.d. `data_fold_4.yaml`) tanpa menduplikasi file gambar.
   - **Notebook Google Colab & `train_yolo.py` Anti-Degradasi (`TRAIN-2`, `TRAIN-4`)**: Notebook [`plat-nomor/a_YOLOv11n.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a_YOLOv11n.ipynb), [`plat-nomor/a_YOLOv8n.ipynb`](Tugas%20Citra%20Digital/prototype/plat-nomor/a_YOLOv8n.ipynb), dan [`train_yolo.py`](Tugas%20Citra%20Digital/prototype/train_yolo.py) telah dilengkapi sel pembentukan 5-Fold CV otomatis, opsi `RUN_ALL_FOLDS = True/False` ($\text{mAP50}_{\text{CV}} = \mu \pm \sigma$), hiperparameter `ANTI_DEGRADATION_HYPS` (`weight_decay=0.001`, `dropout=0.10`, `degrees=7.0`, `shear=2.5`, `perspective=0.0004`, `erasing=0.25`, `close_mosaic=15`, `fliplr=0.0`), serta benchmark OCR Perpol No. 7 Tahun 2021.

### Variabel Lingkungan Utama

| Variabel | Default | Fungsi |
| :--- | :--- | :--- |
| `SGS_SECRET_KEY` | `(auto file)` | Kunci kriptografi sesi Flask (wajib diisi 32+ byte acak di produksi) |
| `SGS_ADMIN_PASSWORD` / `SGS_SATPAM_PASSWORD` | `admin123` / `satpam123` | Password akun seed `admin` & `satpam1` saat `init_db` / `--reset-db` |
| `SGS_HRGA_PASSWORD` / `SGS_BEACUKAI_PASSWORD` | `hrga123` / `beacukai123` | Password akun seed `hrga1` & `beacukai1` saat `init_db` / `--reset-db` |
| `SGS_OCR_BACKEND` | `paddleocr` | Pilihan mesin OCR utama (`paddleocr`, `easyocr`, `template_match`) |
| `SGS_ENABLE_SECONDARY_OCR` | `0` | Aktifkan (`1`) fallback lintas-engine OCR kedua (default `0` untuk mencegah dual-runtime RAM bloat) |
| `SGS_SAVE_PIPELINE_STAGES` | `0` | Simpan seluruh 8 tahap citra PNG per frame (`1`) untuk laporan, atau hanya crop bukti *best frame* (`0`) |
| `SGS_YOLO_VARIANT` / `SGS_YOLO_WEIGHTS` | `yolov8n` / `(auto)` | Varian model YOLO aktif (`yolov8n`, `yolo11n`) atau path ke `best.onnx` / `best.pt` |
| `SGS_USE_ONNX` | `1` | Prioritaskan runner ONNX murni (`best.onnx` via `onnxruntime` / `cv2.dnn` tanpa memuat PyTorch); set `0` untuk paksa `.pt` |
| `SGS_CPU_THREADS` | `cpu_count // 2` | Batas thread inferensi CPU untuk Paddle, PyTorch, dan OpenCV |
| `SGS_MAX_CONCURRENT_INFER` | `1` | Batas inferensi paralel lintas request HTTP |
| `SGS_DETECTION_ROI` | `0.05,0.35,0.95,1.0` | ROI deteksi bawah untuk frame kamera lebar (`x1,y1,x2,y2`) |
| `SGS_DETECTION_GAMMA` / `SGS_CLAHE_CLIP_LIMIT` | `1.15` / `2.0` | Koreksi eksposur & batas kontras CLAHE pra-deteksi |
| `SGS_REQUIRE_SIGNED_STICKER` | `1` | Wajibkan QR stiker bertanda tangan HMAC-SHA256 (`SGS1.*`) |
| `SGS_STICKER_SIGNING_KEY` | `(kosong)` | Kunci rahasia HMAC (minimal 32 byte) untuk verifikasi & pembuatan QR stiker |
| `SGS_LOG_COOLDOWN_SECONDS` | `60` | Jendela deduplikasi log untuk nomor plat yang sama |

---

## Pengujian & Evaluasi

Jalankan suite pemeriksaan mandiri (**170 pemeriksaan** regresi utama di `tests/test_pipeline.py` tanpa ketergantungan `pytest`):

```powershell
cd "Tugas Citra Digital/prototype"
python tests\test_pipeline.py
```

Suite ini menguji normalisasi karakter NRKB sesuai Perpol No. 7 Tahun 2021 (`B/8`, `I/1/L`, `O/0/D`, `G/6`, `Q/O`, kode wilayah `L`/`BL`/`DL`/`PG`, penyelamatan awalan `005877US -> DD5877US` & `81234XYZ -> B1234XYZ`, perlindungan angka akhir `DD1407` & `DD2270`), kesesuaian golongan nomor kendaraan (Polda Metro Jaya `B` vs Wilayah Umum), penyaringan 4 digit masa berlaku `MMYY` (`0425`, `1228`), penggabungan plat 2 baris (`B 9012` + `QWE` -> `B9012QWE`), pembacaan plat warna dasar hitam bertulisan putih, perlindungan lebar horizontal bbox YOLO (`keep_horizontal=True`), fusi skor & voting multi-kamera, ketahanan moiré layar monitor, penolakan distraktor subtitle/blok warna, verifikasi tanda tangan QR token `SGS1.*`, rotasi snapshot, dan pipeline end-to-end.

Untuk evaluasi akurasi deteksi (IoU/mAP) dan OCR (exact match & character alignment) pada dataset nyata:

```powershell
python tools\eval_dataset.py --split valid,test
python tools\eval_real.py --part both --limit 200
```

Panduan pelatihan ulang di Google Colab / Kaggle tersedia di [`docs/TRAINING_GUIDE.md`](docs/TRAINING_GUIDE.md).

---

## Referensi (Terdaftar di Mendeley / Crossref / Scopus — 5 Tahun Terakhir: 2021–2026)

> File siap impor langsung ke **Mendeley Reference Manager**: [`docs/references_mendeley.ris`](docs/references_mendeley.ris) dan [`docs/references_mendeley.bib`](docs/references_mendeley.bib).

- Ramadhani, A. D., dkk. (2026). *Analisis Akurasi Pembacaan Karakter Plat Nomor Kendaraan Indonesia Menggunakan YOLOv8 dan EasyOCR*. Jurnal Teknika, Vol. 18, No. 2, 147–154. DOI: [10.30736/jt.v18i2.1604](https://doi.org/10.30736/jt.v18i2.1604).
- Sutikno, Sugiharto, A., dan Kusumaningrum, R. (2025). *Enhanced Automatic License Plate Detection and Recognition using CLAHE and YOLOv11 for Seat Belt Compliance Detection*. Engineering, Technology & Applied Science Research (ETASR), Vol. 15, No. 1, 20271–20278. DOI: [10.48084/etasr.9629](https://doi.org/10.48084/etasr.9629).
- Syihabuddin, E. R., Angela, W., Naufal, M., dan Pramunendar, R. A. (2025). *Pengenalan Plat Nomor Kendaraan dengan YOLOv8 dan PaddleOCR*. Journal of Computer Science and Technology (JCS-TECH), Vol. 5, No. 2, 66–72. DOI: [10.54840/jcstech.v5i2.374](https://doi.org/10.54840/jcstech.v5i2.374).
- Subekti, I., Hariyono, R. C. S., dan Sorikhi. (2025). *Pengenalan Plat Nomor Kendaraan Menggunakan Algoritma Convolutional Neural Network Berbasis Tensorflow*. Remik: Riset dan E-Jurnal Manajemen Informatika Komputer, Vol. 9, No. 3. DOI: [10.33395/remik.v9i3.15169](https://doi.org/10.33395/remik.v9i3.15169). [PDF](docs/artc/15169-Article%20Text-24310-1-10-20250811.pdf)
- Salsabila, N., dan Sriani. (2024). *Enhancing Automated Vehicle License Plate Recognition with YOLOv8 and EasyOCR*. Journal of Information Systems and Informatics (Journal ISI), Vol. 6, No. 3, 1577–1597. DOI: [10.51519/journalisi.v6i3.848](https://doi.org/10.51519/journalisi.v6i3.848).
- Haidar, M. A., dan Arifin, F. (2024). *Evaluation of YOLOv8 Algorithm for Vehicle License Plate Detection System in UNY Integrated Parking Lot*. ELINVO (Electronics, Informatics, and Vocational Education), Vol. 9, No. 2, 220–229. DOI: [10.21831/elinvo.v9i2.70032](https://doi.org/10.21831/elinvo.v9i2.70032).
- Chandrawan, M. A., dkk. (2024). *Design and Build an Automatic AI-IoT Parking Barrier Management System Using YOLO & OCR*. JTRISTE, Vol. 10, No. 1, 41–49. DOI: [10.55645/jtriste.v10i1.389](https://doi.org/10.55645/jtriste.v10i1.389).
- Iriawan, A. D., dan Sunyoto, A. (2023). *Automatic License Plate Recognition System in Indonesia Using YOLOv8 and EasyOCR Algorithm*. 2023 6th International Conference on Information and Communications Technology (ICOIACT), IEEE, 384–388. DOI: [10.1109/ICOIACT59844.2023.10455908](https://doi.org/10.1109/ICOIACT59844.2023.10455908).
- Peraturan Kepolisian Negara Republik Indonesia Nomor 7 Tahun 2021 tentang Registrasi dan Identifikasi Kendaraan Bermotor.
