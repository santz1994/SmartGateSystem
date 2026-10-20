# Panduan Training Smart Gate System

Dokumen ini menjelaskan dataset, training detektor plat nomor, evaluasi OCR, dan
cara memasang model ke prototype Flask. Perintah pada contoh dijalankan dari
folder `prototype/`.

## 1. Komponen Dataset

### Dataset lokal

| Folder | Format | Isi | Kegunaan |
| --- | --- | --- | --- |
| `plat-nomor/` | YOLO detection | 393 train, 84 valid, 84 test | Sumber deteksi awal |
| `datasets/detection/` | COCO | 1.377 gambar dan 2.128 anotasi | Dikonversi ke YOLO |
| `datasets/text/` | CSV + crop | 1.863 crop dengan `label.csv` | Evaluasi/pengembangan OCR |
| `dataset_merged/` | YOLO detection | train 1.572, valid 290, test 84 | Dataset training utama |
| `dataset_extra/` | Gambar web | 13 positif dan 2 negatif terakhir | Data tambahan, bukan ground truth utama |

`dataset_merged/data.yaml` saat ini hanya memiliki satu kelas:

```yaml
nc: 1
names: ['number-plate']
```

Model deteksi yang tersedia saat ini mendeteksi plat nomor. Stiker masih
diproses oleh pipeline stiker/fallback dan belum menjadi kelas YOLO terpisah.
Jika stiker akan dilatih, anotasi stiker harus ditambahkan secara konsisten
terlebih dahulu.

### Mengonversi dan menggabungkan data

Konversi COCO ke YOLO:

```powershell
python tools/convert_coco_to_yolo.py
```

Dataset hasil konversi berada di `datasets/detection/yolo_format/`. Saat
menggabungkan dataset, pastikan nama file tidak bentrok, setiap gambar memiliki
label dengan nama yang sama, dan split validasi/test tidak bocor ke train.

### Data dari internet

`tools/fetch_samples.py` mengambil contoh dari Wikimedia Commons, menyimpan
atribusi, dan memisahkan data positif (plat Indonesia) dari data negatif
(bukan plat). Jalankan dengan:

```powershell
python tools/fetch_samples.py
```

Periksa hasil manual sebelum dipakai training. Data web dapat memiliki lisensi,
resolusi, framing, atau label yang tidak sesuai. Daftar sumber dan lisensi wajib
dipertahankan di [`dataset_extra/SOURCES.md`](dataset_extra/SOURCES.md).
Jangan menggunakan gambar berhak cipta tanpa izin atau menghapus atribusinya.

## 2. Anotasi dan Augmentasi

Anotasi menggunakan format YOLO detection:

```text
class_id center_x center_y width height
```

Semua koordinat dinormalisasi ke 0--1. Kotak mencakup seluruh bidang plat,
bukan hanya beberapa karakter. Data dengan plat sangat terpotong, tertutup,
atau tidak dapat diverifikasi diberi label `bad`/dikeluarkan dari validasi,
bukan dipaksa menjadi label positif.

Augmentasi yang relevan:

- perubahan brightness/contrast dan HSV untuk siang, malam, dan lampu gate;
- blur ringan dan noise untuk simulasi CCTV;
- rotasi/perspektif kecil untuk kamera miring;
- crop dan resize yang mempertahankan karakter plat;
- pantulan/silau hanya sebagai variasi tambahan, bukan pengganti foto nyata.

Hindari flip vertikal, distorsi ekstrem, atau augmentasi yang membuat bentuk
plat tidak realistis. Pisahkan kendaraan yang sama antar split agar metrik tidak
terlihat tinggi karena kebocoran frame.

## 3. Training YOLO

### GPU/Colab

```powershell
pip install ultralytics
python train_yolo.py --data dataset_merged/data.yaml --epochs 50 `
  --imgsz 640 --batch 16 --device 0 --name smartgate-gpu
```

### CPU lokal

```powershell
python train_yolo.py --data dataset_merged/data.yaml --epochs 15 `
  --imgsz 416 --batch 8 --device cpu --patience 5 --name smartgate
```

CPU pada laptop i5-8250U berjalan sangat lambat. Untuk training panjang,
gunakan GPU. `best.pt` dipilih berdasarkan metrik validasi, bukan sekadar epoch
terakhir.

Pelatihan berhenti otomatis lewat dua mekanisme: `patience` (berhenti bila
mAP50 tidak membaik) dan `--target-map50` (default `0.98`, nonaktifkan dengan
`0`) yang menghentikan training segera setelah target mAP50 tercapai —
mencegah overfitting sekaligus menghemat waktu komputasi. Notebook
`plat-nomor/a.ipynb` memakai mekanisme yang sama (`TARGET_MAP50 = 0.98`,
callback `on_fit_epoch_end`).

### Hasil yang sudah tercatat

Run **V5 `smartgate-colab-v5`** (Colab, YOLOv8n, 50 epoch, dataset gabungan
Roboflow + Kaggle COCO + background dengan anti-leakage) adalah run aktif saat
ini. Ringkasan lengkap ada di `runs/detect/smartgate-colab-v5/evaluation_summary.json`:

| Metrik | Nilai |
| --- | ---: |
| Validation mAP50 | 0,8938 |
| Validation mAP50-95 | 0,5339 |
| Test mAP50 | 0,9491 |
| Test mAP50-95 | 0,5999 |
| Valid format rate OCR (V4 parser) | 73,95% (88/119 plat) |
| Latency rata-rata / P95 | 98,22 ms / 176,99 ms |

Run lama yang masih tersimpan (baseline historis, jangan dipakai untuk klaim):

- `smartgate` (15 epoch, `imgsz=416`, CPU): precision 0,714; recall 0,668; mAP50 0,716; mAP50-95 0,435.
- `smartgate-full` (4 epoch, belum final): mAP50 sementara 0,6671.

Artefak training:

```text
runs/detect/smartgate-colab-v5/      # run aktif (V5)
├── results.csv
├── evaluation_summary.json
├── confusion_matrix.png
└── weights/best.pt, best.onnx
runs/detect/runs/detect/smartgate/   # baseline lama
runs/detect/runs/detect/smartgate-full/
```

Halaman [`/training`](http://localhost:5001/training) menampilkan status epoch,
loss, precision, recall, mAP, plot yang tersedia, serta metrik evaluasi terbaru
dari `evaluation_summary.json`. Halaman otomatis memilih run dengan
`results.csv` paling baru.

## 4. Evaluasi

Validasi detektor:

```powershell
yolo val model=runs/detect/smartgate-colab-v5/weights/best.pt `
  data=dataset_merged/data.yaml
```

Evaluasi pipeline OCR:

```powershell
python tools/eval_real.py --part both --limit 200
```

Laporkan sedikitnya precision, recall, mAP50, mAP50-95, plate accuracy,
character error rate (CER), dan latency. Bedakan metrik deteksi dari metrik
OCR: mAP tidak berarti teks plat pasti terbaca benar.

## 5. Memakai Bobot di Prototype

```powershell
$env:SGS_YOLO_WEIGHTS = "D:\Project\Smart Gate System\Tugas Citra Digital\prototype\runs\detect\smartgate-colab-v5\weights\best.pt"
python run.py
```

Jika `SGS_YOLO_WEIGHTS` tidak diisi, prototype otomatis memakai bobot terbaru
dengan urutan `runs/detect/smartgate-colab-v5`, lalu `runs/detect/runs/detect/smartgate`,
lalu `smartgate-full`. Hasil YOLO tetap melewati
gerbang confidence, rasio plat, tekstur, dan jumlah glyph; kotak yang hanya
menyerupai gril/emblem tidak diteruskan ke OCR.

Jalur YOLO hanya menerima `class_id=0` karena dataset saat ini hanya memiliki
kelas `number-plate`. Kandidat juga wajib memiliki rasio lebar/tinggi 1,4--5,0
dan luas maksimal 20% frame. Rentang ini menjaga plat motor (sekitar 1,5--3,2)
tetap diterima, tetapi menolak box bodi motor atau box yang terlalu memanjang.
NMS YOLO tetap digunakan, lalu kandidat diurutkan berdasarkan confidence
sebelum jumlah kandidat dibatasi.

Pada webcam, detector secara default hanya memproses ROI bawah
`0.05,0.35,0.95,1.0` (x1,y1,x2,y2) untuk mengurangi false positive jaket/wajah.
ROI dapat dikalibrasi dengan `SGS_DETECTION_ROI`. Koreksi gamma `1.15` dan
CLAHE ringan diterapkan khusus pada input detector; gambar asli tetap dipakai
untuk snapshot dan crop OCR. Nilai gamma dapat diatur lewat
`SGS_DETECTION_GAMMA` (nilai lebih besar menggelapkan frame overexposed).

Periksa `http://localhost:5001/api/health`. Backend harus menunjukkan `yolo`
bila bobot berhasil dimuat. Jika bobot tidak tersedia, prototype memakai
deteksi klasik OpenCV sebagai fallback; fallback ini lebih rentan terhadap
silau, pantulan monitor, dan objek terang di background.

## 6. Pipeline OCR Setelah Deteksi

Deteksi plat tidak langsung membuka gate. Crop kandidat diproses melalui:

1. ROI dan pemilihan kendaraan terdekat;
2. `drop_swallowed` dan deduplikasi kandidat;
3. deglare, CLAHE, morphology, upscale, dan unsharp mask;
4. PaddleOCR recognizer-only (EasyOCR menjadi fallback bila PaddleOCR belum terpasang) dengan allowlist `A-Z0-9`;
5. padding crop 8% horizontal/12% vertikal, retry deglare, adaptive threshold, dan dua ukuran enhancement;
6. voting/cache hasil OCR dan validasi struktur NRKB.

Retry dibatasi dan model di-warm-up agar latency tidak membengkak. Test pipeline
terakhir mencakup normalisasi NRKB, ROI, pemilihan kendaraan, retry OCR, dan
fusi hasil.

Aturan NRKB digunakan sebagai **skor tambahan**, bukan kebenaran tunggal:

- prefix 1--3 huruf;
- nomor urut 1--4 digit dan digit pertamanya bukan `0`;
- suffix 0--3 huruf;
- konteks posisi membedakan `B/8`, `6/G`, `1/I`, `O/0`, `I/1`, `L/1`, `S/5`, `T/7`, `A/4`, `D/0`, `V/U`, `W/VV`, `X/XX`, `Z/2`;
- koreksi blok prefix (`_PREFIX_FIX`): `0/1/O/I/L` → `D`, `8` → `B`, plus bonus
  skor untuk kode wilayah valid di `VALID_PREFIXES` — mis. `005877US` →
  `DD5877US` (plat Makassar), dan blok angka diawali `0` dikenai penalti karena
  NRKB tak pernah mulai dari `0`.

Referensi struktur nomor: [Bapenda Jawa Barat](https://bapenda.jabarprov.go.id/2017/10/24/kenali-penomoran-kendaraan-bermotor/).

## 7. Pantulan dan Kasus Sulit

`deglare` melakukan inpainting pada highlight yang jenuh lalu CLAHE. Nilai
`SGS_CLAHE_CLIP_LIMIT` dapat diturunkan untuk menekan moire layar. Ini
membantu pantulan lampu, tetapi tidak menjamin keberhasilan ketika kamera
merekam foto kendaraan dari layar monitor. Moire, perspektif layar, dan
fragmen karakter dapat membuat satu plat terpecah menjadi beberapa kontur.

Untuk deployment:

- kalibrasikan ROI per kamera;
- gunakan YOLO sebagai detector utama;
- ambil foto kendaraan langsung, bukan foto dari monitor;
- simpan frame gagal yang sudah dikonfirmasi satpam sebagai data evaluasi;
- jangan menurunkan ambang sampai sistem membuka kendaraan yang salah.

## 8. Checklist Sebelum Deployment

- [ ] Tidak ada duplikasi kendaraan antar train/valid/test.
- [ ] Semua gambar valid memiliki label yang benar.
- [ ] Data web memiliki atribusi dan sudah ditinjau manual.
- [ ] `best.pt` berasal dari run yang selesai dan tervalidasi.
- [ ] Precision/false accept diuji pada kendaraan yang tidak terdaftar.
- [ ] ROI dan ukuran minimum dikalibrasi untuk kamera gate.
- [ ] Gagal OCR menghasilkan alert satpam, bukan auto-open.
- [ ] Snapshot dan keputusan tersimpan di audit log.
