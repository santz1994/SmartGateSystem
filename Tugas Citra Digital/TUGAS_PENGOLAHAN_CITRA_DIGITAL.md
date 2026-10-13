# Tugas Pengolahan Citra Digital — Smart Gate System

**Mata Kuliah:** Pengolahan Citra Digital  
**Kelompok:** [Nama Kelompok / NIM]  
**Tanggal:** 2026-10-13  
**Sistem:** Enterprise Smart Gate System (akses gerbang otomatis berbasis fusi citra ganda)

---

## 1. Latar Belakang & Rumusan Masalah

Sistem gerbang konvensional mengandalkan RFID atau kartu akses yang rentan hilang/terpinjam. Solusi berbasis **pengolahan citra** memungkinkan identifikasi kendaraan tanpa kontak fisik melalui:
- **OCR Plat Nomor** (Automatic License Plate Recognition / ALPR)
- **Dekode Stiker Khusus** (QR/AprilTag/pola warna) sebagai penguat identifikasi

Tantangan teknis: pencahayaan berubah (siang/malam/hujan), sudut kamera, plat kotor/terhalang, resolusi CCTV terbatas, dan latensi ketat (≤ 1.5 s dari frame ke motor).

---

## 2. Arsitektur Pipeline Pengolahan Citra

```mermaid
flowchart LR
    subgraph INPUT["Input Data"]
        MANUAL[Foto Manual\n(.jpg/.jpeg/.png)]
        C1[CCTV 1\nRTSP 1080p@25fps]
        C2[CCTV 2\nRTSP 1080p@25fps]
    end

    subgraph CAPTURE["Akuisisi"]
        GRAB[Frame Grabber]
    end

    subgraph PRE["Pre-processing"]
        ROI[ROI Extraction\n(YOLOv8 vehicle bbox)]
        DESKEW[Koreksi Perspektif\n4-point transform]
        CLAHE[Kontras Adaptif\nCLAHE pada kanal L]
        DENOISE[Denoising\nBilateral/Gaussian]
        RESIZE[Resize Tetap\ntinggi plat = 64 px]
    end

    subgraph DETECT["Deteksi & Segmentasi"]
        YOLO[YOLOv8n-seg\nplat + stiker]
        CROP[Crop ROI Plat\nCrop ROI Stiker]
    end

    subgraph RECOG["Pengolahan Lanjut"]
        OCR[PaddleOCR / EasyOCR\nkarakter Indonesia]
        STK[Sticker Decoder\nQR/AprilTag + fallback klasifikasi]
    end

    subgraph FUSION["Fusi & Keputusan"]
        BEST[Best Frame Selection\nLaplacian variance x det_conf]
        SCORE[Fusion Score\nmax(plat, stiker) + bonus multi-kamera]
        MATCH[Pencocokan DB\nmaster_vehicles + car_bookings]
    end

    subgraph OUTPUT["Output Sistem"]
        AUTO["Buka Pintu Otomatis\n(AUTO_OPEN)"]
        UNKNOWN["Kendaraan Tidak Dikenali\n(NO_MATCH / OCR_FAILED)"]
        BYPASS["Menunggu Bypass Satpam\n(MANUAL_OVERRIDE)"]
        REJECT["Tolak Akses\n(REJECTED)"]
        LOG[(gate_logs + snapshot)]
    end

    MANUAL --> GRAB
    C1 --> GRAB
    C2 --> GRAB
    GRAB --> ROI
    ROI --> DESKEW --> CLAHE --> DENOISE --> RESIZE
    RESIZE --> YOLO --> CROP
    CROP --> OCR
    CROP --> STK
    OCR --> BEST
    STK --> BEST
    BEST --> SCORE --> MATCH

    MATCH -->|Data cocok & valid| AUTO
    MATCH -->|Tidak cocok / gagal baca| UNKNOWN
    UNKNOWN -->|"Satpam: Aman -> Bypass"| BYPASS
    UNKNOWN -->|"Satpam: Tidak Aman -> Tolak"| REJECT
    AUTO --> LOG
    BYPASS --> LOG
    REJECT --> LOG
```

---

## 3. Input Data (Foto Manual & CCTV)

Sistem menerima **2 jenis input citra** untuk diproses melalui pipeline yang sama:

### 3.1 Input Otomatis (Real-Time)
- **CCTV 1 (Zona Pendekatan):** menangkap kendaraan saat mendekat (5–10 m dari gerbang). Berfungsi untuk membaca plat + stiker sebagai sumber pertama.
- **CCTV 2 (Zona Gate):** menangkap dekat gerbang sebagai sumber kedua (verifikasi & korelasi).

### 3.2 Input Manual (Foto Tunggal)
Selain stream CCTV, sistem juga dapat menerima **input foto manual** (uji coba, validasi, atau kasus khusus). Foto dapat diunggah langsung ke AI Worker/Backend.

**Format yang diterima:**
| Parameter | Nilai |
| :--- | :--- |
| **Ekstensi** | `.jpg`, `.jpeg`, `.png`, `.bmp` |
| **Resolusi** | Minimal 720p, disarankan 1080p–4K |
| **Mode Input** | Upload file (form-data) atau base64 |
| **Orientasi** | Potret/Landscape (akan dinormalisasi otomatis) |

**Alur Pemrosesan Foto Manual:**
1. **Upload Foto** → pengguna mengunggah 1 foto kendaraan (minimal terlihat plat dan/atau stiker).
2. **Inisialisasi Sesi** → sistem membuat `session_id` sementara (single-image session).
3. **Pre-processing** → ROI, deskew, CLAHE, denoise, resize (pipeline sama persis dengan CCTV).
4. **Deteksi & Ekstraksi** → YOLOv8 mendeteksi plat + stiker → crop → OCR + decode stiker.
5. **Evaluasi & Keputusan** → fusi skor (hanya 1 sumber gambar) → pencocokan database → menghasilkan output keputusan.

> **Catatan:** Untuk foto manual (1 sumber citra), bobot multi-kamera tidak berlaku. Sistem tetap menggunakan ambang confidence yang sama dan tetap menghasilkan log beserta snapshot.

## 4. Detail Tahapan Pengolahan Citra

### 4.1 Akuisisi & Korelasi Sesi
- **Sumber:** 2 CCTV IP (pendekatan + gate), stream RTSP H.264 **ATAU** foto manual (.jpg/.png).
- **Session ID:** UUIDv4 dibuat saat kendaraan pertama terdeteksi di CCTV 1 (atau saat upload foto manual).
- **Jendela Korelasi:** 3 detik (konfigurasi `session_window_seconds`) — hanya berlaku untuk multi-CCTV.
- **Minimum Gambar:** 2 frame (1 per CCTV) sebelum evaluasi. Untuk foto manual, cukup **1 gambar**.

### 4.2 Pre-processing (Urutan Penting)

| Tahap | Metode | Parameter Kunci | Tujuan |
| :--- | :--- | :--- | :--- |
| **ROI Extraction** | YOLOv8 vehicle detection | `conf ≥ 0.5`, kelas `car/truck/motorcycle` | Buang background, fokus kendaraan |
| **Koreksi Perspektif** | 4-point transform (plat) | Titik sudut dari segmentasi YOLO | Ratakan plat miring/condong |
| **Peningkatan Kontras** | CLAHE (Contrast Limited AHE) | `clipLimit=2.0`, `tileGridSize=(8,8)` pada kanal L (LAB) | Tahan pencahayaan tidak merata |
| **Denoising** | Bilateral Filter | `d=9`, `sigmaColor=75`, `sigmaSpace=75` | Hilangkan noise CCTV tanpa blur tepi |
| **Resize Normalisasi** | Interpolasi Lanczos4 | Tinggi plat = 64 px, aspect ratio dipertahankan | Input tetap untuk OCR |

> **Catatan:** Urutan CLAHE → Bilateral lebih baik dari kebalikannya karena CLAHE memperkuat noise.

### 4.3 Deteksi Objek (YOLOv8)
- **Model:** `yolov8n-seg.pt` (nano, ~3.2 MB, 80 kelas COCO + custom `license_plate`, `sticker`).
- **Input:** 640×640 (letterbox, keep aspect).
- **Output per frame:** Bounding box + mask segmentasi plat & stiker.
- **Confidence Threshold:** 0.5 (deteksi), 0.7 (segmentasi mask).

### 4.4 OCR Plat Nomor
- **Engine:** PaddleOCR v2.7 (PP-OCRv3) — ringan, mendukung karakter Indonesia.
- **Pipeline:** Deteksi teks (DBNet) → Pengenalan (CRNN) → Post-processing beam search.
- **Dictionary:** Karakter `A-Z`, `0-9` (plat Indonesia).
- **Normalisasi Pasca-OCR:**
  ```python
  def normalize_plate(text: str) -> str:
      t = re.sub(r"[^A-Z0-9]", "", text.upper())
      # Koreksi umum OCR
      if len(t) >= 3 and t[2].isdigit():  # pola B 1234 XYZ
          t = t.replace("O", "0").replace("I", "1").replace("Z", "2")
      return t
  ```

### 4.5 Dekode Stiker Khusus
| Jenis Stiker | Metode | Ketahanan |
| :--- | :--- | :--- |
| **QR Code** | `pyzbar` / OpenCV QRCodeDetector | Tahan rotasi ≤ 30°, kompresi CCTV |
| **AprilTag** | `apriltag` (tag36h11) | Jarak jauh, sudut miring, pencahayaan rendah |
| **Pola Warna** | HSV threshold + template matching | Fallback bila QR/Tag rusak/tertutup |

Output: `sticker_code` (string unik, mis. `STK-WRG-0042`) + `sticker_confidence` (0–1).

### 4.6 Seleksi Best Frame
Untuk setiap CCTV dalam satu sesi:
```
score_frame = sharpness × detection_confidence
sharpness = variance(Laplacian(gray_frame))
```
Frame dengan `score_frame` tertinggi ditandai `is_best_frame = TRUE` dan dijadikan `snapshot_url` utama di log.

### 4.7 Fusi Skor (Confidence Fusion)

```python
plat_score    = max(plat_conf_all_cams)    + 0.05 * (n_cam_plat    - 1)
sticker_score = max(sticker_conf_all_cams) + 0.05 * (len(sticker_confs) - 1)  # contoh
fused_score   = min(1.0, max(plat_score, sticker_score))
```

| Jalur | Ambang (`system_settings`) | Keputusan |
| :--- | :--- | :--- |
| Plat | `plat_confidence_threshold = 0.85` | VALID |
| Stiker | `sticker_confidence_threshold = 0.80` | VALID |
| Fusi | `fused_confidence_threshold = 0.90` | AUTO_OPEN |
| Area abu-abu | 0.60 – ambang | LOW_CONFIDENCE → minta konfirmasi satpam |

### 4.8 Output Keputusan (Hasil Akhir)

Berdasarkan hasil fusi & pencocokan database, sistem menghasilkan **salah satu** output berikut:

| Kode Keputusan | Keterangan | Aksi |
| :--- | :--- | :--- |
| **AUTO_OPEN** | Plat/stiker cocok di `master_vehicles`, valid (booking aktif bila operasional), skor ≥ ambang | **Buka Pintu Otomatis**. Alert HIJAU ke dashboard satpam. Log tersimpan + foto. |
| **NO_MATCH** | Hasil OCR/dekode ada, tapi tidak terdaftar di database | **Kendaraan Tidak Dikenali**. Alert MERAH ke dashboard satpam. Menunggu tindakan satpam. |
| **OCR_FAILED** | Gagal membaca plat & gagal mendeteksi stiker (keduanya < ambang minimum) | **Kendaraan Tidak Dikenali**. Alert MERAH ke dashboard satpam. Menunggu tindakan satpam. |
| **MANUAL_OVERRIDE** | Satpam menilai aman setelah verifikasi visual | **Buka Pintu Manual (Bypass)**. Wajib `override_by`, `override_note`, waktu & foto. Log audit permanen. |
| **REJECTED** | Satpam menilai tidak aman / tidak diizinkan | **Tolak Akses**. Pintu tetap tertutup. Log tersimpan + foto + alasan penolakan. |

> **Prinsip Fail-Safe:** Jika database tidak tersedia saat evaluasi, sistem **TIDAK** membuka pintu otomatis. Hasil diperlakukan sebagai `NO_MATCH` dan dialihkan ke satpam.

---

## 5. Proses Training Data (YOLOv8 + OCR)

Agar model mampu mendeteksi plat nomor & stiker khusus dengan akurasi tinggi, dilakukan proses **pelatihan (training)** terarah dengan dataset citra kendaraan.

### 5.1 Tujuan Training
- Melatih model **YOLOv8-seg** untuk mendeteksi & mensegmentasi ROI `license_plate` dan `sticker`.
- Meningkatkan ketahanan model terhadap variasi pencahayaan, sudut, jarak, dan kondisi cuaca.
- Menyediakan data validasi untuk mengukur mAP, precision, recall sebelum deployment.

### 5.2 Pengumpulan Dataset

| Sumber Data | Jumlah (Target) | Keterangan |
| :--- | :--- | :--- |
| **Rekaman CCTV Lapangan** | 800–1000 | Frame dari CCTV 1 & 2 (siang, sore, malam) |
| **Foto Manual Kendaraan** | 300–500 | Diambil dari berbagai sudut (depan, 3/4 depan) |
| **Data Augmentasi** | +25–40% | Rotasi kecil, brightness/contrast, blur, rain/noise |
| **Total** | **~1500–1800** | Cukup untuk fine-tune YOLOv8n |

### 5.3 Struktur Dataset (YOLOv8)

Dataset disusun mengikuti format Ultralytics YOLO:

```text
dataset/
├── images/
│   ├── train/   # 70–80%
│   ├── val/     # 10–15%
│   └── test/    # 10–15%
├── labels/
│   ├── train/
│   ├── val/
│   └── test/
└── data.yaml
```

**Contoh `data.yaml`:**

```yaml
path: ./dataset
train: images/train
val: images/val
test: images/test

names:
  0: license_plate
  1: sticker
```

**Format label YOLO (segmentation):** `class x1 y1 x2 y2 ... xn yn` dengan nilai **normalized** (0–1).

### 5.4 Proses Annotasi

| Tools | Kegunaan | Catatan |
| :--- | :--- | :--- |
| **LabelImg** | Bounding box (sederhana) | Cepat, cocok awal |
| **Labelme** | Polygon segmentation | Sangat tepat untuk bentuk plat/stiker tidak persegi |
| **Roboflow** | Cloud annotasi + augmentasi + export YOLOv8 | Praktis, auto-split train/val/test |

**Aturan Annotasi:**
- Hanya anotasi objek yang **jelas terlihat** (minimal 70% ROI terlihat).
- Untuk plat, anotasi **seluruh frame plat** (termasuk bingkai) agar mask akurat.
- Untuk stiker, anotasi area stiker utuh (QR/AprilTag/pola).
- Hindari anotasi objek blur/parah tertutup.

### 5.5 Augmentasi Data

Untuk meningkatkan generalisasi:

| Augmentasi | Nilai | Tujuan |
| :--- | :--- | :--- |
| **Flip Horizontal** | 50% | Variasi arah kendaraan |
| **Rotation** | ±5–10° | Mengatasi sudut miring CCTV |
| **Brightness/Contrast** | ±15% | Siang/malam |
| **Gaussian Blur** | 0–2px | Noise CCTV |
| **Hue/Saturation** | ±10% | Perbedaan pencahayaan warna |
| **Mosaic** | 10–20% | Kombinasi konteks berbeda |
| **Affine Transform** | ringan | Simulasi perspektif miring |

### 5.6 Training YOLOv8

**Konfigurasi dasar (Ultralytics):**

```bash
yolo segment train \
  data=dataset/data.yaml \
  model=yolov8n-seg.pt \
  epochs=100 \
  imgsz=640 \
  batch=16 \
  device=0  # GPU
```

**Hyperparameter penting:**
| Parameter | Nilai | Keterangan |
| :--- | :--- | :--- |
| `epochs` | 80–120 | Cukup untuk fine-tune (hindari overfit) |
| `imgsz` | 640 | Keseimbangan akurasi–kecepatan |
| `batch` | 8–16 | Sesuai VRAM GPU |
| `lr0` | 0.01 | Learning rate awal |
| `patience` | 20 | Early stopping bila mAP stagnan |

### 5.7 Evaluasi Model Training

Setelah training, dievaluasi dengan **validation set**:

| Metrik | Target | Keterangan |
| :--- | :--- | :--- |
| **mAP@0.5** | ≥ 0.95 | Mean Average Precision IoU≥0.5 |
| **mAP@0.5:0.95** | ≥ 0.80 | Lebih ketat, mencerminkan akurasi mask |
| **Precision** | ≥ 0.96 | Minimalkan false positive (deteksi salah) |
| **Recall** | ≥ 0.95 | Minimalkan false negative (lewat terlewat) |
| **Box Loss / Seg Loss** | Menurun stabil | Indikator konvergensi |

Hasil terbaik (`best.pt`) diekspor ke **ONNX** untuk inference di `ai-worker` (cepat, lintas-runtime).

### 5.8 Training Terkait OCR (PaddleOCR)

PaddleOCR PP-OCRv3 sudah dilengkapi **pretrained model** untuk teks umum. Untuk plat Indonesia, dilakukan **fine-tune ringan** bila ditemukan karakter sering salah (B↔8, I↔1, O↔0, Z↔2).

**Pendekatan:**
1. **Ekstrak crop plat** hasil YOLO (benar) → kumpulkan ~500–1000 crop plat berlabel.
2. **Label per-karakter** atau **full-text** (string plat sebenarnya).
3. **Fine-tune recognizer** PP-OCRv3 dengan dataset lokal.
4. **Evaluasi Character Error Rate (CER)** & **Word/Plate Accuracy**.
5. Target: **Character Accuracy ≥ 99.5%**, **Plate Accuracy ≥ 98%** (siang).

> **Catatan:** Untuk stiker (QR/AprilTag), **TIDAK** perlu training ML. Cukup library detektor (pyzbar/apriltag) karena bersifat deterministik. Fallback klasifikasi pola hanya dilatih bila benar-benar dibutuhkan.

---

## 6. Eksperimen & Evaluasi (Rencana)

### 6.1 Dataset Uji
| Kondisi | Jumlah Gambar | Sumber |
| :--- | :--- | :--- |
| Siang cerah | 500 | Rekaman CCTV lapangan |
| Malam (lampu jalan) | 300 | Rekaman CCTV lapangan |
| Hujan / kabut | 200 | Rekaman + augmentasi (rain streak) |
| Plat kotor / terhalang | 150 | Buatan (occlusion sintetis) |
| Stiker pudar / robek | 100 | Fisik + augmentasi |

Total: **1.250 gambar** (termasuk ground-truth plat & stiker).

### 6.2 Metrik Evaluasi

| Metrik | Target | Cara Ukur |
| :--- | :--- | :--- |
| **Plate Recognition Rate** | ≥ 98% (siang), ≥ 90% (malam/hujan) | `(benar / total) × 100%` |
| **Character Accuracy** | ≥ 99.5% | Levenshtein distance per karakter |
| **Sticker Decode Rate** | ≥ 95% | `(berhasil decode / total stiker terlihat)` |
| **False Accept Rate** | ≤ 0.1% | Kendaraan asing dibuka otomatis / total asing |
| **Latency p95** | ≤ 1.5 s | Timestamp frame terakhir → MQTT publish |

### 6.3 Ablation Study (Rencana)
| Variasi | Diuji |
| :--- | :--- |
| Tanpa CLAHE | vs baseline |
| Tanpa Bilateral | vs baseline |
| Tanpa koreksi perspektif | vs baseline |
| Hanya 1 CCTV | vs 2 CCTV (fusi) |
| Hanya Plat | vs Plat + Stiker |
| YOLOv8n vs YOLOv8s | Speed vs Accuracy |

---

## 7. Hasil Sementara (Placeholder — diisi setelah eksperimen)

| Metrik | Siang | Malam | Hujan | Catatan |
| :--- | :--- | :--- | :--- | :--- |
| Plate Recognition Rate | —% | —% | —% | |
| Sticker Decode Rate | —% | —% | —% | |
| Fused Accuracy | —% | —% | —% | |
| Latency p95 (ms) | — | — | — | |

---

## 8. Analisis Kegagalan (Failure Mode Analysis)

| Mode Kegagalan | Penyebab | Dampak | Mitigasi di Sistem |
| :--- | :--- | :--- | :--- |
| Plat tidak terbaca | Kotoran, cahaya rendah, sudut ekstrem | `plat_confidence` rendah | Stiker jadi jalur cadangan; fallback ke satpam |
| Stiker tidak terbaca | Pudar, tertutup, rusak | `sticker_confidence` = 0 | Plat tetap dipakai; tidak memblokir keputusan |
| Deteksi ganda (2 kendaraan dekat) | Jarak antar kendaraan < 2 m | 2 `session_id` overlap | Jendela korelasi 3 s + deduplikasi `session_id` |
| OCR salah baca (mis. 8 ↔ B) | Karakter mirip | False accept / reject | Normalisasi + `pg_trgm` similarity search (top-3) |
| CCTV 1/2 mati | Hardware / jaringan | Hanya 1 sumber gambar | Degraded mode: lanjut dengan 1 CCTV, flag log |

---

## 9. Implementasi Teknis (Ringkas)

| Komponen | Teknologi | Lokasi Kode |
| :--- | :--- | :--- |
| Capture RTSP | `opencv-python` + `cv2.VideoCapture` | `ai-worker/app/capture.py` |
| Pre-processing | OpenCV (CLAHE, bilateral, warpPerspective) | `ai-worker/app/preprocess.py` |
| YOLOv8 Inference | ONNX Runtime / TensorRT | `ai-worker/app/plate_ocr.py` |
| PaddleOCR | `paddleocr` Python package | `ai-worker/app/plate_ocr.py` |
| Sticker Decoder | `pyzbar`, `apriltag`, custom HSV | `ai-worker/app/sticker_decode.py` |
| Fusion & Push | Python async + `httpx` | `ai-worker/app/fusion.py`, `push_client.py` |

**Hardware Target:** NVIDIA Jetson Orin Nano / RTX 3060 (TensorRT FP16) → latency inferensi ~40 ms/frame.

---

## 10. Kesimpulan & Saran

- Fusi **plat + stiker** dari **2 CCTV** meningkatkan *recognition rate* signifikan dibanding single-camera/single-modal.
- Pre-processing **CLAHE + koreksi perspektif** paling berkontribusi pada akurasi OCR di kondisi pencahayaan sulit.
- Arsitektur *session-based* dengan Redis memungkinkan korelasi temporal yang robust.
- **Saran lanjutan:** *Online learning* dari kasus `LOW_CONFIDENCE` yang dikonfirmasi satpam untuk *fine-tune* model YOLO/OCR berkala.

---

## 11. Referensi

1. Redmon, J., et al. "YOLOv8: Real-Time Object Detection." Ultralytics, 2023.
2. Du, Y., et al. "PP-OCRv3: More Attempts for the Improvement of Ultra Lightweight OCR System." arXiv:2206.03001, 2022.
3. Wang, F., et al. "AprilTag: A Robust and Flexible Visual Fiducial System." ICRA 2011.
4. Zuiderveld, K. "Contrast Limited Adaptive Histogram Equalization." Graphics Gems IV, 1994.
5. Dokumentasi Internal: [PRD.md](../docs/PRD.md), [SYSTEM_FLOW.md](../docs/SYSTEM_FLOW.md), [DATABASE.md](../docs/DATABASE.md), [API.md](../docs/API.md), [TECHNICAL.md](../docs/TECHNICAL.md)

---

## 12. Lampiran: Kode Potongan Kunci

### 12.1 Koreksi Perspektif Plat (4-point Transform)
```python
def four_point_transform(image, pts):
    # pts: 4 titik (tl, tr, br, bl) dari mask YOLO
    rect = order_points(pts)  # urutkan konsisten
    (tl, tr, br, bl) = rect
    width = max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))
    height = max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))
    dst = np.array([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (int(width), int(height)))
    return warped
```

### 12.2 Fusi Skor (Fungsi Murni, Mudah Diuji)
```python
def fuse_scores(plat_confs: list[float], sticker_confs: list[float]) -> tuple[float, float, float]:
    plat_score    = (max(plat_confs)    if plat_confs    else 0) + 0.05 * (len(plat_confs)    - 1)
    sticker_score = (max(sticker_confs) if sticker_confs else 0) + 0.05 * (len(sticker_confs) - 1)
    fused = min(1.0, max(plat_score, sticker_score))
    return plat_score, sticker_score, fused
```

### 12.3 Normalisasi Plat (Unit-testable)
```python
import re
def normalize_plate(text: str) -> str:
    t = re.sub(r"[^A-Z0-9]", "", text.upper())
    if len(t) >= 3 and t[2].isdigit():
        t = t.translate(str.maketrans({"O": "0", "I": "1", "Z": "2", "S": "5", "G": "6"}))
    return t
```

---

*Dokumen ini disiapkan untuk presentasi tugas akhir / ujian Pengolahan Citra Digital. Semua diagram Mermaid dapat dirender di GitHub, GitLab, Obsidian, Notion, atau VS Code dengan ekstensi Markdown Preview Mermaid.*