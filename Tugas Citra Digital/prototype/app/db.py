"""Lapisan data SQLite untuk prototipe.

Skema disederhanakan dari ``docs/DATABASE.md`` (PostgreSQL) agar prototipe bisa
jalan tanpa server DB. Nama tabel & kolom sengaja dipertahankan sama supaya
migrasi ke PostgreSQL nanti hanya soal DDL, bukan refactor kode.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('admin', 'satpam')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gate_devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    cctv_role   TEXT NOT NULL CHECK (cctv_role IN ('approach', 'gate')),
    rtsp_url    TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS master_vehicles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number  TEXT NOT NULL UNIQUE,
    sticker_code  TEXT UNIQUE,
    owner_name    TEXT NOT NULL,
    owner_type    TEXT NOT NULL CHECK (owner_type IN ('warga', 'karyawan', 'tamu')),
    vehicle_type  TEXT NOT NULL DEFAULT 'car',
    requires_booking INTEGER NOT NULL DEFAULT 0,
    valid_until   TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS car_bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number  TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    valid_from    TEXT NOT NULL,
    valid_to      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'expired', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS detection_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT NOT NULL,
    source             TEXT NOT NULL CHECK (source IN ('cctv', 'manual')),
    cctv_role          TEXT,
    image_path         TEXT,
    plate_text         TEXT,
    plate_confidence   REAL NOT NULL DEFAULT 0,
    sticker_code       TEXT,
    sticker_confidence REAL NOT NULL DEFAULT 0,
    fused_score        REAL NOT NULL DEFAULT 0,
    sharpness          REAL NOT NULL DEFAULT 0,
    is_best_frame      INTEGER NOT NULL DEFAULT 0,
    ocr_backend        TEXT,
    vehicle_class      TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gate_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    decision            TEXT NOT NULL CHECK (decision IN
                          ('AUTO_OPEN','NO_MATCH','OCR_FAILED','LOW_CONFIDENCE',
                           'MANUAL_OVERRIDE','REJECTED')),
    plate_text          TEXT,
    sticker_code        TEXT,
    fused_score         REAL NOT NULL DEFAULT 0,
    matched_vehicle_id  INTEGER REFERENCES master_vehicles(id),
    matched_booking_id  INTEGER REFERENCES car_bookings(id),
    snapshot_url        TEXT,
    reason              TEXT,
    override_by         TEXT,
    override_note       TEXT,
    override_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    -- Audit wajib: bypass tanpa jejak tidak boleh masuk DB.
    CHECK (decision <> 'MANUAL_OVERRIDE'
           OR (override_by IS NOT NULL AND override_note IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS system_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_detection_session ON detection_events(session_id);
CREATE INDEX IF NOT EXISTS idx_gate_logs_created ON gate_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gate_logs_decision ON gate_logs(decision);
CREATE INDEX IF NOT EXISTS idx_bookings_plate ON car_bookings(plate_number, status);
"""

SEED_USERS = [
    ("admin", "Administrator Sistem", "admin"),
    ("satpam1", "Budi Santoso", "satpam"),
]

SEED_DEVICES = [
    ("CCTV 1 - Zona Pendekatan", "in", "approach", "rtsp://192.168.1.11:554/stream1"),
    ("CCTV 2 - Zona Gate", "in", "gate", "rtsp://192.168.1.12:554/stream1"),
]

SEED_VEHICLES = [
    ("B 1234 XYZ", "STK-WRG-0042", "Ahmad Wijaya", "warga", "car", 0, None),
    ("D 5678 ABC", "STK-KRY-0107", "Siti Rahayu", "karyawan", "car", 0, None),
    ("B 9012 QWE", None, "PT Mitra Logistik", "tamu", "truck", 1, None),
]

SEED_BOOKINGS = [
    ("B 9012 QWE", "Pengiriman material", "2020-01-01 00:00:00", "2099-12-31 23:59:59", "active"),
]


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Tambah kolom yang belum ada di DB lama (SQLite tak punya IF NOT EXISTS)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(detection_events)")}
    if "vehicle_class" not in existing:
        conn.execute("ALTER TABLE detection_events ADD COLUMN vehicle_class TEXT")


def init_db(force: bool = False) -> None:
    """Buat skema + seed. Idempoten; ``force`` menghapus DB lama."""
    if force and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    with session() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.executemany("INSERT INTO users (username, full_name, role) VALUES (?,?,?)", SEED_USERS)
            conn.executemany(
                "INSERT INTO gate_devices (name, direction, cctv_role, rtsp_url) VALUES (?,?,?,?)",
                SEED_DEVICES,
            )
            conn.executemany(
                "INSERT INTO master_vehicles "
                "(plate_number, sticker_code, owner_name, owner_type, vehicle_type, requires_booking, valid_until) "
                "VALUES (?,?,?,?,?,?,?)",
                SEED_VEHICLES,
            )
            conn.executemany(
                "INSERT INTO car_bookings (plate_number, purpose, valid_from, valid_to, status) VALUES (?,?,?,?,?)",
                SEED_BOOKINGS,
            )
        for key, value in config.DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?,?)", (key, str(value)))


# --- Query helpers -----------------------------------------------------------

def settings() -> dict[str, float]:
    """Ambil ambang keputusan. Cache di memori, invalidasi lewat :func:`set_setting`."""
    cached = _settings_cache.get("value")
    if cached is not None:
        return cached
    with session() as conn:
        rows = conn.execute("SELECT key, value FROM system_settings").fetchall()
    merged = dict(config.DEFAULTS)
    for row in rows:
        try:
            merged[row["key"]] = float(row["value"])
        except (TypeError, ValueError):
            continue
    _settings_cache["value"] = merged
    return merged


_settings_cache: dict[str, dict[str, float]] = {}


def set_setting(key: str, value: float) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO system_settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
    _settings_cache.clear()


def raw_setting(key: str, default: str = "") -> str:
    """Ambil nilai setting non-numerik (mis. varian model) apa adanya."""
    with session() as conn:
        row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def find_vehicle(plate_text: str | None, sticker_code: str | None) -> sqlite3.Row | None:
    """Cocokkan plat ATAU stiker ke master_vehicles yang aktif & belum kedaluwarsa."""
    clauses, params = [], []
    if plate_text:
        # Bandingkan tanpa spasi: OCR menghasilkan "B1234XYZ", DB menyimpan "B 1234 XYZ".
        clauses.append("REPLACE(plate_number, ' ', '') = ?")
        params.append(plate_text)
    if sticker_code:
        clauses.append("sticker_code = ?")
        params.append(sticker_code)
    if not clauses:
        return None
    sql = (
        "SELECT * FROM master_vehicles WHERE is_active = 1 "
        "AND (valid_until IS NULL OR valid_until >= datetime('now')) "
        f"AND ({' OR '.join(clauses)}) LIMIT 1"
    )
    with session() as conn:
        return conn.execute(sql, params).fetchone()


def active_booking(plate_number: str) -> sqlite3.Row | None:
    with session() as conn:
        return conn.execute(
            "SELECT * FROM car_bookings WHERE REPLACE(plate_number, ' ', '') = ? AND status = 'active' "
            "AND valid_from <= datetime('now') AND valid_to >= datetime('now') "
            "ORDER BY valid_to DESC LIMIT 1",
            (plate_number,),
        ).fetchone()

# --- Master kendaraan ----------------------------------------------------------

def list_vehicles() -> list[sqlite3.Row]:
    with session() as conn:
        return conn.execute(
            "SELECT * FROM master_vehicles ORDER BY is_active DESC, id"
        ).fetchall()

def get_vehicle(vehicle_id: int) -> sqlite3.Row | None:
    with session() as conn:
        return conn.execute("SELECT * FROM master_vehicles WHERE id = ?", (vehicle_id,)).fetchone()

def insert_vehicle(**fields: Any) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    with session() as conn:
        cur = conn.execute(f"INSERT INTO master_vehicles ({cols}) VALUES ({marks})", list(fields.values()))
        return int(cur.lastrowid)

def update_vehicle(vehicle_id: int, **fields: Any) -> bool:
    assigns = ", ".join(f"{col} = ?" for col in fields)
    with session() as conn:
        cur = conn.execute(
            f"UPDATE master_vehicles SET {assigns} WHERE id = ?", [*fields.values(), vehicle_id]
        )
        return cur.rowcount > 0

def delete_vehicle(vehicle_id: int) -> bool:
    """Hard delete. SQLite menolak bila kendaraan sudah tercatat di gate_logs (FK)."""
    with session() as conn:
        cur = conn.execute("DELETE FROM master_vehicles WHERE id = ?", (vehicle_id,))
        return cur.rowcount > 0


def insert_detection_event(**fields: Any) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    with session() as conn:
        cur = conn.execute(f"INSERT INTO detection_events ({cols}) VALUES ({marks})", list(fields.values()))
        return int(cur.lastrowid)


def insert_gate_log(**fields: Any) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    with session() as conn:
        cur = conn.execute(f"INSERT INTO gate_logs ({cols}) VALUES ({marks})", list(fields.values()))
        return int(cur.lastrowid)


def get_gate_log(log_id: int) -> sqlite3.Row | None:
    with session() as conn:
        return conn.execute("SELECT * FROM gate_logs WHERE id = ?", (log_id,)).fetchone()


def list_gate_logs(limit: int = 50, decision: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM gate_logs"
    params: list[Any] = []
    if decision:
        sql += " WHERE decision = ?"
        params.append(decision)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with session() as conn:
        return conn.execute(sql, params).fetchall()


def list_detection_events(session_id: str) -> list[sqlite3.Row]:
    with session() as conn:
        return conn.execute(
            "SELECT * FROM detection_events WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()


def stats() -> dict[str, int]:
    with session() as conn:
        rows = conn.execute("SELECT decision, COUNT(*) AS n FROM gate_logs GROUP BY decision").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM gate_logs").fetchone()[0]
        vehicles = conn.execute("SELECT COUNT(*) FROM master_vehicles WHERE is_active = 1").fetchone()[0]
    out = {row["decision"]: row["n"] for row in rows}
    out["TOTAL"] = total
    out["VEHICLES"] = vehicles
    return out


def resolve_override(log_id: int, decision: str, username: str, note: str) -> bool:
    """Catat tindakan satpam (bypass / tolak). Hanya untuk log yang belum final."""
    with session() as conn:
        cur = conn.execute(
            "UPDATE gate_logs SET decision = ?, override_by = ?, override_note = ?, "
            "override_at = datetime('now') WHERE id = ? AND decision IN "
            "('NO_MATCH','OCR_FAILED','LOW_CONFIDENCE')",
            (decision, username, note, log_id),
        )
        return cur.rowcount > 0
