# Smart Gate System — Prototype (`Tugas Citra Digital/prototype`)

Prototipe aplikasi **Smart Gate System** berbasis Flask, Ultralytics **YOLOv8n / YOLOv11n**, dan **PaddleOCR / EasyOCR** dengan parser struktur **TNKB & NRKB sesuai Peraturan Kepolisian (Perpol) Nomor 7 Tahun 2021**.

---

## 1. Benchmark Model Detektor & OCR (v6 Multi-Domain Fold 0)

Kedua model dilatih di Google Colab (GPU Tesla T4, 50 epoch, `seed=42`) menggunakan **5-Fold Stratified Group Cross-Validation (Fold 0: ~3.253 citra train : ~813 citra val multi-domain dengan anti-leakage `dHash` 64-bit + SHA-256)** dan regularisasi anti-degradasi (`ANTI_DEGRADATION_HYPS`):

| Metrik Evaluasi | YOLOv8n (`smartgate-colab-v6-yolov8n`) | YOLOv11n (`smartgate-colab-v6-yolo11n`) |
| :--- | ---: | ---: |
| **Bobot `.pt` / `.onnx`** | `6,48 MB` / `12,77 MB` | **`5,48 MB` / `10,66 MB`** |
| **Validation Fold 0 mAP50** *(multi-domain)* | **`0,8488`** | `0,8464` |
| **Validation Fold 0 mAP50-95** *(multi-domain)* | `0,5669` | **`0,5686`** |
| **Test Hold-out mAP50** *(84 citra)* | `0,9617` | **`0,9693`** |
| **Test Hold-out mAP50-95** *(84 citra)* | `0,5931` | **`0,6150`** |
| **End-to-End OCR Valid Format Rate** | **`75,96%` (`79/104`)** | `74,07%` (`80/108`) |
| **Latency End-to-End Rata-rata / P95** | **`76,50 ms` / `157,19 ms`** | `87,43 ms` / `161,03 ms` |

### Penempatan Bobot Model (`runs/detect/` & `smartgate-artifacts-*/`)

Aplikasi secara otomatis menggunakan bobot hasil training v6 (`YOLO_MODEL_PATH` di [`app/config.py`](app/config.py) dan `VARIANTS` / `ARTIFACT_FALLBACKS` di [`app/detect_yolo.py`](app/detect_yolo.py)) tanpa bergantung pada model v5 lama:
1. `runs/detect/smartgate-colab-v6-yolo11n/weights/best.pt` (atau langsung dari `../../smartgate-artifacts-Y11N/best.pt`)
2. `runs/detect/smartgate-colab-v6-yolov8n/weights/best.pt` (atau langsung dari `../../smartgate-artifacts-Y8N/best.pt`)

Untuk menyalin bobot beserta `evaluation_summary.json`, `results.csv`, dan `confusion_matrix.png` dari folder/ZIP artefak Colab di root repositori (`smartgate-artifacts-Y11N` dan `smartgate-artifacts-Y8N`), jalankan:

```powershell
python tools\fetch_weights.py
```

Varian model aktif (`yolo11n` atau `yolov8n`) dapat diganti langsung saat runtime melalui halaman **`/training`** atau variabel lingkungan `SGS_YOLO_VARIANT=yolo11n`.

---

## 2. Menjalankan Aplikasi & Pengujian

```powershell
# Jalankan server prototipe
python run.py

# Jalankan suite regresi otomatis (133 pemeriksaan)
python tests\test_pipeline.py
```

Lihat panduan training lengkap di [`../../docs/TRAINING_GUIDE.md`](../../docs/TRAINING_GUIDE.md) dan laporan tugas di [`../../docs/TUGAS_PENGOLAHAN_CITRA_DIGITAL.md`](../../docs/TUGAS_PENGOLAHAN_CITRA_DIGITAL.md).
