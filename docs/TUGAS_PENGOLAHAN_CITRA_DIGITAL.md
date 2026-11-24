# Tugas Pengolahan Citra Digital: Smart Gate System

**Mata kuliah:** Pengolahan Citra Digital
**Sistem:** Prototype akses gerbang berbasis plat nomor
**Status:** Implementasi dan evaluasi bertahap

## 1. Latar Belakang

Smart Gate System mengidentifikasi kendaraan tanpa kontak fisik. CCTV 1
menangkap kendaraan pada zona pendekatan, sedangkan CCTV 2 menangkap kendaraan
di dekat gate. Kedua sumber dapat menghasilkan lebih dari satu gambar untuk
diproses bersama. Plat nomor dibaca dengan OCR dan koreksi aturan NRKB sesuai
**Peraturan Kepolisian (Perpol) Nomor 7 Tahun 2021**.

Jika plat cocok dengan database kendaraan aktif dan confidence memenuhi
aturan, sistem menghasilkan `AUTO_OPEN`. Jika plat gagal dibaca atau tidak
cocok, sistem menghasilkan `NO_MATCH` atau `OCR_FAILED`, memberi alert kepada
satpam, dan tidak membuka gate otomatis. Satpam dapat memilih `MANUAL_OVERRIDE`
setelah pemeriksaan visual; foto, pengguna, waktu, dan alasan tetap dicatat.

Ringkasan eksperimen terbaru (**v6 Multi-Domain 5-Fold Stratified Group CV — Fold 0**):
- **YOLOv11n (`smartgate-colab-v6-yolo11n`)**: Bobot `5,48 MB` (`.pt`) / `10,66 MB` (`.onnx`), **Test Hold-out mAP50 = `0,9693`**, `mAP50-95 = 0,6150`, Validation Fold 0 multi-domain `mAP50 = 0,8464` (`mAP50-95 = 0,5686`), End-to-End OCR Valid Format Rate `74,07%` (`80/108`), latensi rata-rata `87,43 ms` (`P95 = 161,03 ms`).
- **YOLOv8n (`smartgate-colab-v6-yolov8n`)**: Bobot `6,48 MB` (`.pt`) / `12,77 MB` (`.onnx`), **Test Hold-out mAP50 = `0,9617`**, `mAP50-95 = 0,5931`, Validation Fold 0 multi-domain `mAP50 = 0,8488` (`mAP50-95 = 0,5669`), **End-to-End OCR Valid Format Rate = `75,96%`** (`79/104`, naik dari `72,03%`), latensi rata-rata `76,50 ms` (`P95 = 157,19 ms`).
- Seluruh pipeline dikunci dengan **133 pemeriksaan** regresi otomatis di `tests/test_pipeline.py`.

## 2. Tujuan

1. Mendeteksi area plat nomor pada gambar kendaraan.
2. Meningkatkan kualitas crop yang terkena noise, blur, dan pantulan cahaya.
3. Menerjemahkan karakter plat Indonesia dengan OCR dan validasi struktur NRKB.
4. Memilih kendaraan paling dekat ketika satu frame berisi beberapa kendaraan.
5. Menghasilkan keputusan gate yang fail-safe dan audit log lengkap.
6. Membandingkan hasil training detektor dengan hasil OCR end-to-end.

## 3. Arsitektur Sistem

```mermaid
flowchart LR
  C1[CCTV 1: pendekatan] --> A[Akuisisi frame]
  C2[CCTV 2: gate] --> A
  M[Foto manual] --> A
  A --> S[Pilih kendaraan terdekat + ROI]
  S --> D[YOLO deteksi plat / OpenCV fallback]
  D --> P[Crop, deskew, deglare, CLAHE, resize]
  P --> O[PaddleOCR/EasyOCR + voting + aturan NRKB]
  O --> F[Fusi bukti (voting antar-frame)]
  F --> DB[Pencocokan master_vehicles]
  DB -->|cocok dan valid| OPEN[AUTO_OPEN]
  DB -->|gagal/tidak cocok| ALERT[NO_MATCH / OCR_FAILED]
  ALERT --> SAT[Alert satpam]
  SAT -->|aman| BYPASS[MANUAL_OVERRIDE]
  SAT -->|tidak aman| REJECT[REJECTED]
  OPEN --> LOG[gate_logs + snapshot]
  BYPASS --> LOG
  REJECT --> LOG
```

Prototype Flask menyediakan halaman `/camera` untuk mengaktifkan webcam,
menjalankan scan manual/otomatis, dan menampilkan overlay runtime. ROI
berwarna cyan, kotak plat hijau, kotak stiker oranye, serta teks hasil OCR
dapat dilihat langsung. Preview menggunakan `persist=0` agar auto-scan tidak
membanjiri log.

## 4. Dataset dan Pelabelan

Dataset utama berada di `prototype/dataset_merged`:

- train: 1.572 gambar;
- valid: 290 gambar;
- test: 84 gambar;
- satu kelas: `number-plate`.

Sumbernya adalah dataset YOLO `plat-nomor/`, dataset COCO
`datasets/detection/` yang dikonversi, plus set Roboflow "Indonesia License
Plate Detection", dataset Kaggle (COCO), dan latar tanpa plat dari
`no-plate-backgrounds.zip`. Penggabungan Colab memakai prefix `rf_`, `kg_`,
dan `bg_`; data latar hanya masuk split train dan split valid/test dijaga
steril dari train (anti-leakage). Dataset OCR `datasets/text/` digunakan
untuk crop dengan label teks. Data tambahan Wikimedia Commons berjumlah
sekitar 13 positif dan 2 negatif pada pengambilan terakhir; sumber dan lisensi
dicatat di `dataset_extra/SOURCES.md`.

Label positif adalah gambar dengan plat yang benar-benar terlihat dan dapat
diverifikasi. Label negatif adalah gambar bukan plat atau gambar yang
dideteksi sebagai false positive. Data internet ditinjau manual dan tidak
dianggap ground truth hanya karena diunduh otomatis.

## 5. Tahapan Pengolahan Citra

### 5.1 Seleksi spasial dan multi-kendaraan

Untuk webcam, input detector dibatasi ke ROI bawah frame secara default
(`x=5--95%`, `y=35--100%`) agar jaket/wajah di bagian atas tidak menjadi
false positive. ROI dapat dikalibrasi melalui `SGS_DETECTION_ROI`. Sebelum
deteksi, frame diberi koreksi gamma ringan (`SGS_DETECTION_GAMMA`, default
1,15; nilai lebih besar menggelapkan highlight) dan CLAHE terbatas. Frame asli
tetap dipakai untuk audit dan OCR.

Deteksi yang berada di luar ROI gate disaring sebelum OCR. Saat beberapa
kendaraan atau objek mirip plat muncul, urutan kandidat ditentukan
`candidate_score`: kemiripan bentuk plat (skor bingkai `plate_border_score` +
skor struktur `plate_plausibility`) didahulukan, kedekatan ke kamera (luas
bbox + posisi bawah) hanya pemecah seri. Skor bingkai menghukum blob teks/video
(subtitle, thumbnail) yang tidak memiliki bingkai papan plat sehingga distraktor
layar tidak mengambil slot OCR dari plat asli. Kandidat yang menelan kandidat lain
dibuang karena sering berupa gabungan bodi/lampu/logo. Maksimal kandidat terbaik
diteruskan ke OCR untuk menekan latency dan mencegah salah baca kendaraan
belakang. Pada tampilan, hanya kotak kandidat terpilih (`primary`) yang digambar
terang; kandidat sekunder digambar tipis transparan agar tidak "sibuk".

ROI default prototype adalah x 10--90% dan y 25--100%; nilai ini harus
dikalibrasi per kamera. Kandidat tunggal tetap dapat diproses untuk foto manual.

### 5.2 Enhancement dan ketahanan pantulan

Urutan pemrosesan crop dapat mencakup:

1. koreksi perspektif/penyempitan ke pita teks (`snap_to_text_band` dengan `keep_horizontal=True` pada bbox YOLO agar karakter tepi kiri/kanan tidak terpotong oleh ambang Otsu global, serta lokalisasi sub-window Otsu pada `grow_to_text_line` agar ~20× lebih cepat di CPU);
2. deteksi highlight dan inpainting `deglare`;
3. grayscale, adaptive threshold, morphology close, serta deteksi polaritas otomatis (`_ink_mask`: membalikkan mask `255 - binary` bila proporsi piksel aktif > 0,55 sehingga mendukung plat dasar putih, kuning, hijau, merah, maupun plat lama warna dasar hitam bertulisan putih);
4. CLAHE untuk kontras lokal;
5. median blur 3×3 untuk meredam moiré/pola piksel layar monitor sebelum
   penajaman;
6. upscale 160/240 piksel dan unsharp mask;
7. margin `pad_crop` dikembalikan setelah penyempitan pita teks agar lengan
   huruf (`Y`, `G`, `4`) yang samar tidak terpotong lalu salah baca
   (mis. `Y` terpotong → terbaca `1` → dinormalisasi `I`);
8. retry terbatas (`deglare`, adaptive threshold) sampai hasil valid **dan**
   keyakinan ≥ 0,80 — dengan penggabungan otomatis baris atas (`prefix + nomor`) dan baris bawah (`seri huruf`) pada plat 2 baris (truk/bus) tanpa *early-exit* prematur pada baris pertama.
9. pengendalian sumber daya CPU & RAM: pencegahan *dual-runtime memory bloat* (`SGS_ENABLE_SECONDARY_OCR=0` default, warmup hanya `_paddle_rec_model`), anggaran keras panggilan OCR per frame (`MAX_OCR_CALLS_FAST = 2`, `MAX_OCR_CALLS_FULL = 6`), penghapusan `zoom 2x` ganda, dan hashing `SHA-1` *zero-copy* (`np.ascontiguousarray`).

Pantulan monitor berbeda dari pantulan kendaraan nyata. Karena itu hasil dari
foto yang menampilkan plat pada layar monitor harus ditandai sebagai kasus
khusus, bukan bukti bahwa sistem sudah stabil untuk semua CCTV.

### 5.3 OCR dan aturan NRKB

Backend prototype memprioritaskan PaddleOCR CPU untuk crop plat kecil/distorsi.
Runtime saat ini masih memakai EasyOCR karena paket `paddleocr` dan
`paddlepaddle` belum terpasang; EasyOCR tetap sebagai fallback kompatibel dan
template matching sebagai fallback terakhir.
PaddleOCR memakai mode recognition pada crop yang sudah dideteksi, allowlist
`0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ`, warm-up, dan cache crop. Jika hasil
awal rendah, sistem mencoba crop deglare/enhancement lalu melakukan voting
lintas frame. Backend dapat dipilih dengan `SGS_OCR_BACKEND`.
Crop hasil YOLO diberi padding agar karakter suffix seperti `UL` tidak terpotong.
EasyOCR juga memakai `paragraph`, `width_ths`, dan `link_threshold` agar jarak
antara nomor dan suffix tetap digabung.

Struktur yang divalidasi mengacu pada **Peraturan Kepolisian (Perpol) Nomor 7 Tahun 2021** tentang Registrasi dan Identifikasi Kendaraan Bermotor:

- **Pola 3 blok pasti**: prefix kode wilayah **1--2 alfabet** (`[A]` atau `[AA]` sesuai `VALID_PREFIXES`, termasuk kode wilayah baru `PG`, `PS`, `PT`, `PY`), nomor urut registrasi **1--4 digit angka** (tidak diawali angka `0`), dan suffix seri akhir **1--3 alfabet** (`[A]`, `[AA]`, `[AAA]` sesuai wilayah Polda, mis. `[A] [9999] [AAA]`, `[A] [9999] [AA]`, `[A] [9999] [A]`, `[AA] [9999] [A]`, `[AA] [9999] [AA]`, `[AA] [9999] [AAA]`);
- **Pemisahan mutlak alfabet vs angka**: **tidak ada angka pada blok alfabet dan tidak ada alfabet pada blok angka**; karakter ambigu dikoreksi berdasarkan posisi blok (`_AMBIGUOUS_ALPHA` dengan prior `(0.75, 0.55)` vs `_AMBIGUOUS_DIGIT` dengan prior `(0.45, 0.80)` agar digit terakhir pada plat tanpa suffix seperti `DD1407` atau `DD2270` tidak berubah menjadi huruf `DD140T` atau `DD227O`). Koreksi prefix `_fix_prefix()` menjaga kode wilayah yang sudah valid (sehingga plat Surabaya `L`, Aceh `BL`, dan Sulut `DL` tidak pernah terubah menjadi `D`, `BD`, `DD`), sekaligus menyelamatkan awalan angka ambigu di `best_plate_text()` (`005877US` → `DD5877US`, `81234XYZ` → `B1234XYZ`);
- **4 digit angka di bawah TNKB (`MMYY`)**: merupakan masa berlaku TNKB (2 digit awal = bulan `01--12`, 2 digit belakang = tahun); dipisahkan oleh `text_rows` dan filter `_DATE_LIKE` (baik dengan pemisah maupun 4 digit rapat seperti `0425`, `1228`) agar tidak tergabung ke dalam nomor plat;
- **Warna dasar (Pasal 45 Perpol 7/2021) & patokan ukuran pada gambar bergerak**: mendukung TNKB Putih (tulisan hitam), Kuning (tulisan hitam), Merah (tulisan putih), Hijau (FTZ), lis biru (EV), serta plat lama Hitam (tulisan putih). Karena citra diambil dari kendaraan bergerak (perspektif/jarak berubah), ukuran & rasio fisik plat dipakai sebagai patokan luwes (*soft prior*) bersama golongan nomor urut.

Aturan di atas bukan sekadar pemeringkat: hasil OCR yang melanggar struktur
NRKB **ditolak keras** dan dianggap tidak terbaca (teks mentah tetap disimpan
di `plate_raw_text` untuk audit), confidence tidak ikut dihitung ke skor fusi,
dan alasan `OCR_FAILED` menjelaskan pelanggaran format. Voting antar-frame juga
membuang suara yang melanggar struktur sebelum penghitungan suara.

Alokasi nomor urut kendaraan berdasarkan **Perpol Nomor 7 Tahun 2021**:
- **Wilayah Umum (Nasional)**: `1--1999` Mobil Penumpang/Pribadi, `2000--6999` Sepeda Motor, `7000--7999` Mobil Bus, `8000--8999` Mobil Barang, `9000--9999` Kendaraan Khusus.
- **Wilayah Polda Metro Jaya (`B`)**: `1--2999` Mobil Penumpang/Pribadi, `3000--6999` Sepeda Motor, `7000--7999` Mobil Bus, `8000--8999` Mobil Barang, `9000--9999` Kendaraan Khusus.

### 5.4 Stiker (rencana pengembangan)

Stiker QR bertanda tangan direncanakan sebagai bukti kedua untuk kendaraan
terdaftar. Implementasi prototype menyediakan deteksi stiker sebagai fondasi,
tetapi **di luar lingkup prototipe saat ini** (masuk rencana pengembangan
mendatang / bahan skripsi, bersama integrasi RFID). Blok warna jenuh hasil
fallback hanya menjadi bukti bila berhasil didekode — kandidat yang gagal
didekode dibuang agar objek berwarna di latar (mis. video/layar) tidak
berubah menjadi kotak stiker palsu.

### 5.5 Perbandingan Arsitektur Detektor (Eksperimen v6 Multi-Domain Fold 0)

Dua arsitektur ringan (*nano*) generasi berurutan (**YOLOv8n** vs **YOLOv11n**) dilatih pada protokol **5-Fold Stratified Group Cross-Validation (Fold 0)** dengan regularisasi anti-degradasi, konfigurasi, dan seed yang sama (50 epoch, GPU Tesla T4, `seed=42`). Keduanya dapat diuji dan diganti langsung saat runtime di aplikasi lewat pemilih model di halaman `/training`:

| Metrik Evaluasi | YOLOv8n (`smartgate-colab-v6-yolov8n`) | YOLOv11n (`smartgate-colab-v6-yolo11n`) | Keunggulan |
| --- | ---: | ---: | --- |
| **Validation Fold 0 mAP50** *(multi-domain ~813 citra)* | **0,8488** | 0,8464 | YOLOv8n (+0,0024) |
| **Validation Fold 0 mAP50-95** *(multi-domain)* | 0,5669 | **0,5686** | YOLOv11n (+0,0017) |
| **Test Hold-out mAP50** *(84 citra)* | 0,9617 | **0,9693** | **YOLOv11n (+0,0076)** |
| **Test Hold-out mAP50-95** *(84 citra)* | 0,5931 | **0,6150** | **YOLOv11n (+0,0219)** |
| **End-to-End OCR Valid Format Rate** | **75,96% (79/104)** | 74,07% (80/108) | **YOLOv8n (+1,89%)** |
| **Latency End-to-End Rata-rata / P95** | **76,50 ms / 157,19 ms** | 87,43 ms / 161,03 ms | **YOLOv8n (lebih cepat 12,5%)** |
| **Ukuran Bobot `best.pt` / `best.onnx`** | 6,48 MB / 12,77 MB | **5,48 MB / 10,66 MB** | **YOLOv11n (15,4% lebih ringkas)** |

#### Analisis Ilmiah Hasil Eksperimen v6 (Multi-Domain Fold 0 vs Hold-out Test):
1. **Mengapa `Validation mAP50` pada Fold 0 Multi-Domain Berada di Kisaran `0,8464–0,8488` (Dibandingkan Split Lama `~0,919–0,936`)?**
   - Pada protokol lama sebelum K-Fold, split `valid` hanya berisi 84 citra dari satu sumber domain tunggal (`plat-nomor` awal) tanpa gambar latar negatif (*0 background*).
   - Melalui **5-Fold Stratified Group Cross-Validation (`dHash` 64-bit anti-leakage)**, Fold 0 menguji model pada **~813 citra validasi multi-domain** yang mencakup campuran proporsional seluruh sumber (`orig`, `rf_` Roboflow, `kg_` Kaggle COCO, `mg_` dataset merged, serta `bg_` *hard-negative background*), variasi skala plat kecil-besar, dan plat 2 baris, di mana tidak ada satu pun kendaraan yang sama (`group_id`) bocor antara `train` dan `val`.
   - Oleh karena itu, angka `Val mAP50 = 0,8464–0,8488` dengan `Val mAP50-95 = 0,5669–0,5686` mencerminkan **evaluasi generalisasi lintas-domain yang jauh lebih jujur dan bebas bias kebocoran frame**, sekaligus berhasil mencegah *model degradation* saat memilih checkpoint `best.pt`.
2. **Peningkatan Performa pada Set `Test` Hold-out (`mAP50` Mencapai `0,9693` pada YOLOv11n dan `0,9617` pada YOLOv8n)**:
   - Bukti nyata bahwa pemilihan checkpoint berbasis Fold 0 multi-domain + regularisasi `ANTI_DEGRADATION_HYPS` (`weight_decay=0.001`, `dropout=0.10`, `perspective=0.0004`, `erasing=0.25`, `close_mosaic=15`, `fliplr=0.0`) meningkatkan generalisasi terlihat pada set `Test` hold-out (84 citra): **Test mAP50 naik dari `0,9564` menjadi `0,9617` pada YOLOv8n** dan **naik dari `0,9683` menjadi `0,9693` pada YOLOv11n** (tertinggi di seluruh eksperimen).
3. **Kenaikan `End-to-End OCR Valid Format Rate` hingga `75,96%` Berkat Parser Perpol No. 7 Tahun 2021**:
   - Pada YOLOv8n, tingkat keberhasilan format NRKB valid meningkat signifikan dari **`72,03%` menjadi `75,96%` (`79/104`)** dan jumlah deteksi ganda/fragmen palsu turun dari 118 menjadi 104 kotak yang lebih bersih.
   - Perbaikan aturan **Perpol Nomor 7 Tahun 2021** terbukti menyelamatkan sampel uji nyata di `evaluation_summary.json`, antara lain:
     - `pl_test (10).jpg`: raw OCR `"005877US"` berhasil dikoreksi menjadi **`"DD 5877 US"`** (sebelumnya ditolak atau ketambahan noise `"USI"`);
     - `pl_test (13).jpg`: raw OCR `"IDD14070M"` berhasil dipangkas noise awalan `'I'` dan dinormalisasi sesuai blok menjadi **`"DD 1407 OM"`** (sebelumnya rusak menjadi `"DD 140 T"` akibat konversi digit ke huruf pada plat tanpa suffix);
     - `pl_test (16).jpg`: plat wilayah Polda Metro Jaya **`"B 2287 TXO"`** terbaca utuh tanpa terpotong huruf `'B'` di tepi kiri (`det_conf = 0,8129–0,8252`, `ocr_conf = 0,8214–0,8487`).
4. **Trade-off YOLOv8n vs YOLOv11n**:
   - **YOLOv11n** unggul pada akurasi lokalisasi detektor (**Test mAP50 `0,9693`**, **Test mAP50-95 `0,6150`**) dan efisiensi ukuran bobot (**`5,48 MB` `.pt` / `10,66 MB` `.onnx`**).
   - **YOLOv8n** menghasilkan *bounding box* yang sedikit lebih ramah terhadap karakter tepi OCR (**Valid Format Rate `75,96%`**) dengan latensi end-to-end lebih cepat (**rata-rata `76,50 ms` / P95 `157,19 ms`**), konsisten dengan temuan *Ramadhani dkk. (2026)*.

Arsip artefak eksperimen: `smartgate-artifacts-Y8N/` dan `smartgate-artifacts-Y11N/` di root repositori (berisi `best.pt`, `best.onnx`, `evaluation_summary.json`, `results.csv`, dan `confusion_matrix.png`).

## 6. Keputusan Sistem

| Kode | Kondisi | Output |
| --- | --- | --- |
| `AUTO_OPEN` | Plat valid dan cocok di database | Perintah buka pintu otomatis dan log foto |
| `NO_MATCH` | Teks terbaca tetapi tidak terdaftar | Alert kendaraan tidak dikenali |
| `OCR_FAILED` | Plat tidak cukup terbaca | Alert kendaraan tidak dikenali |
| `MANUAL_OVERRIDE` | Satpam memverifikasi aman | Bypass buka manual, wajib audit |
| `REJECTED` | Satpam menilai tidak aman | Gate tetap tertutup, simpan alasan |

Jika database, kamera, atau komponen keputusan gagal, sistem tidak melakukan
`AUTO_OPEN`. Semua keputusan menyimpan snapshot dan metadata audit.

## 7. Training Model

Training detektor dijalankan dengan YOLOv8n detection pada `data.yaml` merged.
Contoh CPU:

```powershell
cd "D:\Project\Smart Gate System\Tugas Citra Digital\prototype"
python train_yolo.py --data dataset_merged/data.yaml --epochs 15 `
  --imgsz 416 --batch 8 --device cpu --patience 5 --name smartgate
```

Training berhenti otomatis melalui dua mekanisme: `patience` (tidak ada
perbaikan mAP50 selama N epoch) dan `--target-map50` (default `0,98`,
nonaktifkan dengan `0`) yang memaksa training berhenti begitu target mAP50
tercapai — callback `on_fit_epoch_end` yang sama dipasang di notebook
`plat-nomor/a_YOLOv11n.ipynb` dan `plat-nomor/a_YOLOv8n.ipynb` (`TARGET_MAP50 = 0.98`)
sehingga waktu komputasi GPU/Colab tidak terbuang untuk epoch yang tidak perlu.

Untuk mencegah **degradasi model** (*model degradation* akibat ketimpangan split
`3.982 train : 84 val` satu domain dan kenaikan `val/box_loss` pada paruh akhir
epoch), pipeline pelatihan Google Colab menerapkan **5-Fold Stratified Group
Cross-Validation** (`tools/prepare_kfold.py`) dan regularisasi anti-degradasi
(`ANTI_DEGRADATION_HYPS` di `train_yolo.py`):
- **Anti-leakage visual berbasis Perceptual Hash (`dHash` 64-bit) + SHA-256**:
  mengelompokkan frame CCTV berurutan atau kompresi ulang dari kendaraan yang
  sama (jarak Hamming $\le 4$) ke dalam satu `group_id` agar selalu berada di
  fold yang sama (*GroupKFold*).
- **Stratifikasi multi-dimensi ($K=5$)**: menyeimbangkan proporsi sumber domain
  (`orig`, `rf`, `kg`, `mg`, `bg`), skala luas bbox (`bg_empty`, `small`,
  `medium`, `large`), dan rasio aspek (`one_row` vs `two_row`) ke dalam 5
  manifest portabel `folds/data_fold_0.yaml` s.d. `folds/data_fold_4.yaml`
  (~3.253 `train` : ~813 `val` multi-domain per fold).
- **Regularisasi & augmentasi spesifik kamera gate**: `weight_decay=0.001`,
  `dropout=0.10`, `cos_lr=True`, `degrees=7.0`, `shear=2.5`,
  `perspective=0.0004`, `scale=0.45`, `erasing=0.25`, `close_mosaic=15`, dan
  **`fliplr=0.0`** (wajib `0.0` agar urutan karakter plat tidak terbalik cermin).

Run **V6 Multi-Domain Fold 0 (`smartgate-colab-v6-yolo11n` dan `smartgate-colab-v6-yolov8n`)** (Colab T4, 50 epoch, 5-Fold Stratified Group CV pada pool dataset gabungan ~4.066 gambar) adalah hasil training terbaru yang digunakan oleh sistem:

| Metrik | YOLOv8n (`v6-yolov8n`) | YOLOv11n (`v6-yolo11n`) |
| --- | ---: | ---: |
| Validation Fold 0 mAP50 *(multi-domain)* | **0,8488** | 0,8464 |
| Validation Fold 0 mAP50-95 *(multi-domain)* | 0,5669 | **0,5686** |
| Test Hold-out mAP50 *(84 citra)* | 0,9617 | **0,9693** |
| Test Hold-out mAP50-95 *(84 citra)* | 0,5931 | **0,6150** |
| Valid format rate OCR (V5 Perpol 7/2021) | **75,96% (79/104 plat)** | 74,07% (80/108 plat) |
| Latency rata-rata / P95 | **76,50 ms / 157,19 ms** | 87,43 ms / 161,03 ms |
| Ukuran Bobot `.pt` / `.onnx` | 6,48 MB / 12,77 MB | **5,48 MB / 10,66 MB** |

Bobot dipasang melalui:

```powershell
$env:SGS_YOLO_VARIANT = "yolo11n"   # atau yolov8n — juga bisa diganti di halaman /training
python run.py
```

Tanpa `SGS_YOLO_WEIGHTS`, prototype memakai bobot v6 terbaru secara otomatis
(`runs/detect/smartgate-colab-v6-yolo11n/weights/best.pt` dan
`runs/detect/smartgate-colab-v6-yolov8n/weights/best.pt`, atau langsung dari
folder `smartgate-artifacts-Y11N/best.pt` dan `smartgate-artifacts-Y8N/best.pt`
di root repositori). Validasi detektor dan OCR harus dilaporkan terpisah:

```powershell
yolo val model=runs/detect/smartgate-colab-v6-yolo11n/weights/best.pt `
  data=plat-nomor/data.yaml
python tools/eval_dataset.py --dataset plat-nomor --split test
```

## 8. Evaluasi dan Hasil

Metrik detektor: precision, recall, mAP50, dan mAP50-95. Metrik OCR:
plate accuracy, character accuracy/CER, false accept rate, serta latency
p95. Target akademik dapat digunakan sebagai sasaran eksperimen, bukan klaim
hasil sebelum diuji pada dataset terpisah.

Uji manual yang sudah dicakup meliputi normalisasi NRKB (Perpol No. 7 Tahun
2021), pemilihan kandidat terdekat, ROI, voting OCR, retry enhancement,
penggabungan plat 2 baris, pembacaan plat hitam bertulisan putih, efisiensi
CPU/RAM, pembagian 5-Fold Stratified Group Cross-Validation (`dHash` 64-bit),
keamanan sesi/rate-limiting, fusi, dan alur end-to-end. Regresi otomatis
terkunci di `tests/test_pipeline.py` (assert tanpa framework, **133
pemeriksaan**): aturan NRKB Perpol 7/2021, voting, moiré monitor
(`test_monitor_moire`), dan distraktor layar/video (`test_distractors`).
Kasus seperti `L1257PR` berhasil dibantu penyempitan pita teks dan voting.
Kasus pantulan layar seperti `AA5045YN` masih tidak stabil karena detektor
klasik dapat memecah plat menjadi fragmen.

Untuk pantulan monitor, `SGS_CLAHE_CLIP_LIMIT` dapat diturunkan agar pola moire
tidak terlalu diperkuat. Beberapa frame dari kendaraan yang sama dinormalisasi
lebih dahulu, kemudian hasil mayoritas dipilih. Jika sumber berbeda mengarah
ke dua kendaraan berbeda, hasil tersebut ditolak sebagai konflik bukti dan
tidak boleh `AUTO_OPEN`. Stiker QR dan RFID direncanakan sebagai bukti
tambahan pada tahap pengembangan mendatang / bahan skripsi.

## 9. Keterbatasan dan Pengembangan

- YOLO harus menjadi detector utama pada deployment; OpenCV klasik adalah
  fallback dan lebih sensitif terhadap background terang.
- ROI dan ambang ukuran perlu konfigurasi per gate.
- Foto kendaraan langsung lebih representatif daripada foto layar monitor.
- Tracking antar-frame (ByteTrack/DeepSORT) belum diimplementasikan.
- Training OCR khusus karakter Indonesia masih merupakan pengembangan; saat ini
  sistem menggunakan recognizer pretrained, enhancement, voting, dan aturan
  NRKB.
- Data gagal yang telah dikonfirmasi satpam sebaiknya dianonimkan, diberi label,
  lalu dimasukkan ke evaluasi berikutnya.

## 10. Kesimpulan

Pipeline menghasilkan keluaran sampai perintah buka pintu, kendaraan tidak
dikenali, bypass satpam, atau penolakan. Kombinasi dua CCTV, seleksi kendaraan
terdekat, deglare, OCR retry, aturan NRKB sesuai **Perpol Nomor 7 Tahun 2021**,
database, dan audit snapshot mengurangi risiko salah baca dan salah buka.
Penerapan **5-Fold Stratified Group Cross-Validation (`dHash` 64-bit)** dan
regularisasi anti-degradasi pada eksperimen v6 Multi-Domain Fold 0 berhasil
meningkatkan akurasi deteksi hold-out hingga **`Test mAP50 = 0,9693`** pada
**YOLOv11n** (`5,48 MB`) serta meningkatkan **`End-to-End OCR Valid Format Rate`
hingga `75,96%`** dengan latensi rata-rata **`76,50 ms`** pada **YOLOv8n**
(`6,48 MB`), didukung oleh **133 pemeriksaan** unit test otomatis yang lulus
100%. Validasi produksi tetap memerlukan rekaman CCTV nyata yang mencakup
siang, malam, hujan, pantulan, dan kendaraan tidak terdaftar.

## Referensi (Terdaftar di Mendeley / Crossref / Scopus — 5 Tahun Terakhir: 2021–2026)

> File siap impor 1-klik ke **Mendeley Reference Manager**: [`references_mendeley.ris`](references_mendeley.ris) dan [`references_mendeley.bib`](references_mendeley.bib).

1. Ramadhani, A. D., Amami, A. F., Lesmono, A. N., Pramulen, A. S., Nadziroh, F., dan Segara, A. J. T. (2026). *Analisis Akurasi Pembacaan Karakter Plat Nomor Kendaraan Indonesia Menggunakan YOLOv8 dan EASYOCR*. **Jurnal Teknika**, 18(2), 147–154. DOI: [10.30736/jt.v18i2.1604](https://doi.org/10.30736/jt.v18i2.1604). — Temuan: akurasi deteksi bbox tidak otomatis identik dengan akurasi OCR; margin horizontal kotak deteksi sangat menentukan keberhasilan pembacaan karakter tepi.
2. Sutikno, Sugiharto, A., dan Kusumaningrum, R. (2025). *Enhanced Automatic License Plate Detection and Recognition using CLAHE and YOLOv11 for Seat Belt Compliance Detection*. **Engineering, Technology & Applied Science Research (ETASR)**, 15(1), 20271–20278. DOI: [10.48084/etasr.9629](https://doi.org/10.48084/etasr.9629). *(Terindeks Scopus Q2 & Mendeley Catalog)* — Peningkatan kontras lokal menggunakan CLAHE (`clipLimit=2.0`, grid `8×8`) yang dipadukan dengan arsitektur YOLOv11 untuk mendongkrak keterbacaan plat pada pencahayaan rendah/silau tanpa menambah beban parameter model.
3. Syihabuddin, E. R., Angela, W., Naufal, M., dan Pramunendar, R. A. (2025). *Pengenalan Plat Nomor Kendaraan dengan YOLOv8 dan PaddleOCR*. **Journal of Computer Science and Technology (JCS-TECH)**, 5(2), 66–72. DOI: [10.54840/jcstech.v5i2.374](https://doi.org/10.54840/jcstech.v5i2.374). — Pipeline 2-tahap ringan (YOLOv8 untuk lokalisasi plat Indonesia + PaddleOCR untuk rekognisi karakter) dengan pra-pemrosesan terfokus pada crop plat agar tetap efisien di CPU.
4. Subekti, I., Hariyono, R. C. S., dan Sorikhi. (2025). *Pengenalan Plat Nomor Kendaraan Menggunakan Algoritma Convolutional Neural Network Berbasis Tensorflow*. **Remik**, 9(3). DOI: [10.33395/remik.v9i3.15169](https://doi.org/10.33395/remik.v9i3.15169). — ANPR dengan CNN LeNet-5, akurasi 89,86% (50 citra); usulan klasifikasi per blok (huruf awal / angka / huruf akhir) sejalan dengan aturan NRKB pada sistem ini. [PDF](artc/15169-Article%20Text-24310-1-10-20250811.pdf)
5. Salsabila, N., dan Sriani. (2024). *Enhancing Automated Vehicle License Plate Recognition with YOLOv8 and EasyOCR*. **Journal of Information Systems and Informatics (Journal ISI)**, 6(3), 1577–1597. DOI: [10.51519/journalisi.v6i3.848](https://doi.org/10.51519/journalisi.v6i3.848). *(Terindeks SINTA 2, DOAJ, Crossref & Mendeley)* — Peningkatan akurasi pengenalan plat nomor otomatis pada gerbang parkir menggunakan kombinasi YOLOv8 dan EasyOCR.
6. Haidar, M. A., dan Arifin, F. (2024). *Evaluation of YOLOv8 Algorithm for Vehicle License Plate Detection System in UNY Integrated Parking Lot*. **ELINVO (Electronics, Informatics, and Vocational Education)**, 9(2), 220–229. DOI: [10.21831/elinvo.v9i2.70032](https://doi.org/10.21831/elinvo.v9i2.70032). *(Terindeks SINTA 2, Crossref & Mendeley)* — Evaluasi deteksi plat nomor warna dasar putih dan hitam pada gerbang parkir nyata dengan pembatasan *Region of Interest* (ROI) untuk efisiensi komputasi *real-time*.
7. Chandrawan, M. A., Tanamal, E., Prasetya, A. I. D., Syariati, K., dan Suardi, C. (2024). *Design and Build an Automatic AI-IoT Parking Barrier Management System Using YOLO & OCR*. **JTRISTE**, 10(1), 41–49. DOI: [10.55645/jtriste.v10i1.389](https://doi.org/10.55645/jtriste.v10i1.389). — Integrasi detektor YOLO, OCR, dan verifikasi database kendaraan untuk sistem manajemen palang pintu otomatis (*smart barrier gate*).
8. Iriawan, A. D., dan Sunyoto, A. (2023). *Automatic License Plate Recognition System in Indonesia Using YOLOv8 and EasyOCR Algorithm*. **2023 6th International Conference on Information and Communications Technology (ICOIACT)**, IEEE, 384–388. DOI: [10.1109/ICOIACT59844.2023.10455908](https://doi.org/10.1109/ICOIACT59844.2023.10455908). *(Terindeks IEEE Xplore, Scopus & Mendeley Catalog)* — Implementasi spesifik pengenalan plat nomor kendaraan Indonesia berbasis YOLOv8 dan EasyOCR.
9. Peraturan Kepolisian Negara Republik Indonesia Nomor 7 Tahun 2021 tentang Registrasi dan Identifikasi Kendaraan Bermotor (NRKB & TNKB).
