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

---

## C. Tindakan Mitigasi yang Telah Dilakukan

| Tindakan | Dampak |
| :--- | :--- |
| *Warmup* hanya satu backend OCR (backend cadangan dimuat malas saat dibutuhkan) | Pemakaian RAM aplikasi turun ±1 GB |
| Batas inferensi konkuren (semaphore 2 proses) | CPU tidak lumpuh oleh banyak scan paralel |
| Rotasi snapshot otomatis (maksimum 200 sesi) | Penyimpanan tidak membengkak tanpa batas |
| Pemangkasan jumlah percobaan OCR + *early stop* saat hasil sudah valid | Scan 3 frame turun dari **> 10 menit menjadi ±45–58 detik** |
| Cache hasil baca per frame identik (TTL 30 detik) | Auto scan tidak mengulang pekerjaan yang sama |
| Batas thread inferensi (OMP/PyTorch/OpenCV = setengah core logis) + `OMP_WAIT_POLICY=PASSIVE` | CPU saat scan turun dari ~90% menjadi **±53%** — CPU tidak lagi jenuh oleh pool thread yang saling berebut |
| Jalur cepat OCR: recognizer tanpa deteksi teks (deteksi teks hanya untuk hasil gagal format) | Satu pembacaan OCR turun dari ±2,9 detik menjadi **±0,45 detik** |
| Satu inferensi pada satu waktu (semaphore `SGS_MAX_CONCURRENT_INFER`) | Dua scan paralel tidak lagi saling memperlambat |

*Catatan: perbaikan murni logika/kode (pemilihan crop, aturan format nomor plat,
penyaringan stiker tanggal, dan seterusnya) dikerjakan sebagai bagian
pengembangan internal dan tidak dicatat sebagai temuan masalah lingkungan
pengujian. Regresi dijaga oleh test suite otomatis (**102/102 pemeriksaan
lulus**).*

---

## D. Rekomendasi untuk Deployment di PT Quty Karunia

1. **Gunakan PC/laptop khusus minimal 16 GB RAM** — beban utama bukan deteksi,
   melainkan OCR di CPU. Perangkat uji (12 GB) sudah berada di batas.
2. **Pertimbangkan GPU kecil / NPU** atau model OCR ringan agar *real-time*
   (target < 1 detik per kendaraan). Contoh perangkat yang relevan: **Axelera
   Metis** (Compute Board / M.2 / PCIe) dengan **Voyager SDK** — deteksi objek
   CCTV dapat di-*offload* ke NPU tersebut (referensi: forum komunitas Axelera
   "Home Assistant CCTV object and motion detection using Metis" dan repositori
   `axelera-ai-hub/voyager-sdk` di GitHub). Implementasi lapangan yang mirip
   dengan proyek ini: `graffitiwriter/Metis-for-Home-Assistant-Motion-Detection`
   (GitHub) — deteksi zona per-koordinat untuk menyaring positif palsu (konsep
   sama dengan ROI zona gerbang di prototipe), dan Voyager SDK mendukung
   *cascaded pipeline* yang bisa diperluas ke pengenalan plat nomor.
3. **Kamera Logitech C920 sudah memadai**; yang krusial adalah **pencahayaan dan
   sudut**: usahakan plat terisi ±70% lebar frame, tidak menyorot layar.
4. Interval auto scan **1,5 detik kini tercapai** setelah optimasi (scan cepat
   ±1,4 detik); 2–3 detik tetap wajar bila ada beban lain di mesin yang sama.
5. Anotasi ulang dataset (semua plat terlihat, tinggi plat ≥ 30 px) bila ingin
   akurasi deteksi meningkat untuk skripsi/pengembangan lanjutan.

---

## Referensi

1. Harani, N. H., Prianto, C., dan Hasanah, M. (2019). *Deteksi Objek dan
   Pengenalan Karakter Plat Nomor Kendaraan Indonesia Menggunakan Metode
   Convolutional Neural Network (CNN) Berbasis Python*. **Jurnal Teknik
   Informatika**, Vol. 11, No. 3, Agustus 2019. Politeknik Pos Indonesia.
   [PDF](artc/658-Article%20Text-963-1-10-20200213.pdf) — CNN efektif untuk
   klasifikasi karakter plat (37 class huruf+angka); deteksi posisi kendaraan
   memakai Faster R-CNN.
2. Subekti, I., Hariyono, R. C. S., dan Sorikhi. (2025). *Pengenalan Plat Nomor
   Kendaraan Menggunakan Algoritma Convolutional Neural Network Berbasis
   Tensorflow*. **Remik: Riset dan E-Jurnal Manajemen Informatika Komputer**,
   Vol. 9, No. 3, Agustus 2025. DOI:
   [10.33395/remik.v9i3.15169](https://doi.org/10.33395/remik.v9i3.15169)
   [PDF](artc/15169-Article%20Text-24310-1-10-20250811.pdf) — ANPR dengan
   CNN LeNet-5 (akurasi 89,86% pada 50 citra); rekomendasi pemisahan klasifikasi
   per blok (huruf awal / angka / huruf akhir) sejalan dengan aturan NRKB yang
   diterapkan sistem ini. *(Salinan duplikat:
   `15169-Article Text-24310-1-10-20250811 (1).pdf`.)*
3. Forum Komunitas Axelera AI. *Home Assistant CCTV Object and Motion Detection
   Using Metis*. [community.axelera.ai](https://community.axelera.ai/the-axelera-forum-52/home-assistant-cctv-object-and-motion-detection-using-metis-1226) ·
   [`axelera-ai-hub/voyager-sdk`](https://github.com/axelera-ai-hub/voyager-sdk) ·
   [`graffitiwriter/Metis-for-Home-Assistant-Motion-Detection`](https://github.com/graffitiwriter/Metis-for-Home-Assistant-Motion-Detection) —
   offload deteksi CCTV ke NPU Axelera Metis (~30 FPS, ±196 ms), zona deteksi
   per-koordinat, dan cascaded pipeline Voyager SDK untuk pengenalan plat
   (opsi percepatan bila target < 1 detik per kendaraan).
