# Changelog

All notable changes to **Smart Gate System** are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2026-11-27] — Sistem Log Kendaraan Terpadu & Kepatuhan (Satpam, HRGA, Bea Cukai)

### Added
- **Skema Log Kendaraan Terpadu (`gate_logs`)**: Penambahan kolom `direction` (`IN`/`OUT`), `visit_category` (`COMPANY_CAR`, `EMPLOYEE`, `CARGO_LOGISTIC`, `GUEST`), `paired_log_id`, `dwell_minutes`, `driver_or_guest_name`, `company_or_vendor`, `visit_purpose_or_host`, `bc_doc_type` (`NONE`, `BC 2.3`, `BC 2.5`, `BC 2.7`, `BC 4.0`, `BC 4.1`, `SURAT_JALAN`), `bc_doc_number`, dan `seal_number`.
- **Tabel Penjadwalan & Izin (`vehicle_bookings`)**: Halaman manajemen `/bookings` (HRGA & Admin) untuk penjadwalan mobil dinas, tamu, dan kargo; metadata otomatis terisi ke `gate_logs` saat plat aktif dipindai di gerbang.
- **Pairing Otomatis `IN` ↔ `OUT` & Durasi Kunjungan (`dwell_minutes`)**: Log `OUT` otomatis dipasangkan ke log `IN` terbuka terbaru dengan plat yang sama dan menghitung durasi kunjungan secara otomatis.
- **Peran RBAC Baru**: Penambahan peran `hrga` (`hrga1`) dan `beacukai` (`beacukai1`) dengan password seed yang dapat dikonfigurasi via `SGS_HRGA_PASSWORD` dan `SGS_BEACUKAI_PASSWORD`.
- **API Pencarian & Ekspor Laporan**:
  - `GET /api/logs` dengan filter terpadu (`q`, `direction`, `visit_category`, `status` termasuk `UNCLOSED_IN`, `bc_doc_type`, `date_from`, `date_to`).
  - `GET /api/logs/export.csv` dengan UTF-8 BOM (`\ufeff`) siap dibuka langsung di Microsoft Excel serta proteksi *CSV formula injection*.
- **UI/UX Terpadu**:
  - Navigasi dinamis berbasis peran + badge peran aktif di `base.html`.
  - Kartu KPI operasional di `dashboard.html` (*Kendaraan di Dalam Area*, *Kargo/Bea Cukai Hari Ini*, *Tamu & Mobil Dinas Aktif*) serta pemilih arah cepat (`IN`/`OUT`) di `dashboard.html` dan `camera.html`.
  - Form dinamis berbasis JavaScript vanilla di `log_detail.html` (panel Tamu, panel Kargo & Bea Cukai, panel Mobil Perusahaan/Karyawan) + kartu relasi Pasangan Log `IN` ↔ `OUT` beserta durasi kunjungan.
- **Pengujian Otomatis**: Penambahan uji migrasi skema lama, pairing `IN`↔`OUT`, validasi metadata kargo/tamu, RBAC `hrga` & `beacukai` (HTTP 403), dan ekspor CSV di `tests/test_pipeline.py` (**170 pemeriksaan lulus**).

### Changed
- `service.evaluate()` kini menerima parameter `direction` dan `metadata`, melakukan deduplikasi cooldown per kombinasi `(direction, plate_text)`, serta menggabungkan metadata otomatis dari `vehicle_bookings` dan `master_vehicles`.
- `service.guard_action()` mendukung pembaruan metadata terstruktur pada aksi `bypass`, `reject`, dan `update`.
- `logs.html` diperbarui dengan bar filter multi-kriteria, badge arah/kategori/durasi, dan tombol **Export CSV (HRGA / Bea Cukai)**.

### Security
- Penegakan `@auth.roles_required(...)` ketat pada seluruh endpoint HTML dan `/api/*`:
  - `hrga` dan `beacukai` ditolak (`HTTP 403`) dari `MANUAL_OVERRIDE`, `REJECTED`, `/api/settings`, `/camera`, `/upload`, `/api/evaluate`, dan `/api/simulate`.
  - `beacukai` otomatis terfilter pada kategori `CARGO_LOGISTIC` secara default dan ditolak dari `/bookings` serta `/vehicles`.
- Proteksi *CSV formula injection* (`_csv_safe`) pada seluruh sel ekspor CSV.
- Seluruh query filter menggunakan parameterized SQL dan seluruh rendering dinamis di `app.js` tetap memakai `esc()`.

### Database Migration
- Migrasi otomatis idempoten di `app/db.py:_migrate()` menambahkan 10 kolom baru pada `gate_logs` via `ALTER TABLE`, memperluas `CHECK` constraint `users.role` untuk DB lama agar menerima `hrga` & `beacukai`, membuat tabel `vehicle_bookings`, serta menambahkan indeks `(direction, visit_category, created_at DESC)` dan `(bc_doc_number)`.

---

## [2026-11-24] — Penutupan Audit Penuh Kode + ML & Runner ONNX Murni

### Added
- Runner deteksi YOLO ONNX murni (`_OnnxYoloRunner` di `app/detect_yolo.py`) menggunakan `onnxruntime` atau `cv2.dnn.readNetFromONNX` tanpa mengimpor `torch`/`ultralytics` (`SGS_USE_ONNX=1`).
- Laporan audit kode & ML lengkap di `docs/AUDIT_FULL_CODE_ML.md`.

### Changed
- Perbaikan `deglare()` untuk melindungi papan TNKB dasar putih Perpol 7/2021 (`M-1`), pelestarian huruf seri `Q` (`L-1`), pemisahan golongan `bus` (`7000–7999`) vs `truck` (`8000–8999`) (`L-2`), dan *fail-safe* `db.settings()` (`L-3`).
- Urutan import `paddlex` sebelum `paddle` di `_configure_paddle_cpu()` untuk mencegah konflik DLL Windows `torch\lib\shm.dll` (`WinError 127`) dan `PDX has already been initialized`.
