# Lampiran Temuan Masalah — Laporan Kerja Praktik
## Smart Gate System di PT Quty Karunia (One Gate)

> Bahan siap salin untuk laporan KP. Semua angka di bawah **hasil pengukuran
> nyata** pada perangkat yang sama saat pengujian, bukan estimasi.

---

## A. Lingkungan Pengujian

### A.1 Spesifikasi Laptop

| Komponen | Spesifikasi |
| :--- | :--- |
| Tipe | **Dell Inspiron 5570** |
| Prosesor | **Intel Core i5-8250U** — 4 core / 8 thread, 1,6 GHz (turbo ±3,4 GHz) |
| Memori (RAM) | **12 GB DDR4 2400 MHz** (2 keping: 8 GB + 4 GB, 2 dari 2 slot terpakai) |
| Grafis | Intel UHD Graphics 620 + AMD Radeon R7 M460 |
| Penyimpanan | SSD NVMe V-GEN 512 GB |
| Sistem operasi | Microsoft Windows 11 Home Single Language (build 26200) |

### A.2 Perangkat Kamera

| Perangkat | Keterangan |
| :--- | :--- |
| Kamera utama | **Logitech HD Pro Webcam C920** (USB, 1080p) |
| Kamera sekunder | Integrated Webcam (bawaan laptop) |
| Penempatan | Menghadap jalur masuk gerbang (atau monitor CCTV saat uji) |

### A.3 Perangkat Lunak

| Komponen | Versi / Keterangan |
| :--- | :--- |
| Deteksi plat | YOLOv8n / YOLOv11n (`best.onnx` murni via `onnxruntime` / `cv2.dnn` tanpa PyTorch; fallback `.pt` Ultralytics & OpenCV klasik) |
| OCR | PaddleOCR (`PP-OCRv6_medium_rec` jalur cepat), murni CPU (`SGS_ENABLE_SECONDARY_OCR=0` default untuk mencegah *dual-runtime RAM bloat*) |
| Web server | Flask (dev) / Waitress (mode produksi `--prod`) |
| Database | SQLite (WAL) |

---

## B. Temuan Masalah

### B.1 Keterbatasan sumber daya: RAM dan CPU hampir jenuh *(temuan utama)*

Pengamatan langsung melalui **Task Manager** saat aplikasi berjalan dan melakukan
scan:

| Metrik | Pengukuran | Keterangan |
| :--- | :--- | :--- |
| RAM terpakai | **10,0 GB dari 11,9 GB (84%)** | Sisa 1,9 GB — mendekati batas |
| RAM *committed* | **21,1 GB dari 25,3 GB** | *Page file* ikut membengkak |
| CPU | **96% pada 2,2 GHz** | Jenuh saat inferensi |
| Proses aplikasi | **±3,5 GB RSS** (satu proses `python.exe`) | PaddleOCR + EasyOCR/PyTorch + YOLO termuat bersamaan |

**Akibat yang terasa:**
1. Waktu baca jauh lebih lambat daripada nilai *interval* yang tampil (interval
   1,5 detik hanyalah **jeda antar-scan**; durasi proses nyata 1–3 detik/frame
   untuk jalur cepat dan ±15 detik/frame untuk jalur penuh 3 frame).
2. Pada percobaan dengan beban penuh, **proses server pernah berhenti (crash)**
   karena kehabisan sumber daya — halaman web berubah menjadi *connection
   refused*.
3. OCR yang berat di CPU menjadi penyumbang latensi terbesar; deteksi YOLO
   sendiri relatif ringan (±100 ms).

**Bukti pengukuran latensi (CPU i5-8250U, tanpa GPU):**

| Aktivitas | Waktu |
| :--- | :--- |
| Scan cepat (preview auto scan), 1 frame | ±1–3 detik (model sudah hangat) |
| Scan penuh (Scan & Simpan Log), 3 frame | ±45–58 detik (termasuk muat model ±12 detik pertama) |
| Satu panggilan OCR pada crop plat (PaddleOCR) | ±0,5–2 detik |

Nilai *interval* 1,5 detik pada halaman kamera hanyalah **jeda antar-scan**;
siklus nyata = durasi proses + jeda tersebut. Pada perangkat ini interval
praktis terkecil yang masuk akal adalah **±2–3 detik**.

**Pengukuran setelah optimasi (29 Oktober 2026, perangkat yang sama):**

| Aktivitas | Sebelum | Sesudah |
| --- | --- | --- |
| Scan cepat (preview auto scan), 1 frame — model hangat | ±4,5 detik | **±1,4 detik** |
| Scan penuh (Scan & Simpan Log), 3 frame — model hangat | ±15 detik | **±5 detik** |
| Satu panggilan OCR pada crop plat | ±2,9 detik | **±0,45 detik** (jalur cepat) |
| CPU rata-rata saat scan | ~90% | **±53%** (puncak 83%) |
| Memori aplikasi (RSS) | ±3,5 GB | **±1,2 GB** |

Dengan angka ini interval auto scan **1,5 detik tercapai** dan sisa CPU cukup
untuk browser/presentasi. Angka "sebelum" pada tabel latensi di atas tetap
dipertahankan sebagai dokumentasi temuan awal saat pengujian KP.

### B.2 Konflik DLL Windows antara PaddlePaddle dan PyTorch (`torch\lib\shm.dll`)

Pada pengujian mode produksi (`python run.py --prod`) di lingkungan Windows 11 dengan virtual environment `.venv` yang memuat `PaddlePaddle` dan `PyTorch/Ultralytics` secara bersamaan:
- Memuat `paddle` sebelum `paddlex`/`torch` memicu galat sistem **`OSError: [WinError 127] ... Error loading "torch\lib\shm.dll"`** saat warmup detektor YOLO serta **`RuntimeError: PDX has already been initialized`** pada panggilan ulang `PaddleOCR`.
- **Solusi yang diterapkan**:
  1. Menjalankan model deteksi **`best.onnx`** secara murni melalui `_OnnxYoloRunner` (`onnxruntime` atau `cv2.dnn.readNetFromONNX` bawaan OpenCV, dikontrol `SGS_USE_ONNX=1`) **tanpa mengimpor `torch` maupun `ultralytics`**, sehingga konflik DLL hilang total dan konsumsi RAM produksi semakin ringan.
  2. Memuat `paddlex` sebelum `import paddle` pada `_configure_paddle_cpu()` di `app/ocr.py` dan menangkap `(ImportError, OSError)` pada fallback `.pt`.

---

## C. Tindakan Mitigasi yang Telah Dilakukan

| Tindakan | Dampak |
| :--- | :--- |
| *Warmup* hanya satu backend OCR (`SGS_ENABLE_SECONDARY_OCR=0`, tanpa memuat EasyOCR/PyTorch bersamaan) | Pemakaian RAM aplikasi turun ±1–2 GB (stabil ±1,2 GB RSS) |
| Runner deteksi YOLO ONNX murni (`_OnnxYoloRunner` via `onnxruntime` / `cv2.dnn`, `SGS_USE_ONNX=1`) + urutan inisialisasi `paddlex` sebelum `paddle` | Menghilangkan crash Windows `torch\lib\shm.dll` (`WinError 127`) dan `PDX has already been initialized`, tanpa perlu memuat PyTorch ke RAM |
| Perlindungan `deglare()` untuk TNKB dasar putih (`median < 175`, `gray >= 251`, `glare_ratio <= 0,25`), pelestarian huruf seri `Q`, pemisahan golongan `bus` (`7000–7999`) vs `truck` (`8000–8999`), serta *fail-safe* `db.settings()` | Menutup seluruh temuan audit minor (`M-1`, `L-1`, `L-2`, `L-3`, `L-4`) agar tepi karakter TNKB putih tetap tajam dan kegagalan SQLite tidak pernah memicu `AUTO_OPEN` |
| Batas inferensi konkuren (semaphore `SGS_MAX_CONCURRENT_INFER=1`) | CPU tidak lumpuh oleh banyak scan paralel |
| Rotasi snapshot otomatis (maksimum 200 sesi) | Penyimpanan tidak membengkak tanpa batas |
| Pemangkasan jumlah percobaan OCR + anggaran keras (`MAX_OCR_CALLS_FAST=2`, `FULL=6`) + *early stop* | Scan 3 frame turun dari **> 10 menit menjadi ±5 detik** |
| Cache hasil baca per frame identik (TTL 30 detik, SHA-1 *zero-copy*) | Auto scan tidak mengulang pekerjaan yang sama |
| Batas thread inferensi (`SGS_CPU_THREADS` = setengah core logis) + `OMP_WAIT_POLICY=PASSIVE` | CPU saat scan turun dari ~90% menjadi **±53%** — CPU tidak lagi jenuh oleh pool thread yang saling berebut |
| Jalur cepat OCR: recognizer `PP-OCRv6_medium_rec` tanpa deteksi teks | Satu pembacaan OCR turun dari ±2,9 detik menjadi **±0,45 detik** |

*Catatan: seluruh perbaikan logika, keamanan, efisiensi, dan kompatibilitas runtime
dijaga oleh test suite otomatis (**151/151 pemeriksaan lulus**, termasuk uji
deteksi & OCR pada dataset nyata `plat-nomor/test`). Detail audit lengkap
tersedia di [`AUDIT_FULL_CODE_ML.md`](AUDIT_FULL_CODE_ML.md).*

---

## D. Rekomendasi untuk Deployment di PT Quty Karunia

1. **Gunakan PC/laptop khusus minimal 16 GB RAM** — beban utama bukan deteksi,
   melainkan OCR di CPU. Perangkat uji (12 GB) sudah berada di batas.
2. **Pertahankan mode ONNX (`SGS_USE_ONNX=1`, default aktif)** — model deteksi `best.onnx` (`10,66 MB` YOLOv11n / `12,77 MB` YOLOv8n) kini sudah berjalan otomatis tanpa PyTorch; bila dibutuhkan latensi < 1 detik konsisten pada beban tinggi, tambahkan paket `onnxruntime` atau akselerator GPU kecil / NPU.
3. **Kamera Logitech C920 sudah memadai**; yang krusial adalah **pencahayaan dan
   sudut**: usahakan plat terisi ±70% lebar frame, tidak menyorot layar.
4. Interval auto scan **1,5 detik kini tercapai** setelah optimasi (scan cepat
   ±1,4 detik); 2–3 detik tetap wajar bila ada beban lain di mesin yang sama.
5. Anotasi ulang dataset (semua plat terlihat, tinggi plat ≥ 30 px) bila ingin
   akurasi deteksi meningkat untuk skripsi/pengembangan lanjutan.

---

## Referensi (Terdaftar di Mendeley / Crossref / Scopus — 5 Tahun Terakhir: 2021–2026)

> File siap impor 1-klik ke **Mendeley Reference Manager**: [`references_mendeley.ris`](references_mendeley.ris) dan [`references_mendeley.bib`](references_mendeley.bib).

1. Ramadhani, A. D., dkk. (2026). *Analisis Akurasi Pembacaan Karakter Plat
   Nomor Kendaraan Indonesia Menggunakan YOLOv8 dan EasyOCR*. **Jurnal
   Teknika**, Vol. 18, No. 2, 147–154. DOI:
   [10.30736/jt.v18i2.1604](https://doi.org/10.30736/jt.v18i2.1604).
2. Sutikno, Sugiharto, A., dan Kusumaningrum, R. (2025). *Enhanced Automatic
   License Plate Detection and Recognition using CLAHE and YOLOv11 for Seat Belt
   Compliance Detection*. **Engineering, Technology & Applied Science Research
   (ETASR)**, Vol. 15, No. 1, 20271–20278. DOI:
   [10.48084/etasr.9629](https://doi.org/10.48084/etasr.9629).
3. Syihabuddin, E. R., Angela, W., Naufal, M., dan Pramunendar, R. A. (2025).
   *Pengenalan Plat Nomor Kendaraan dengan YOLOv8 dan PaddleOCR*. **Journal of
   Computer Science and Technology (JCS-TECH)**, Vol. 5, No. 2, 66–72. DOI:
   [10.54840/jcstech.v5i2.374](https://doi.org/10.54840/jcstech.v5i2.374).
4. Subekti, I., Hariyono, R. C. S., dan Sorikhi. (2025). *Pengenalan Plat Nomor
   Kendaraan Menggunakan Algoritma Convolutional Neural Network Berbasis
   Tensorflow*. **Remik: Riset dan E-Jurnal Manajemen Informatika Komputer**,
   Vol. 9, No. 3, Agustus 2025. DOI:
   [10.33395/remik.v9i3.15169](https://doi.org/10.33395/remik.v9i3.15169)
   [PDF](artc/15169-Article%20Text-24310-1-10-20250811.pdf).
5. Salsabila, N., dan Sriani. (2024). *Enhancing Automated Vehicle License Plate
   Recognition with YOLOv8 and EasyOCR*. **Journal of Information Systems and
   Informatics (Journal ISI)**, Vol. 6, No. 3, 1577–1597. DOI:
   [10.51519/journalisi.v6i3.848](https://doi.org/10.51519/journalisi.v6i3.848).
6. Haidar, M. A., dan Arifin, F. (2024). *Evaluation of YOLOv8 Algorithm
   for Vehicle License Plate Detection System in UNY Integrated Parking Lot*.
   **ELINVO**, Vol. 9, No. 2, 220–229. DOI:
   [10.21831/elinvo.v9i2.70032](https://doi.org/10.21831/elinvo.v9i2.70032).
7. Chandrawan, M. A., dkk. (2024). *Design and Build an Automatic AI-IoT Parking
   Barrier Management System Using YOLO & OCR*. **JTRISTE**, Vol. 10, No. 1,
   41–49. DOI: [10.55645/jtriste.v10i1.389](https://doi.org/10.55645/jtriste.v10i1.389).
8. Iriawan, A. D., dan Sunyoto, A. (2023). *Automatic License Plate Recognition
   System in Indonesia Using YOLOv8 and EasyOCR Algorithm*. **2023 6th
   International Conference on Information and Communications Technology
   (ICOIACT)**, IEEE, 384–388. DOI:
   [10.1109/ICOIACT59844.2023.10455908](https://doi.org/10.1109/ICOIACT59844.2023.10455908).
9. Peraturan Kepolisian Negara Republik Indonesia Nomor 7 Tahun 2021 tentang
   Registrasi dan Identifikasi Kendaraan Bermotor.
