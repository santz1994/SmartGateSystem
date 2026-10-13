# API Specification — Enterprise Smart Gate System

Referensi: [PRD.md](PRD.md) · [DATABASE.md](DATABASE.md) · [SYSTEM_FLOW.md](SYSTEM_FLOW.md) · [TECHNICAL.md](TECHNICAL.md)

Base URL: `http://gate-backend.local:8000`
Versi: `v1` · Format: JSON (UTF-8) · Auth: `Authorization: Bearer <JWT>` kecuali ditandai *publik/internal*.

---

## 0. Konvensi

| Aspek | Aturan |
| :--- | :--- |
| Autentikasi | JWT HS256, masa hidup 8 jam (shift satpam), refresh via `/auth/refresh` |
| Auth internal | AI worker & heartbeat perangkat memakai header `X-Internal-Key` |
| Timestamp | ISO-8601 dengan zona, contoh `2026-10-13T07:29:08+07:00` |
| ID | UUIDv4 |
| Error | `{ "error": { "code": "...", "message": "...", "detail": {} } }` |
| Paginasi | `?page=1&per_page=50`, response menyertakan `meta` |
| Idempotensi | `POST` ingestion & override idempoten berdasarkan `session_id` |

### Kode Error

| HTTP | Code | Arti |
| :--- | :--- | :--- |
| 400 | `INVALID_PAYLOAD` | Body tidak sesuai skema |
| 401 | `UNAUTHENTICATED` | Token hilang/kadaluarsa |
| 403 | `FORBIDDEN` | Role tidak berwenang (mis. satpam akses endpoint admin) |
| 404 | `SESSION_NOT_FOUND` | `session_id` tidak dikenal |
| 409 | `SESSION_ALREADY_CLOSED` | Sesi sudah dievaluasi |
| 409 | `DECISION_ALREADY_MADE` | Override/reject dipanggil dua kali |
| 422 | `DEVICE_NOT_FOUND` | `camera_id` / `device_id` tidak terdaftar |
| 503 | `AI_SERVICE_UNAVAILABLE` | Inference server tidak merespons |

---

## 1. Autentikasi

### `POST /api/v1/auth/login`

```json
{ "username": "satpam.pos1", "password": "••••••" }
```

Response `200`:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": { "id": "8f0c...", "username": "satpam.pos1", "full_name": "Budi", "role": "SATPAM" }
}
```

### `POST /api/v1/auth/refresh` · `POST /api/v1/auth/logout`
Menggunakan `Authorization: Bearer <token>` yang masih valid.

---

## 2. Ingestion (AI Inference Server → Backend)

### `POST /api/v1/detection/push` *(internal)*

Header: `X-Internal-Key: <secret>`

```json
{
  "session_id": "3f8c1e42-9a11-4c72-b7d0-2a9f5e6c1b04",
  "camera_id": "cam_gate_masuk_1",
  "direction": "IN",
  "plat_text": "B1234XYZ",
  "plat_confidence": 0.92,
  "sticker_code": "STK-WRG-0042",
  "sticker_confidence": 0.88,
  "is_best_frame": true,
  "image_base64": "iVBORw0KGgo...",
  "captured_at": "2026-10-13T07:29:08+07:00"
}
```

Response `201`:

```json
{
  "event_id": "c1a2...",
  "session_id": "3f8c1e42-...",
  "image_path": "/snapshots/2026/10/13/3f8c1e42/cam_gate_masuk_1.jpg",
  "session_state": "CAPTURING",
  "images_collected": 2,
  "min_images_required": 2
}
```

Catatan: gambar diterima sebagai base64, ditulis ke NAS oleh backend, dan yang tersimpan di DB hanya `image_path`.

### `POST /api/v1/detection/session/close` *(internal)*

```json
{ "session_id": "3f8c1e42-9a11-4c72-b7d0-2a9f5e6c1b04", "reason": "WINDOW_ELAPSED" }
```

Response `200`:

```json
{ "session_id": "3f8c1e42-...", "status": "EVALUATED", "decision": "AUTO_OPEN" }
```

Error: `404 SESSION_NOT_FOUND`, `409 SESSION_ALREADY_CLOSED`.

---

## 3. Keputusan Gate

### `GET /api/v1/gate/decision/{session_id}`

Response `200` (kendaraan dikenali):

```json
{
  "session_id": "3f8c1e42-...",
  "decision": "AUTO_OPEN",
  "match_result": "MATCH",
  "vehicle": {
    "id": "7b2c...",
    "plat_nomor": "B1234XYZ",
    "sticker_code": "STK-WRG-0042",
    "jenis": "KARYAWAN",
    "owner_name": "Andi Pratama",
    "owner_dept": "Finance"
  },
  "booking": null,
  "fused_confidence": 0.94,
  "sources": [
    { "camera_id": "cam_gate_masuk_1", "plat_confidence": 0.92, "sticker_confidence": 0.88 },
    { "camera_id": "cam_gate_masuk_2", "plat_confidence": 0.90, "sticker_confidence": null }
  ],
  "snapshot_url": "/snapshots/2026/10/13/3f8c1e42/cam_gate_masuk_1.jpg",
  "snapshot_urls": [
    "/snapshots/2026/10/13/3f8c1e42/cam_gate_masuk_1.jpg",
    "/snapshots/2026/10/13/3f8c1e42/cam_gate_masuk_2.jpg"
  ],
  "decided_at": "2026-10-13T07:29:09+07:00"
}
```

Response `200` (tidak dikenal):

```json
{
  "session_id": "9d1f...",
  "decision": null,
  "match_result": "NO_MATCH",
  "vehicle": null,
  "booking": null,
  "fused_confidence": 0.41,
  "snapshot_urls": ["/snapshots/.../cam_gate_masuk_1.jpg"],
  "awaiting_action": true,
  "decided_at": "2026-10-13T07:29:10+07:00"
}
```

### `POST /api/v1/gate/{session_id}/override` *(role: SATPAM, SUPERVISOR, ADMIN)*

Bypass manual — **wajib** `note`, backend mencatat `override_by` dari JWT.

```json
{ "note": "Kendaraan tamu, sudah verifikasi KTP di pos. Aman." }
```

Response `200`:

```json
{
  "session_id": "9d1f...",
  "decision": "MANUAL_OVERRIDE",
  "override_by": { "id": "8f0c...", "full_name": "Budi" },
  "override_at": "2026-10-13T07:30:12+07:00",
  "gate_command_sent": true
}
```

Error: `409 DECISION_ALREADY_MADE`, `400 INVALID_PAYLOAD` (note kosong).

### `POST /api/v1/gate/{session_id}/reject` *(role: SATPAM, SUPERVISOR, ADMIN)*

```json
{ "note": "Kendaraan tanpa izin, dialihkan ke pemeriksaan." }
```

Response `200`: `{ "session_id": "9d1f...", "decision": "REJECTED", "gate_command_sent": false }`

### `POST /api/v1/gate/{device_id}/open` *(role: ADMIN, SUPERVISOR)*

Pembukaan langsung/keadaan darurat, bukan hasil deteksi.

```json
{ "note": "Uji coba pemeliharaan gate." }
```

Response `200`: `{ "device_id": "gate_in_motor", "command_sent": true, "sent_at": "..." }`

---

## 4. Master Kendaraan

### `GET /api/v1/vehicles?q=B1234&jenis=KARYAWAN&page=1&per_page=50`

```json
{
  "data": [
    {
      "id": "7b2c...",
      "plat_nomor": "B1234XYZ",
      "sticker_code": "STK-WRG-0042",
      "rfid_tag": "TAG98765",
      "jenis": "KARYAWAN",
      "owner_name": "Andi Pratama",
      "owner_dept": "Finance",
      "is_active": true
    }
  ],
  "meta": { "page": 1, "per_page": 50, "total": 1 }
}
```

### `POST /api/v1/vehicles` *(role: ADMIN)*

```json
{
  "plat_nomor": "B1234XYZ",
  "sticker_code": "STK-WRG-0042",
  "rfid_tag": "TAG98765",
  "jenis": "KARYAWAN",
  "owner_name": "Andi Pratama",
  "owner_dept": "Finance",
  "phone": "0812..."
}
```

Response `201` dengan objek kendaraan. Error `409` bila `plat_nomor`/`sticker_code`/`rfid_tag` sudah dipakai.

### `PUT /api/v1/vehicles/{id}` · `DELETE /api/v1/vehicles/{id}`
`DELETE` melakukan *soft delete* (`is_active = false`) agar `gate_logs` historis tetap valid.

---

## 5. Car Booking

### `POST /api/v1/bookings`

```json
{
  "vehicle_id": "7b2c...",
  "purpose": "Kunjungan klien - Divisi IT",
  "start_time": "2026-10-13T08:00:00+07:00",
  "end_time": "2026-10-13T17:00:00+07:00"
}
```

### `GET /api/v1/bookings?status=APPROVED&date=2026-10-13`
### `POST /api/v1/bookings/{id}/cancel` *(role: ADMIN, SUPERVISOR)*

---

## 6. Log & Audit

### `GET /api/v1/logs?from=2026-10-01&to=2026-10-13&decision=MANUAL_OVERRIDE&plat=B1234&page=1&per_page=50`

```json
{
  "data": [
    {
      "id": "d4e5...",
      "session_id": "9d1f...",
      "plate_final": "B9999ZZ",
      "sticker_final": null,
      "match_result": "NO_MATCH",
      "decision": "MANUAL_OVERRIDE",
      "vehicle": null,
      "snapshot_url": "/snapshots/2026/10/13/9d1f/cam_gate_masuk_1.jpg",
      "snapshot_urls": ["/snapshots/.../cam_gate_masuk_1.jpg", "/snapshots/.../cam_gate_masuk_2.jpg"],
      "override_by": { "id": "8f0c...", "full_name": "Budi" },
      "override_note": "Kendaraan tamu, sudah verifikasi KTP.",
      "override_at": "2026-10-13T07:30:12+07:00",
      "created_at": "2026-10-13T07:30:12+07:00"
    }
  ],
  "meta": { "page": 1, "per_page": 50, "total": 1 }
}
```

### `GET /api/v1/logs/{session_id}`
Detail satu sesi termasuk seluruh `detection_events` penyusunnya.

### `GET /api/v1/logs/export?from=...&to=...&format=csv`
Export CSV untuk laporan bulanan (role ADMIN/SUPERVISOR).

---

## 7. Perangkat & Pengaturan

### `POST /api/v1/devices/heartbeat` *(internal)*

```json
{ "code": "cam_gate_masuk_1", "status": "ONLINE", "firmware": "esp32-1.4.2", "uptime_s": 84213 }
```

### `GET /api/v1/devices` *(role: ADMIN)*
Status perangkat + `last_seen_at`.

### `GET /api/v1/settings` · `PUT /api/v1/settings` *(role: ADMIN)*

```json
{
  "plat_confidence_threshold": "0.85",
  "sticker_confidence_threshold": "0.80",
  "fused_confidence_threshold": "0.90",
  "session_window_seconds": "3",
  "min_images_per_session": "2"
}
```

---

## 8. WebSocket — Alert Realtime

### `WS /ws/alerts?token=<JWT>`

Server mem-push event; client (dashboard) wajib mengirim `{"type":"ping"}` tiap 25 s.

### Event: `gate.alert`

```json
{
  "type": "gate.alert",
  "level": "GREEN",
  "session_id": "3f8c1e42-...",
  "message": "Kendaraan warga/karyawan perusahaan",
  "direction": "IN",
  "plate_final": "B1234XYZ",
  "sticker_final": "STK-WRG-0042",
  "fused_confidence": 0.94,
  "vehicle": { "jenis": "KARYAWAN", "owner_name": "Andi Pratama" },
  "snapshot_url": "/snapshots/...",
  "snapshot_urls": ["...", "..."],
  "awaiting_action": false,
  "at": "2026-10-13T07:29:09+07:00"
}
```

```json
{
  "type": "gate.alert",
  "level": "RED",
  "session_id": "9d1f...",
  "message": "Kendaraan tidak dikenal",
  "plate_final": "B9999ZZ",
  "fused_confidence": 0.41,
  "vehicle": null,
  "snapshot_urls": ["...", "..."],
  "awaiting_action": true,
  "at": "2026-10-13T07:29:10+07:00"
}
```

### Event lain

| Type | Kapan | Payload inti |
| :--- | :--- | :--- |
| `gate.opened` | Motor bergerak / gate terbuka | `session_id`, `trigger` (`AUTO`/`OVERRIDE`), `at` |
| `gate.closed` | Gate tertutup | `session_id`, `at` |
| `gate.failed` | Motor tidak merespons | `session_id`, `reason` |
| `device.status` | Perangkat online/offline | `code`, `status`, `at` |
| `system.degraded` | CCTV/AI/MQTT bermasalah | `component`, `message` |

---

## 9. Endpoint MQTT (bukan HTTP) — Kontrak Perangkat Gate

| Topik | Arah | Payload |
| :--- | :--- | :--- |
| `gate/{direction}/motor/cmd` | Backend → ESP32 | `{"cmd":"OPEN","session_id":"...","duration_ms":3000}` |
| `gate/{direction}/motor/ack` | ESP32 → Backend | `{"session_id":"...","status":"OPENED","at":"..."}` |
| `gate/{direction}/sensor` | ESP32 → Backend | `{"state":"OPEN"\|"CLOSED","at":"..."}` |
| `device/heartbeat/{code}` | Perangkat → Backend | `{"status":"ONLINE","uptime_s":1234}` |

QoS 1, `retain=false`, LWT perangkat diatur ke `{"status":"OFFLINE"}` pada topik `device/status/{code}`.

---

## 10. Ringkasan Endpoint

| Method | Path | Auth | Role |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/auth/login` | — | publik |
| POST | `/api/v1/auth/refresh` | JWT | semua |
| POST | `/api/v1/auth/logout` | JWT | semua |
| POST | `/api/v1/detection/push` | `X-Internal-Key` | internal |
| POST | `/api/v1/detection/session/close` | `X-Internal-Key` | internal |
| GET | `/api/v1/gate/decision/{session_id}` | JWT | semua |
| POST | `/api/v1/gate/{session_id}/override` | JWT | SATPAM, SUPERVISOR, ADMIN |
| POST | `/api/v1/gate/{session_id}/reject` | JWT | SATPAM, SUPERVISOR, ADMIN |
| POST | `/api/v1/gate/{device_id}/open` | JWT | SUPERVISOR, ADMIN |
| GET | `/api/v1/vehicles` | JWT | semua |
| POST/PUT/DELETE | `/api/v1/vehicles[/{id}]` | JWT | ADMIN |
| GET/POST | `/api/v1/bookings` | JWT | semua / ADMIN |
| POST | `/api/v1/bookings/{id}/cancel` | JWT | SUPERVISOR, ADMIN |
| GET | `/api/v1/logs` | JWT | semua |
| GET | `/api/v1/logs/{session_id}` | JWT | semua |
| GET | `/api/v1/logs/export` | JWT | SUPERVISOR, ADMIN |
| GET | `/api/v1/devices` | JWT | ADMIN |
| POST | `/api/v1/devices/heartbeat` | `X-Internal-Key` | internal |
| GET/PUT | `/api/v1/settings` | JWT | ADMIN |
| WS | `/ws/alerts` | JWT (query) | semua |

---

## 11. Contoh Alur Lengkap (cURL)

```bash
# 1. AI mengirim gambar CCTV 1
curl -X POST http://gate-backend.local:8000/api/v1/detection/push \
  -H "X-Internal-Key: $INTERNAL_KEY" -H "Content-Type: application/json" \
  -d '{"session_id":"3f8c1e42","camera_id":"cam_gate_masuk_1","direction":"IN","plat_text":"B1234XYZ","plat_confidence":0.92,"sticker_code":"STK-WRG-0042","sticker_confidence":0.88,"image_base64":"...","captured_at":"2026-10-13T07:29:08+07:00"}'

# 2. AI mengirim gambar CCTV 2
curl -X POST http://gate-backend.local:8000/api/v1/detection/push \
  -H "X-Internal-Key: $INTERNAL_KEY" -H "Content-Type: application/json" \
  -d '{"session_id":"3f8c1e42","camera_id":"cam_gate_masuk_2","direction":"IN","plat_text":"B1234XYZ","plat_confidence":0.90,"image_base64":"...","captured_at":"2026-10-13T07:29:08.5+07:00"}'

# 3. Tutup sesi -> backend evaluasi & buka gate otomatis
curl -X POST http://gate-backend.local:8000/api/v1/detection/session/close \
  -H "X-Internal-Key: $INTERNAL_KEY" -H "Content-Type: application/json" \
  -d '{"session_id":"3f8c1e42","reason":"WINDOW_ELAPSED"}'

# 4. Cek hasil keputusan
curl http://gate-backend.local:8000/api/v1/gate/decision/3f8c1e42 -H "Authorization: Bearer $TOKEN"

# 5. Bila NO_MATCH, satpam bypass
curl -X POST http://gate-backend.local:8000/api/v1/gate/3f8c1e42/override \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"note":"Kendaraan tamu, sudah verifikasi KTP di pos. Aman."}'
```
