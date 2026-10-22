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
| Deteksi plat | YOLOv8n / YOLOv8x / YOLOv11n (Ultralytics, CPU) |
| OCR | PaddleOCR (PP-OCRv6 medium) + EasyOCR (fallback), murni CPU |
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
| A/B backend pada frame kamera sama | PaddleOCR `H4TC` (salah), EasyOCR kosong — keduanya gagal pada kasus kamera menyorot layar (moiré) |

### B.2 Teks stiker masa berlaku ikut terbaca sebagai nomor plat

Stiker tanggal ("09·23", "04·25") menempel fisik di papan plat dan selalu ikut
terfoto. Sistem awalnya membaca teks stiker tersebut sebagai nomor plat
(contoh: stiker "04·25" terbaca menjadi `D425`), padahal toggle **Stiker:
Nonaktif** hanya menonaktifkan dekode QR/kode stiker.

### B.3 Salah pilih crop: potongan plat yang dibaca bukan baris nomornya

Detektor terkadang hanya menutup sebagian plat (mis. hanya bagian `NB`) atau
justru menempel pada stiker tanggal, sehingga OCR membaca potongan yang salah
(contoh kasus uji `kg_00069.jpg`: box deteksi jatuh pada stiker → `D425`,
padahal plat `H 6249 NB` terbaca sempurna (confidence 0,99) **ketika crop yang
benar diberikan** — membuktikan masalah ada di pemilihan crop, bukan pada
kemampuan OCR).

### B.4 Kualitas anotasi dataset pelatihan

Pada foto uji `kg_00163.jpg` terlihat 3 plat, tetapi anotasi hanya memuat **1
plat** berukuran **66×16 piksel** — terlalu kecil untuk dilatih maupun dibaca
OCR. Akibatnya model deteksi meleset pada foto tersebut dan sistem benar-benar
mengembalikan "tidak terbaca" (fail-safe) dibanding menghasilkan teks palsu.

### B.5 Foto kamera yang menyorot layar monitor (moiré)

Saat kamera menyorot monitor (bukan kendaraan langsung), pola moiré dan
pantulan membuat kedua backend OCR gagal. Sistem memilih mengembalikan
**"tidak terbaca"** (keputusan `OCR_FAILED`, gerbang tidak dibuka) — sesuai
prinsip *fail-safe*, lebih baik menolak daripada membuka untuk plat yang salah
baca.

---

## C. Tindakan Perbaikan yang Telah Dilakukan

| # | Temuan | Tindakan | Hasil |
| :--- | :--- | :--- | :--- |
| 1 | B.1 RAM/CPU | *Warmup* hanya backend utama (EasyOCR dimuat malas saat dibutuhkan), batas inferensi konkuren (semaphore), rotasi snapshot (maks 200 sesi), pemangkasan *retry* | Pemakaian RAM aplikasi turun ±1 GB; scan jauh lebih cepat dari sebelumnya (dari >10 menit untuk 3 frame menjadi ±45–58 detik) |
| 2 | B.2 Stiker tanggal | Aturan keras: **plat selalu diawali huruf** + kotak bergaya tanggal ("09·23") dibuang dari kandidat bacaan | Teks stiker tidak pernah lagi menjadi nomor plat |
| 3 | B.3 Salah crop | `grow_to_text_line` (crop dilebarkan mengikuti baris tinta plat) + zoom otomatis + pemilihan kandidat NRKB | `kg_00069` terbaca benar `H6249NB` (conf 0,95) |
| 4 | B.4 Dataset | Temuan dilaporkan; perbaikan anotasi menjadi rekomendasi lanjutan | — |
| 5 | B.5 Moiré layar | Gerbang keras format NRKB + fallback antar-backend | `OCR_FAILED` (gerbang tetap tertutup) |

**Bukti regresi:** *test suite* otomatis **102/102 pemeriksaan lulus**.

---

## D. Rekomendasi untuk Deployment di PT Quty Karunia

1. **Gunakan PC/laptop khusus minimal 16 GB RAM** — beban utama bukan deteksi,
   melainkan OCR di CPU. Perangkat uji (12 GB) sudah berada di batas.
2. **Pertimbangkan GPU kecil / NPU** atau model OCR ringan agar *real-time*
   (target < 1 detik per kendaraan).
3. **Kamera Logitech C920 sudah memadai**; yang krusial adalah **pencahayaan dan
   sudut**: usahakan plat terisi ±70% lebar frame, tidak menyorot layar.
4. Interval auto scan disarankan **≥ 2–3 detik** pada perangkat setara i5-8250U
   (interval 1,5 detik tidak tercapai secara fisik).
5. Anotasi ulang dataset (semua plat terlihat, tinggi plat ≥ 30 px) bila ingin
   akurasi deteksi meningkat untuk skripsi/pengembangan lanjutan.
