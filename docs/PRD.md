# Product Requirements Document (PRD): Enterprise Smart Gate System

> **Catatan lingkup:** Fitur stiker QR dan RFID dalam dokumen ini adalah
> **rencana pengembangan mendatang / bahan skripsi**. Lingkup prototipe saat ini:
> pengenalan plat nomor (YOLOv8 + aturan NRKB + keputusan fail-safe).

## 1. Ikhtisar Produk
**Nama Produk:** Enterprise Smart Gate System
**Tujuan Utama:** Mengotomatisasi akses gerbang dengan tingkat keberhasilan tinggi melalui fusi citra ganda (**CCTV 1 + CCTV 2**: OCR plat nomor & deteksi stiker khusus) serta menyediakan antarmuka *fallback* manual (*Dashboard* Satpam) yang terintegrasi dengan modul pemesanan kendaraan (Car Booking) dan master data warga/karyawan.

**Ringkasan Alur:**
1. **CCTV 1** (zona pendekatan) menangkap gambar kendaraan masuk → mencoba membaca **plat nomor** *dan* **stiker khusus**. Hasil keduanya dipakai sebagai penguat skor keberhasilan (*confidence fusion*).
2. **CCTV 2** (dekat gate) menangkap gambar **plat nomor** dan/atau **stiker khusus** sebagai sumber kedua.
3. Dua gambar atau lebih diproses melalui **pipeline pengolahan citra** (seleksi frame terbaik, pre-processing, OCR, dekode stiker, fusi skor).
4. Jika plat nomor didapatkan dengan **akurasi tinggi** **ATAU** stiker sesuai → dilakukan **pencocokan ke database**.
5. **Data cocok** → alert di control room/pos jaga: *"kendaraan warga/karyawan perusahaan"* → sistem mengirim perintah ke **motor** untuk membuka gerbang **otomatis**. Log menyertakan foto.
6. **Plat gagal didapat / data tidak cocok** → alert *"kendaraan tidak dikenal"* → satpam melakukan pengecekan. Jika dinilai aman, satpam dapat **bypass** membuka gate secara manual. Log tetap tersimpan di sistem beserta foto dan identitas satpam.

## 2. Requirements

### Functional Requirements (Kebutuhan Fungsional)
1. **Multi-Camera Detection:** Sistem harus menerima dan mengkorelasikan input dari minimal **2 CCTV** (CCTV 1 pendekatan, CCTV 2 gate) dalam satu sesi deteksi yang sama (*session correlation window* ≤ 3 detik).
2. **Multi-Modal Recognition:** Setiap gambar diproses untuk dua target sekaligus:
   - **Plat Nomor (ALPR):** deteksi plat + OCR karakter, menghasilkan string dan *confidence*.
   - **Stiker Khusus:** deteksi & dekode ID stiker kendaraan (warga/karyawan), menghasilkan kode stiker dan *confidence*.
3. **Image Processing Pipeline:** Sistem harus memilih *best frame* dari setiap CCTV, melakukan pre-processing (de-noise, koreksi perspektif/*deskew*, peningkatan kontras, *resize*), lalu menyimpan snapshot hasil terbaik.
4. **Confidence Fusion:** Skor akhir dihitung dari kombinasi hasil CCTV 1, CCTV 2, plat, dan stiker. Hasil stiker berfungsi sebagai **penguat** kemungkinan keberhasilan identifikasi, bukan syarat tunggal.
5. **Double-Validation Logic:** Gerbang otomatis terbuka jika:
   `(Plat Nomor cocok di database DAN confidence ≥ ambang) ATAU (Stiker Khusus cocok di database DAN confidence ≥ ambang)`
   dengan tambahan validasi jadwal *Car Booking* bilamana kendaraan terikat pada booking aktif.
6. **Real-time Dashboard:** Satpam harus menerima notifikasi *pop-up* dan *live snapshot* kurang dari 1 detik setelah keputusan dibuat, dibedakan warna: **HIJAU** (kendaraan dikenali / warga-karyawan), **MERAH** (kendaraan tidak dikenal / gagal baca).
7. **Manual Override (Bypass):** Satpam dapat membuka gerbang secara manual melalui *dashboard*, yang **wajib** merekam identitas satpam (`override_by`), waktu, alasan/catatan, dan foto kejadian.
8. **Complete Audit Log:** Setiap kejadian — baik *auto open*, *manual override*, maupun *rejected* — wajib tercatat lengkap dengan minimal satu foto snapshot.
9. **Car Booking Integration:** Sistem harus mengecek status pemesanan kendaraan operasional sebelum memberikan izin masuk/keluar.
10. **Realtime Alerting:** Alert harus terkirim ke seluruh *dashboard* satpam yang aktif (WebSocket broadcast) dengan latensi < 1 detik.

### Non-Functional Requirements (Kebutuhan Non-Fungsional)
1. **Latency:** Total waktu dari frame terakhir diterima hingga *relay*/motor terbuka maksimal **1.5 detik** (jalur otomatis). Jalur manual oleh satpam tidak dihitung dalam SLA ini.
2. **Accuracy:** Target *plate recognition rate* ≥ 98% pada kondisi siang, ≥ 90% pada kondisi malam/hujan; target *sticker decode rate* ≥ 95%.
3. **High Availability:** Semua *service* AI dan backend berjalan di atas *container* Docker lokal (Proxmox) agar tetap berfungsi meski koneksi internet eksternal terputus.
4. **Storage:** Foto *snapshot* disimpan di NAS/Lokal, database hanya menyimpan URL/Path gambar.
5. **Fault Tolerance:** Kegagalan salah satu CCTV, AI service, atau koneksi MQTT **tidak boleh** mengunci gerbang; sistem turun ke mode *manual override* dengan alert ke satpam.
6. **Security:** Autentikasi JWT untuk *dashboard*, komunikasi antar-service ter-enkripsi di jaringan lokal, seluruh aksi bypass tercatat sebagai audit trail yang tidak dapat diubah.
7. **Scalability:** Arsitektur harus mendukung penambahan gate/CCTV berikutnya hanya dengan menambah entri pada `gate_devices` tanpa perubahan kode inti.
8. **Availability Target:** ≥ 99.5% *uptime* bulanan untuk layanan gerbang.
9. **Robustness Citra:** Sistem harus menolak distraktor tampilan
   (subtitle/video, blok warna, objek mirip teks) dan memberlakukan aturan
   struktur NRKB secara **keras** — hasil yang melanggar format dianggap
   tidak terbaca, bukan diterima sebagian. Moiré/pantulan layar ditangani di
   lapisan pra-pemrosesan, bukan dengan menurunkan ambang keputusan.

---

## 3. System Flow (Alur Sistem)

Detail lengkap (diagram *sequence*, *state machine*, tabel keputusan) ada di [SYSTEM_FLOW.md](SYSTEM_FLOW.md). Ringkasan fase:

1. **Fase Pendekatan (Approach) — CCTV 1:** Kendaraan memasuki radius 5–10 meter dari gerbang. CCTV 1 menangkap *frame* keseluruhan kendaraan dan mencoba membaca **plat nomor** serta **stiker khusus**. Hasil keduanya dipakai sebagai penguat skor keberhasilan.
2. **Fase Konfirmasi (Gate Zone) — CCTV 2:** CCTV 2 (dekat gate) menangkap gambar tambahan untuk **plat nomor** dan/atau **stiker khusus**. Minimal **2 gambar** dari 2 CCTV yang dikorelasikan dalam satu `session_id` (jendela korelasi ≤ 3 detik).
3. **Fase Ekstraksi & Pengolahan Citra (Edge Inference):** Seluruh gambar sesi dikirim ke Inference Server lokal (YOLOv8 + OCR + *sticker decoder*). Server melakukan seleksi *best frame*, pre-processing citra, OCR plat, dekode stiker, lalu menghitung **skor fusi** `(plat_confidence, sticker_confidence)`.
4. **Fase Evaluasi (Backend FastAPI):** Backend mencocokkan hasil ke PostgreSQL.
   - Plat terbaca dengan akurasi tinggi → cari `master_vehicles.plat_nomor`.
   - Stiker sesuai → cari `master_vehicles.sticker_code`.
   - Jika kendaraan ditemukan → validasi status aktif dan (bila ada) jadwal `car_bookings` yang sedang berlaku.
5. **Fase Keputusan (Action/Override):**
   - **Data Cocok (Valid):** Backend mengirim sinyal via MQTT ke ESP32 untuk menggerakkan **motor/relay** membuka gate. Dashboard satpam menampilkan alert **HIJAU**: *"Kendaraan warga/karyawan perusahaan"*. Log tersimpan lengkap dengan foto.
   - **Tidak Cocok / Gagal Baca:** Dashboard satpam menampilkan alert **MERAH**: *"Kendaraan tidak dikenal"* + foto. Satpam melakukan pengecekan visual. Jika dirasa aman, satpam menekan **Bypass** → gate dibuka manual, log tetap tersimpan beserta foto, identitas satpam, dan catatan alasan. Jika tidak aman → satpam menekan **Tolak (Rejected)**; gate tetap tertutup dan kendaraan dialihkan untuk pemeriksaan lanjutan.

---

## 4. Skema Database & Relasi (PostgreSQL)

DDL lengkap, indeks, dan kebijakan retensi ada di [DATABASE.md](DATABASE.md). Ringkasan tabel:

| Tabel | Fungsi |
| :--- | :--- |
| `users` | Akun satpam/admin (pelaku `manual override`). |
| `gate_devices` | Registry perangkat: CCTV 1, CCTV 2, motor/relay gate, reader RFID (opsional). |
| `master_vehicles` | Master kendaraan warga/karyawan/tamu beserta `plat_nomor` dan `sticker_code`. |
| `car_bookings` | Jadwal pemesanan kendaraan operasional (integrasi modul GA). |
| `detection_events` | Data mentah per frame/gambar dari tiap CCTV (hasil OCR & dekode stiker). |
| `gate_logs` | Hasil akhir keputusan per sesi: auto open / bypass / rejected + foto + audit. |
| `system_settings` | Ambang batas *confidence* dan parameter operasional (dapat diubah tanpa deploy). |

**Relasi Data:**
- `users` **(1)** memiliki **(N)** `gate_logs` (relasi `override_by` — satpam yang melakukan bypass)
- `gate_devices` **(1)** memiliki **(N)** `detection_events`
- `gate_devices` **(1)** memiliki **(N)** `gate_logs` (perangkat gate yang dieksekusi)
- `master_vehicles` **(1)** memiliki **(N)** `car_bookings`
- `master_vehicles` **(1)** memiliki **(N)** `gate_logs` (Nullable — `NULL` bila kendaraan tidak dikenal)
- `gate_logs` **(1)** terhubung ke **(N)** `detection_events` melalui `session_id` (satu sesi = minimal 2 gambar dari 2 CCTV)

---

## 5. Spesifikasi API (FastAPI)

Kontrak lengkap (payload, response, *error code*, WebSocket event) ada di [API.md](API.md). Ringkasan endpoint utama:

| Method | Endpoint | Fungsi |
| :--- | :--- | :--- |
| `POST` | `/api/v1/detection/push` | AI Inference Server mengirim hasil OCR plat / dekode stiker + gambar per CCTV. |
| `POST` | `/api/v1/detection/session/close` | Menutup sesi deteksi dan memicu evaluasi fusi + keputusan. |
| `GET` | `/api/v1/gate/decision/{session_id}` | Mengambil hasil keputusan sesi (MATCH / NO_MATCH). |
| `POST` | `/api/v1/gate/{session_id}/override` | Satpam melakukan **bypass** manual (wajib catatan + identitas satpam). |
| `POST` | `/api/v1/gate/{session_id}/reject` | Satpam menolak akses kendaraan tidak dikenal. |
| `POST` | `/api/v1/gate/{device_id}/open` | Perintah buka gate langsung (role ADMIN / darurat). |
| `GET` | `/api/v1/logs` | Riwayat log gate dengan filter tanggal, status, plat. |
| `GET`/`POST`/`PUT` | `/api/v1/vehicles` | CRUD master kendaraan (plat + stiker khusus). |
| `GET`/`POST` | `/api/v1/bookings` | Modul Car Booking kendaraan operasional. |
| `POST` | `/api/v1/auth/login` | Autentikasi dashboard satpam (JWT). |
| `WS` | `/ws/alerts` | Siaran realtime alert HIJAU/MERAH ke seluruh dashboard satpam. |
| `POST` | `/api/v1/devices/heartbeat` | Heartbeat perangkat (CCTV, motor relay). |

### A. Endpoint Ingestion (AI Inference Server → Backend)
- **Endpoint:** `POST /api/v1/detection/push`
- **Fungsi:** Menerima hasil OCR plat dan/atau dekode stiker khusus beserta gambar dari *container* AI.
- **Payload:**
  ```json
  {
    "session_id": "3f8c1e42-...",
    "camera_id": "cam_gate_masuk_1",
    "direction": "IN",
    "plat_text": "B1234XYZ",
    "plat_confidence": 0.92,
    "sticker_code": "STK-WRG-0042",
    "sticker_confidence": 0.88,
    "image_base64": "..."
  }
  ```

---

## 6. Log & Audit

Setiap `gate_logs` **wajib** menyimpan:
- `session_id` — pengait ke seluruh `detection_events` (minimal 2 gambar, 2 CCTV)
- `snapshot_url` — foto terbaik (best frame) yang menjadi dasar keputusan
- `snapshot_urls` — seluruh foto dari setiap CCTV pada sesi tersebut
- `plat_final`, `plat_confidence`, `sticker_final`, `sticker_confidence`
- `match_result` dan `decision` (`AUTO_OPEN`, `MANUAL_OVERRIDE`, `REJECTED`)
- `override_by`, `override_note`, `override_at` — hanya terisi saat bypass manual

---

## 7. Metrik Keberhasilan (KPI)

| Metrik | Target |
| :--- | :--- |
| Plate recognition rate (siang) | ≥ 98% |
| Plate recognition rate (malam/hujan) | ≥ 90% |
| Sticker decode rate | ≥ 95% |
| False accept rate (kendaraan asing diizinkan otomatis) | ≤ 0.1% |
| Waktu keputusan otomatis (frame akhir → motor bergerak) | ≤ 1.5 detik |
| Latensi alert ke dashboard satpam | ≤ 1 detik |
| Kelengkapan log (ada foto) | 100% |
| Ketepatan pembacaan plat nomor & stiker (fusion) | ≥ 99% |
| Kecepatan pemrosesan *best frame* & OCR | ≤ 0.5 detik per frame |

---

## 8. Asumsi & Batasan

- Stiker khusus ditempel pada posisi yang terlihat kamera (kaca depan / bumper) dengan kode unik yang terdaftar di `master_vehicles.sticker_code`.
- Setiap CCTV memiliki `camera_id` tetap yang terdaftar di `gate_devices`.
- Kendaraan operasional yang terikat pada `car_bookings` hanya boleh masuk pada rentang `start_time`–`end_time`.
- Motor gate dikendalikan melalui ESP32 (relay) yang menerima perintah via MQTT dari backend.
- Sistem berjalan *on-premise*; koneksi internet eksternal tidak menjadi dependensi jalur kritis.

---

## 9. Referensi Dokumen

| Dokumen | Isi |
| :--- | :--- |
| [DATABASE.md](DATABASE.md) | DDL PostgreSQL, ERD, relasi, indeks, retensi data |
| [SYSTEM_FLOW.md](SYSTEM_FLOW.md) | Diagram alur, *state machine*, tabel keputusan, urutan waktu |
| [API.md](API.md) | Spesifikasi lengkap endpoint, payload, response, WebSocket |
| [TECHNICAL.md](TECHNICAL.md) | Arsitektur, stack, deployment, model AI, keamanan, pengujian |