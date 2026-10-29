# Technical Document — Enterprise Smart Gate System

> **Catatan lingkup:** Fitur stiker QR dan RFID dalam dokumen ini adalah
> **rencana pengembangan mendatang / bahan skripsi**. Lingkup prototipe saat ini:
> pengenalan plat nomor (YOLOv8 + aturan NRKB + keputusan fail-safe).

Referensi: [PRD.md](PRD.md) · [DATABASE.md](DATABASE.md) · [SYSTEM_FLOW.md](SYSTEM_FLOW.md) · [API.md](API.md)

---

## 1. Arsitektur Sistem

```mermaid
flowchart LR
    subgraph EDGE["Edge / Lapangan"]
        C1["CCTV 1 - Pendekatan"]
        C2["CCTV 2 - Gate"]
        ESP["ESP32 + Relay"]
        MOT["Motor Gate"]
        RD["RFID Reader (opsional)"]
    end

    subgraph SRV["Server Lokal (Proxmox - Docker)"]
        AI["AI Inference Container\nYOLOv8 + OCR + Sticker Decoder"]
        BE["Backend FastAPI"]
        MQ["MQTT Broker (Mosquitto)"]
        RDIS["Redis (state sesi)"]
        DB[("PostgreSQL 16")]
        WK["Worker / Scheduler"]
    end

    subgraph NAS["NAS / Storage"]
        FS["Snapshot + Model + Backup"]
    end

    subgraph CLIENT["Client"]
        DASH["Dashboard Satpam (Web)"]
        ADM["Panel Admin"]
    end

    C1 -- RTSP --> AI
    C2 -- RTSP --> AI
    RD -. MQTT .-> MQ
    AI -- HTTP push --> BE
    BE -- SQL --> DB
    BE -- state --> RDIS
    BE -- publish cmd --> MQ
    MQ -- MQTT --> ESP
    ESP --> MOT
    AI -- simpan gambar --> FS
    BE -- simpan gambar --> FS
    WK -- retensi/backup --> DB
    WK --> FS
    DASH -- HTTPS + WS --> BE
    ADM -- HTTPS --> BE
```

Prinsip: **seluruh jalur kritis on-premise**. Kegagalan internet eksternal tidak menghentikan operasi gerbang.

---

## 2. Stack Teknologi

| Lapisan | Teknologi | Alasan |
| :--- | :--- | :--- |
| Deteksi objek | YOLOv8 (Ultralytics) | Akurat, ringan, bisa di-*export* ke ONNX/TensorRT |
| OCR plat | PaddleOCR / EasyOCR (kandidat benchmark) | Dukungan karakter Indonesia + angka |
| Dekode stiker | Detektor QR/AprilTag + klasifikasi warna/pola | Tahan kompresi CCTV, cepat |
| Inference runtime | ONNX Runtime / TensorRT (GPU bila ada) | Latensi rendah, deterministik |
| Backend | FastAPI (Python 3.11) | Async, WebSocket native, Pydantic validation |
| Broker | Mosquitto (MQTT 3.1.1/5) | Ringan, cocok untuk ESP32 |
| State sesi | Redis 7 | TTL jendela sesi, counter gambar |
| Database | PostgreSQL 16 | JSONB, trigram, constraint |
| Antrean | Celery + Redis (opsional) | Job retensi, backup, export laporan |
| Frontend | React + Vite + TailwindCSS | Dashboard satpam + panel admin |
| Realtime | WebSocket (`/ws/alerts`) | Alert < 1 detik |
| Kontainer | Docker Compose di Proxmox LXC/VM | Portabilitas, mudah di-restart |
| Reverse proxy | Nginx / Caddy | TLS internal, sertifikat self-signed |
| Monitoring | Prometheus + Grafana + Loki | Latensi, akurasi, status perangkat |

---

## 3. Struktur Repositori (usulan)

```
smart-gate-system/
├─ docker-compose.yml
├─ .env.example
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/          # config, security, logging
│  │  ├─ api/v1/        # routers: auth, detection, gate, vehicles, bookings, logs, devices, settings
│  │  ├─ models/        # SQLAlchemy ORM
│  │  ├─ schemas/       # Pydantic
│  │  ├─ services/      # matching.py, decision.py, snapshot.py, mqtt_publisher.py
│  │  └─ ws/            # connection manager & broadcaster
│  ├─ alembic/          # migrasi database
│  └─ tests/
├─ ai-worker/
│  ├─ app/
│  │  ├─ capture.py     # baca RTSP dari CCTV 1 & 2
│  │  ├─ preprocess.py  # deskew, denoise, contrast, best-frame
│  │  ├─ plate_ocr.py
│  │  ├─ sticker_decode.py
│  │  ├─ fusion.py
│  │  └─ push_client.py # POST /detection/push
│  └─ tests/
├─ firmware/
│  └─ esp32-gate/       # Arduino/PlatformIO: MQTT client, relay, sensor
├─ frontend/
│  ├─ src/pages/        # Dashboard, Logs, Vehicles, Bookings, Devices, Settings
│  └─ src/components/
├─ models/              # *.onnx / *.pt
└─ docs/                # opsional: salinan dokumen ini
```

---

## 4. Komponen & Tanggung Jawab

### 4.1 AI Inference Worker
- Membaca stream RTSP CCTV 1 & 2 secara paralel (`opencv-python` + buffer).
- Deteksi kendaraan → buat/gunakan `session_id` saat kendaraan masuk zona.
- Segmentasi ROI: area plat dan area stiker.
- Pengolahan citra: grayscale, CLAHE, *unsharp mask*, koreksi perspektif via 4 titik plat, *resize* ke tinggi tetap.
- Pilih *best frame* berdasarkan skor ketajaman (Laplacian variance) × *confidence* deteksi.
- Menjalankan OCR plat dan dekode stiker; mengirim hasil via `POST /detection/push`.
- Memanggil `POST /detection/session/close` saat jendela berakhir.

### 4.2 Backend FastAPI
- Menyimpan `detection_events` + menulis gambar ke NAS.
- Mengelola state sesi di Redis: kunci `session:{id}` dengan TTL = `session_window_seconds`.
- Evaluasi fusi lalu pencocokan database (`services/matching.py`).
- Menyusun keputusan (`services/decision.py`) dan menulis `gate_logs`.
- Menerbitkan MQTT `OPEN` ke gate dan menyiarkan alert WebSocket.
- Menyediakan seluruh REST API + WebSocket ([API.md](API.md)).

### 4.3 MQTT Broker + ESP32
- Backend publish `gate/{direction}/motor/cmd`.
- ESP32 (Arduino/PlatformIO): subscribe topik cmd, menyalakan relay dengan `duration_ms`, memantau sensor gate, mengirim `ack` + `sensor` + heartbeat.
- *Last Will and Testament* di set ke `OFFLINE` untuk mendeteksi perangkat mati.

### 4.4 Frontend Dashboard
- Halaman utama satpam: daftar alert realtime (HIJAU/MERAH), panel detail berisi semua snapshot CCTV 1 & 2, tombol **Bypass** dan **Tolak**.
- Panel admin: master kendaraan (plat + stiker), booking, perangkat, pengaturan ambang.
- Audio notifikasi berbeda untuk HIJAU dan MERAH.

---

## 5. Algoritma Inti

### 5.1 Pengolahan Citra
1. Ambil 5–10 *frame* terakhir per CCTV saat kendaraan ada di ROI; jalur live
   memproses 3–5 *frame* per detik (*frame skipping*).
2. Skor ketajaman: `sharpness = variance(Laplacian(gray))`.
3. Pilih *frame* dengan skor `sharpness × detect_conf` tertinggi.
4. Crop ROI deteksi **sebelum** pemrosesan berat; gamma + CLAHE hanya pada kotak
   ROI/plat, tidak pernah pada seluruh frame CCTV (kunci latensi rendah).
5. Deteksi plat (YOLOv8n, fallback klasik) → penyempitan ke pita teks →
   **kembalikan margin** (`pad_crop`) agar lengan huruf tepi tidak terpotong →
   koreksi perspektif (4 *point transform*) → *resize* tinggi tetap.
6. Enhancement crop plat: deglare → CLAHE kanal L → median blur 3×3
   (anti-moiré layar) → unsharp mask; retry terbatas bila hasil belum valid
   atau keyakinan < 0,80.
7. Deteksi stiker (ROI kaca depan/bumper) → *crop* → dekode QR/AprilTag; bila
   gagal, fallback klasifikasi pola/warna — kandidat yang gagal didekode
   dibuang, bukan bukti.
8. Kandidat diurutkan `candidate_score` (bingkai plat + struktur + kedekatan);
   teks yang melanggar struktur NRKB ditolak keras (dianggap tidak terbaca).

### 5.2 Fusi Skor

```
plat_score    = max(plat_confidence semua kamera)    + 0.05 × (jumlah_kamera_berhasil - 1)
sticker_score = max(sticker_confidence semua kamera) + 0.05 × (jumlah_kamera_berhasil - 1)
fused_score   = min(1.0, max(plat_score, sticker_score))
```

- `plat_score ≥ 0.85` → jalur plat valid.
- `sticker_score ≥ 0.80` → jalur stiker valid.
- Keduanya di bawah ambang tetapi salah satu di atas `plausible_threshold` (0.60) → cari plat terdekat dengan `pg_trgm` (maks 3 kandidat) → bila tepat 1 kandidat cocok dengan jarak ≤ 1 karakter, perlakukan sebagai `LOW_CONFIDENCE`; satpam tetap diminta konfirmasi (alert KUNING).

### 5.3 Aturan Keputusan
Lihat tabel keputusan di [SYSTEM_FLOW.md](SYSTEM_FLOW.md#4-tabel-keputusan). Urutan evaluasi:
1. Ada plat/stiker valid? Bila tidak → `OCR_FAILED`.
2. Cocok di `master_vehicles` dan `is_active`? Bila tidak → `NO_MATCH`.
3. Kendaraan `jenis = OPERASIONAL` dan `require_booking_for_operational = true`? Wajib booking aktif, bila tidak → `NO_MATCH`.
4. `fused_score ≥ fused_confidence_threshold` → `MATCH` → `AUTO_OPEN`. Selain itu → alert KUNING, minta konfirmasi satpam.

### 5.4 Normalisasi Plat

Normalisasi bersifat **block-aware**, bukan penggantian global. Teks dipecah
menjadi blok prefix wilayah (1–3 huruf), nomor urut (1–4 angka), dan suffix
(0–3 huruf); setiap pemecahan blok dinilai (karakter sesuai bloknya bernilai
penuh, karakter ambigu bernilai setengah), kode wilayah valid
(`VALID_PREFIXES`) mendapat bonus, dan nomor urut berawalan `0` dikenai
penalti karena NRKB tidak pernah diawali `0`. Koreksi karakter ambigu
dilakukan per blok — `0/1/O/I/L` → `D` dan `8` → `B` hanya pada prefix,
digit → huruf hanya pada suffix.

Hasil akhir yang tetap melanggar struktur NRKB (bagian depan wajib huruf,
nomor tidak diawali `0`, urutan blok huruf→angka→huruf) **ditolak keras**
sebagai tidak terbaca — bukan ditampilkan apa adanya — dan confidence-nya
tidak dihitung ke skor fusi.

---

### 5.5 Pemilihan Varian Model Deteksi

Tiga bobot custom tersedia dan dapat ditukar saat runtime (model dimuat ulang
otomatis): `yolov8n`, `yolov8x`, `yolo11n` — dipetakan di
`app/detect_yolo.py::VARIANTS` ke
`runs/detect/smartgate-colab-v6-<varian>/weights/best.pt`.

- Pilih lewat halaman **/training** ("Pilih Model Deteksi Aktif") atau
  `POST /api/settings {"yolo_variant": "yolo11n"}`.
- Persistensi: `system_settings.yolo_variant` (dipulihkan saat aplikasi start).
- Override lingkungan: `SGS_YOLO_VARIANT` (nama varian) atau `SGS_YOLO_WEIGHTS`
  (path bobot penuh, prioritas tertinggi).
- Fallback aman: bobot varian belum ada → kandidat berikutnya (varian lain →
  run V5 → run legacy).
- Metrik evaluasi tiap varian (`evaluation_summary.json` di folder run)
  ditampilkan di `/training` untuk perbandingan kecepatan/ketepatan.

## 6. Deployment

### 6.1 Prasyarat
- Proxmox VE 8+, VM/LXC Ubuntu 22.04 LTS.
- Docker Engine 24+ dan Docker Compose v2.
- GPU NVIDIA (opsional, sangat disarankan) dengan NVIDIA Container Toolkit.
- Storage NAS terpasang di `/mnt/nas` (NFS/SMB).
- Waktu server disinkronkan NTP lokal (penting untuk korelasi sesi).

### 6.2 `docker-compose.yml` (ringkas)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: smartgate
      POSTGRES_USER: smartgate
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: ["db_data:/var/lib/postgresql/data"]
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes: ["redis_data:/data"]
    restart: unless-stopped

  mqtt:
    image: eclipse-mosquitto:2
    ports: ["1883:1883"]
    volumes: ["./infra/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro"]
    restart: unless-stopped

  backend:
    build: ./backend
    env_file: [.env]
    depends_on: [db, redis, mqtt]
    ports: ["8000:8000"]
    volumes: ["/mnt/nas/snapshots:/snapshots", "/mnt/nas/backup:/backup"]
    restart: unless-stopped

  ai-worker:
    build: ./ai-worker
    env_file: [.env]
    depends_on: [backend]
    volumes:
      - /mnt/nas/snapshots:/snapshots
      - ./models:/models:ro
    deploy:
      resources:
        reservations:
          devices: [{ capabilities: [gpu] }]
    restart: unless-stopped

  frontend:
    build: ./frontend
    ports: ["8443:80"]
    depends_on: [backend]
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports: ["443:443"]
    volumes: ["./infra/nginx.conf:/etc/nginx/nginx.conf:ro"]
    depends_on: [backend, frontend]
    restart: unless-stopped

  worker:
    build: ./backend
    command: ["celery", "-A", "app.worker", "worker", "-B", "-l", "info"]
    env_file: [.env]
    depends_on: [db, redis]
    restart: unless-stopped

volumes:
  db_data:
  redis_data:
```

### 6.3 Variabel Lingkungan (`.env.example`)

```dotenv
# Blueprint produksi. Prototipe Flask cukup: SGS_SECRET_KEY (kunci sesi),
# SGS_ADMIN_PASSWORD/SGS_SATPAM_PASSWORD (akun seed), SGS_STICKER_SIGNING_KEY.
APP_ENV=production
TZ=Asia/Jakarta
DATABASE_URL=postgresql+asyncpg://smartgate:${DB_PASSWORD}@db:5432/smartgate
REDIS_URL=redis://redis:6379/0
MQTT_HOST=mqtt
MQTT_PORT=1883
JWT_SECRET=change-me-32-bytes-min
JWT_TTL_SECONDS=28800
INTERNAL_API_KEY=change-me-too
SNAPSHOT_ROOT=/snapshots
NAS_BACKUP_ROOT=/backup
CAMERA_1_RTSP=rtsp://user:pass@192.168.10.11/stream1
CAMERA_2_RTSP=rtsp://user:pass@192.168.10.12/stream1
PLAT_CONFIDENCE_THRESHOLD=0.85
STICKER_CONFIDENCE_THRESHOLD=0.80
SESSION_WINDOW_SECONDS=3
```

### 6.4 Langkah Deploy

```bash
git clone <repo> /opt/smart-gate && cd /opt/smart-gate
cp .env.example .env && nano .env              # isi password, IP kamera, secret
docker compose build
docker compose up -d db && sleep 5
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.seed     # seed settings, devices, admin
docker compose up -d
docker compose ps
```

Verifikasi:

```bash
curl -sf http://localhost:8000/healthz
docker compose logs -f ai-worker --tail=50
```

---

## 7. Keamanan

| Area | Kendali |
| :--- | :--- |
| Autentikasi dashboard | JWT HS256, `JWT_SECRET` ≥ 32 byte acak, TTL 8 jam |
| Otorisasi | RBAC: `SATPAM` (alert + override/reject), `SUPERVISOR`, `ADMIN` |
| API internal | Header `X-Internal-Key`, hanya menerima dari subnet Docker internal |
| Transport | TLS di Nginx; RTSP di VLAN kamera terpisah |
| Kredensial | Disimpan di `.env` (izin `600`), tidak pernah masuk repositori |
| Password | Argon2id (atau bcrypt *cost* 12) |
| Audit bypass | Constraint DB mewajibkan `override_by` + `override_note`; tercatat permanen |
| File snapshot | Direktori hanya-baca untuk frontend; nama file berisi UUID sesi, bukan plat |
| Rate limiting | 60 req/menit per IP pada endpoint login, 20/menit pada override |
| Hardening MQTT | Autentikasi pengguna + ACL topik per perangkat, TLS bila *broker* lintas host |
| Retensi | Sesuai [DATABASE.md](DATABASE.md#6-retensi--backup) |

---

## 8. Observabilitas

| Metrik | Sumber | Ambang peringatan |
| :--- | :--- | :--- |
| `gate_decision_latency_seconds` | Backend | p95 > 1.5 s |
| `ai_inference_duration_seconds` | AI worker | p95 > 0.8 s |
| `plate_recognition_rate` | Log harian | < 95% (siang) |
| `sticker_decode_rate` | Log harian | < 90% |
| `false_accept_rate` | Audit manual | > 0.1% |
| `device_offline_total` | Heartbeat | > 0 |
| `mqtt_publish_failures_total` | Backend | > 0 |
| `db_connection_errors_total` | Backend | > 0 |

Log terstruktur JSON dengan `session_id` sebagai korelasi utama; dikumpulkan oleh Loki.

---

## 9. Pengujian

| Jenis | Cakupan | Alat |
| :--- | :--- | :--- |
| Unit | Normalisasi plat, fungsi fusi, aturan keputusan | pytest |
| Integration | Alur push → sesi → keputusan → log | pytest + testcontainers (Postgres, Mosquitto) |
| Kontrak API | Skema request/response sesuai [API.md](API.md) | schemathesis / pytest + httpx |
| AI offline | Dataset gambar uji siang/malam/hujan, ukur akurasi & latensi | skrip benchmark, *confusion matrix* |
| End-to-end | Simulasi CCTV, ESP32 virtual (MQTT *mock*), verifikasi gate terbuka & log | pytest + mosquitto mock |
| Beban | 50 kendaraan/menit, ukur latensi p95 | Locust |
| Failover | Matikan satu per satu: CCTV, AI, MQTT, DB | manual / chaos script |
| UAT | Skenario nyata bersama satpam (warga, karyawan, tamu, tidak dikenal) | checklist manual |

### Target Kelulusan
- Seluruh kasus uji keputusan (9 baris tabel keputusan) lulus.
- Latensi p95 ≤ 1.5 s pada beban 50 kendaraan/menit.
- Setiap bypass tersimpan lengkap dengan foto + identitas satpam.

---

## 10. Pemeliharaan Operasional

| Tugas | Frekuensi | Prosedur |
| :--- | :--- | :--- |
| Cek status container | Harian | `docker compose ps` |
| Cek akurasi OCR | Mingguan | Tinjau `gate_logs` `match_result = LOW_CONFIDENCE` |
| Kalibrasi ROI & *exposure* kamera | Bulanan | Bersihkan lensa, sesuaikan sudut & ROI di config |
| Pembaruan model AI | Per rilis | *Retrain* dengan gambar salah klasifikasi, ekspor ONNX, uji A/B lalu promosikan |
| Backup DB | Harian | `pg_dump` terjadwal → `/mnt/nas/backup` |
| Uji restore | Per kuartal | Restore ke DB sementara dan verifikasi jumlah baris |
| Rotasi JWT secret & kunci internal | Per kuartal | Update `.env`, restart backend |
| Pembersihan snapshot | Harian | Job Celery sesuai `snapshot_retention_days` |
| Uji gate darurat | Bulanan | Tombol darurat fisik dipastikan berfungsi |

---

## 11. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
| :--- | :--- | :--- |
| Plat kotor/terhalang | OCR gagal | Manfaatkan stiker khusus sebagai jalur alternatif + bypass satpam |
| Stiker pudar/tergores | Decode gagal | Jalur plat tetap dipakai; jadwalkan penggantian stiker |
| Kamera tergeser angin | ROI meleset | Bracket kokoh + pemeriksaan kalibrasi bulanan + alert penurunan akurasi |
| Hujan/malam | Akurasi turun | Inframerah/IR, lampu LED gate, ambang *confidence* adaptif per kondisi |
| Motor gate mogok | Kendaraan tertahan | Tombol darurat fisik + jalur bypass manual terekam |
| Database lambat | Deteksi gagal | *Fail-safe*: tidak pernah membuka gate otomatis saat DB tidak tersedia |
| Bypass tanpa jejak | Risiko penyalahgunaan | Constraint DB + laporan harian jumlah bypass per satpam |
| Deteksi ganda satu kendaraan | Log ganda | Jendela korelasi sesi + deduplikasi berdasarkan `session_id` |

---

## 12. Roadmap

| Fase | Cakupan |
| :--- | :--- |
| Fase 1 (MVP) | 1 gate, 2 CCTV, OCR plat + stiker, dashboard satpam, auto open, bypass, log |
| Fase 2 | Booking kendaraan operasional penuh, laporan/export, panel admin kendaraan |
| Fase 3 | Multi-gate, RFID UHF sebagai jalur ketiga, analitik akurasi & dasbor KPI |
| Fase 4 | Pembelajaran ulang otomatis dari kasus salah klasifikasi, OCR adaptif per gate |

---

## 13. Referensi

- Harani, N. H., Prianto, C., dan Hasanah, M. (2019). *Deteksi Objek dan Pengenalan Karakter Plat Nomor Kendaraan Indonesia Menggunakan Metode CNN Berbasis Python*. Jurnal Teknik Informatika Vol. 11 No. 3. [PDF](artc/658-Article%20Text-963-1-10-20200213.pdf)
- Subekti, I., Hariyono, R. C. S., dan Sorikhi. (2025). *Pengenalan Plat Nomor Kendaraan Menggunakan Algoritma CNN Berbasis Tensorflow*. Remik Vol. 9 No. 3. DOI [10.33395/remik.v9i3.15169](https://doi.org/10.33395/remik.v9i3.15169). [PDF](artc/15169-Article%20Text-24310-1-10-20250811.pdf)
- [Axelera AI — Home Assistant CCTV Object and Motion Detection Using Metis](https://community.axelera.ai/the-axelera-forum-52/home-assistant-cctv-object-and-motion-detection-using-metis-1226) · [`axelera-ai-hub/voyager-sdk`](https://github.com/axelera-ai-hub/voyager-sdk) · [`graffitiwriter/Metis-for-Home-Assistant-Motion-Detection`](https://github.com/graffitiwriter/Metis-for-Home-Assistant-Motion-Detection) — referensi NPU (Axelera Metis), zona deteksi per-koordinat, dan cascaded pipeline untuk LPR.
