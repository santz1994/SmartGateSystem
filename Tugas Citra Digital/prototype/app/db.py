"""Lapisan data SQLite untuk prototipe.

Skema disederhanakan dari ``docs/DATABASE.md`` (PostgreSQL) agar prototipe bisa
jalan tanpa server DB. Nama tabel & kolom sengaja dipertahankan sama supaya
migrasi ke PostgreSQL nanti hanya soal DDL, bukan refactor kode.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from . import config

ROLE_CHOICES = ("admin", "satpam", "hrga", "beacukai")
DIRECTIONS = ("IN", "OUT")
VISIT_CATEGORIES = ("COMPANY_CAR", "EMPLOYEE", "CARGO_LOGISTIC", "GUEST")
BC_DOC_TYPES = ("NONE", "BC 2.3", "BC 2.5", "BC 2.7", "BC 4.0", "BC 4.1", "SURAT_JALAN")
BOOKING_STATUSES = ("ACTIVE", "USED", "EXPIRED", "CANCELLED")

VISIT_CATEGORY_LABELS = {
    "COMPANY_CAR": "Mobil Perusahaan",
    "EMPLOYEE": "Karyawan",
    "CARGO_LOGISTIC": "Kargo / Logistik",
    "GUEST": "Tamu / Vendor",
}

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'satpam', 'hrga', 'beacukai')),
    password_hash TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number     TEXT NOT NULL UNIQUE,
    sticker_code     TEXT UNIQUE,
    owner_name       TEXT NOT NULL,
    owner_type       TEXT NOT NULL CHECK (owner_type IN ('warga', 'karyawan', 'tamu')),
    vehicle_type     TEXT NOT NULL DEFAULT 'car',
    requires_booking INTEGER NOT NULL DEFAULT 0,
    valid_until      TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1
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

CREATE TABLE IF NOT EXISTS vehicle_bookings (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number           TEXT NOT NULL,
    visit_category         TEXT NOT NULL DEFAULT 'GUEST'
                           CHECK (visit_category IN ('COMPANY_CAR', 'EMPLOYEE', 'CARGO_LOGISTIC', 'GUEST')),
    driver_or_guest_name   TEXT NOT NULL DEFAULT '',
    company_or_vendor      TEXT NOT NULL DEFAULT '',
    visit_purpose_or_host  TEXT NOT NULL DEFAULT '',
    bc_doc_type            TEXT NOT NULL DEFAULT 'NONE'
                           CHECK (bc_doc_type IN ('NONE', 'BC 2.3', 'BC 2.5', 'BC 2.7', 'BC 4.0', 'BC 4.1', 'SURAT_JALAN')),
    bc_doc_number          TEXT NOT NULL DEFAULT '',
    valid_from             TEXT NOT NULL,
    valid_until            TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'ACTIVE'
                           CHECK (status IN ('ACTIVE', 'USED', 'EXPIRED', 'CANCELLED')),
    created_by             TEXT NOT NULL DEFAULT '',
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
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
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id             TEXT NOT NULL,
    decision               TEXT NOT NULL CHECK (decision IN
                             ('AUTO_OPEN','NO_MATCH','OCR_FAILED','LOW_CONFIDENCE',
                              'MANUAL_OVERRIDE','REJECTED')),
    plate_text             TEXT,
    sticker_code           TEXT,
    fused_score            REAL NOT NULL DEFAULT 0,
    matched_vehicle_id     INTEGER REFERENCES master_vehicles(id),
    matched_booking_id     INTEGER REFERENCES car_bookings(id),
    snapshot_url           TEXT,
    reason                 TEXT,
    override_by            TEXT,
    override_note          TEXT,
    override_at            TEXT,
    direction              TEXT NOT NULL DEFAULT 'IN'
                           CHECK (direction IN ('IN', 'OUT')),
    visit_category         TEXT NOT NULL DEFAULT 'GUEST'
                           CHECK (visit_category IN ('COMPANY_CAR', 'EMPLOYEE', 'CARGO_LOGISTIC', 'GUEST')),
    paired_log_id          INTEGER REFERENCES gate_logs(id),
    dwell_minutes          INTEGER,
    driver_or_guest_name   TEXT NOT NULL DEFAULT '',
    company_or_vendor      TEXT NOT NULL DEFAULT '',
    visit_purpose_or_host  TEXT NOT NULL DEFAULT '',
    bc_doc_type            TEXT NOT NULL DEFAULT 'NONE'
                           CHECK (bc_doc_type IN ('NONE', 'BC 2.3', 'BC 2.5', 'BC 2.7', 'BC 4.0', 'BC 4.1', 'SURAT_JALAN')),
    bc_doc_number          TEXT NOT NULL DEFAULT '',
    seal_number            TEXT NOT NULL DEFAULT '',
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
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
CREATE INDEX IF NOT EXISTS idx_vehicle_bookings_plate_status ON vehicle_bookings(plate_number, status);
"""

SEED_USERS = [
    ("admin", "Administrator Sistem", "admin"),
    ("satpam1", "Budi Santoso", "satpam"),
    ("hrga1", "Rina Kusuma (HRGA)", "hrga"),
    ("beacukai1", "Petugas Pengawas Bea Cukai", "beacukai"),
]

# Password akun seed. PROTOTIPE: ganti lewat env sebelum dipakai di jaringan.
SEED_PASSWORDS = {
    "admin": os.getenv("SGS_ADMIN_PASSWORD", config.ADMIN_PASSWORD),
    "satpam1": os.getenv("SGS_SATPAM_PASSWORD", config.SATPAM_PASSWORD),
    "hrga1": os.getenv("SGS_HRGA_PASSWORD", config.HRGA_PASSWORD),
    "beacukai1": os.getenv("SGS_BEACUKAI_PASSWORD", config.BEACUKAI_PASSWORD),
}

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

SEED_VEHICLE_BOOKINGS = [
    (
        "B 9012 QWE",
        "CARGO_LOGISTIC",
        "Hendra Wijaya",
        "PT Mitra Logistik",
        "Gudang Bahan Baku / Warehouse",
        "BC 4.0",
        "000123-20261127",
        "2020-01-01 00:00:00",
        "2099-12-31 23:59:59",
        "ACTIVE",
        "hrga1",
    ),
]

_GATE_LOG_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("direction", "TEXT NOT NULL DEFAULT 'IN'"),
    ("visit_category", "TEXT NOT NULL DEFAULT 'GUEST'"),
    ("paired_log_id", "INTEGER"),
    ("dwell_minutes", "INTEGER"),
    ("driver_or_guest_name", "TEXT NOT NULL DEFAULT ''"),
    ("company_or_vendor", "TEXT NOT NULL DEFAULT ''"),
    ("visit_purpose_or_host", "TEXT NOT NULL DEFAULT ''"),
    ("bc_doc_type", "TEXT NOT NULL DEFAULT 'NONE'"),
    ("bc_doc_number", "TEXT NOT NULL DEFAULT ''"),
    ("seal_number", "TEXT NOT NULL DEFAULT ''"),
)


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


def _migrate_users_roles(conn: sqlite3.Connection) -> None:
    """Perluas CHECK constraint users.role pada DB lama agar menerima hrga & beacukai."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    ddl = row["sql"] if row and row["sql"] else ""
    if "'hrga'" in ddl and "'beacukai'" in ddl:
        return
    users_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    has_pw = "password_hash" in users_cols
    conn.execute(
        """
        CREATE TABLE users_v2 (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            full_name     TEXT NOT NULL,
            role          TEXT NOT NULL CHECK (role IN ('admin', 'satpam', 'hrga', 'beacukai')),
            password_hash TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    if has_pw:
        conn.execute(
            "INSERT INTO users_v2 (id, username, full_name, role, password_hash, created_at) "
            "SELECT id, username, full_name, role, password_hash, created_at FROM users"
        )
    else:
        conn.execute(
            "INSERT INTO users_v2 (id, username, full_name, role, created_at) "
            "SELECT id, username, full_name, role, created_at FROM users"
        )
    conn.execute("DROP TABLE users")
    conn.execute("ALTER TABLE users_v2 RENAME TO users")


def _migrate(conn: sqlite3.Connection) -> None:
    """Tambah kolom/tabel/indeks yang belum ada di DB lama secara idempoten."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(detection_events)")}
    if "vehicle_class" not in existing:
        conn.execute("ALTER TABLE detection_events ADD COLUMN vehicle_class TEXT")

    _migrate_users_roles(conn)
    users_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "password_hash" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    log_cols = {row["name"] for row in conn.execute("PRAGMA table_info(gate_logs)")}
    for col_name, col_def in _GATE_LOG_MIGRATIONS:
        if col_name not in log_cols:
            conn.execute(f"ALTER TABLE gate_logs ADD COLUMN {col_name} {col_def}")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gate_logs_dir_cat_created "
        "ON gate_logs(direction, visit_category, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gate_logs_bc_doc ON gate_logs(bc_doc_number)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vehicle_bookings_plate_status "
        "ON vehicle_bookings(plate_number, status)"
    )


def init_db(force: bool = False) -> None:
    """Buat skema + seed. Idempoten; ``force`` menghapus DB lama."""
    if force and config.DB_PATH.exists():
        config.DB_PATH.unlink()
    with session() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        from .auth import hash_password

        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO users (username, full_name, role, password_hash) VALUES (?,?,?,?)",
                [(u, n, r, hash_password(SEED_PASSWORDS[u])) for u, n, r in SEED_USERS],
            )
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
        else:
            # DB lama yang sudah punya admin/satpam tetap mendapat akun seed hrga1 & beacukai1.
            for u, n, r in SEED_USERS:
                conn.execute(
                    "INSERT OR IGNORE INTO users (username, full_name, role, password_hash) VALUES (?,?,?,?)",
                    (u, n, r, hash_password(SEED_PASSWORDS[u])),
                )

        if conn.execute("SELECT COUNT(*) FROM vehicle_bookings").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO vehicle_bookings "
                "(plate_number, visit_category, driver_or_guest_name, company_or_vendor, "
                "visit_purpose_or_host, bc_doc_type, bc_doc_number, valid_from, valid_until, status, created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                SEED_VEHICLE_BOOKINGS,
            )

        # DB lama (user tanpa password) tetap bisa login: isi hash default sekali.
        for username, password in SEED_PASSWORDS.items():
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ? AND password_hash IS NULL",
                (hash_password(password), username),
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


def set_setting(key: str, value: float | str) -> None:
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
        clauses.append("REPLACE(UPPER(plate_number), ' ', '') = ?")
        params.append(plate_text.replace(" ", "").upper())
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
    plate_key = plate_number.replace(" ", "").upper()
    with session() as conn:
        return conn.execute(
            "SELECT * FROM car_bookings WHERE REPLACE(UPPER(plate_number), ' ', '') = ? AND status = 'active' "
            "AND valid_from <= datetime('now') AND valid_to >= datetime('now') "
            "ORDER BY valid_to DESC LIMIT 1",
            (plate_key,),
        ).fetchone()


def active_vehicle_booking(plate_number: str) -> sqlite3.Row | None:
    """Cari jadwal aktif di ``vehicle_bookings`` untuk nomor plat tertentu."""
    plate_key = plate_number.replace(" ", "").upper()
    with session() as conn:
        return conn.execute(
            "SELECT * FROM vehicle_bookings "
            "WHERE REPLACE(UPPER(plate_number), ' ', '') = ? AND status = 'ACTIVE' "
            "AND valid_from <= datetime('now') AND valid_until >= datetime('now') "
            "ORDER BY valid_until DESC, id DESC LIMIT 1",
            (plate_key,),
        ).fetchone()


def list_vehicle_bookings(status: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
    sql = "SELECT * FROM vehicle_bookings"
    params: list[Any] = []
    if status and status in BOOKING_STATUSES:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with session() as conn:
        return conn.execute(sql, params).fetchall()


def get_vehicle_booking(booking_id: int) -> sqlite3.Row | None:
    with session() as conn:
        return conn.execute("SELECT * FROM vehicle_bookings WHERE id = ?", (booking_id,)).fetchone()


def insert_vehicle_booking(**fields: Any) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    with session() as conn:
        cur = conn.execute(f"INSERT INTO vehicle_bookings ({cols}) VALUES ({marks})", list(fields.values()))
        return int(cur.lastrowid)


def update_vehicle_booking_status(booking_id: int, status: str) -> bool:
    if status not in BOOKING_STATUSES:
        return False
    with session() as conn:
        cur = conn.execute("UPDATE vehicle_bookings SET status = ? WHERE id = ?", (status, booking_id))
        return cur.rowcount > 0


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


# --- Pairing IN <-> OUT & Durasi Kunjungan ------------------------------------

def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_dwell(minutes: int | None) -> str:
    """Format durasi kunjungan dalam menit menjadi teks terbaca (mis. '2 jam 15 menit')."""
    if minutes is None:
        return "—"
    mins = max(0, int(minutes))
    hours, rem = divmod(mins, 60)
    if hours and rem:
        return f"{hours} jam {rem} menit"
    if hours:
        return f"{hours} jam"
    return f"{rem} menit"


def _pair_exit_in_tx(
    conn: sqlite3.Connection,
    out_log_id: int,
    plate_text: str | None,
    out_created_at: str | None = None,
) -> tuple[int | None, int | None]:
    """Hubungkan log ``OUT`` dengan log ``IN`` terbaru yang belum berpasangan."""
    if not plate_text:
        return None, None
    plate_key = plate_text.replace(" ", "").upper()
    if not plate_key:
        return None, None
    in_row = conn.execute(
        "SELECT id, created_at FROM gate_logs "
        "WHERE direction = 'IN' AND paired_log_id IS NULL AND id <> ? "
        "AND REPLACE(UPPER(COALESCE(plate_text, '')), ' ', '') = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (out_log_id, plate_key),
    ).fetchone()
    if in_row is None:
        return None, None

    if out_created_at is None:
        out_row = conn.execute("SELECT created_at FROM gate_logs WHERE id = ?", (out_log_id,)).fetchone()
        out_created_at = out_row["created_at"] if out_row else None

    dt_in = _parse_ts(in_row["created_at"])
    dt_out = _parse_ts(out_created_at)
    dwell: int | None = None
    if dt_in is not None and dt_out is not None:
        dwell = max(0, int(round((dt_out - dt_in).total_seconds() / 60.0)))

    conn.execute(
        "UPDATE gate_logs SET paired_log_id = ?, dwell_minutes = ? WHERE id = ?",
        (int(in_row["id"]), dwell, out_log_id),
    )
    conn.execute(
        "UPDATE gate_logs SET paired_log_id = ?, dwell_minutes = ? WHERE id = ?",
        (out_log_id, dwell, int(in_row["id"])),
    )
    return int(in_row["id"]), dwell


def pair_exit_log(out_log_id: int) -> tuple[int | None, int | None]:
    """Wrapper publik untuk memasangkan log ``OUT`` dengan log ``IN`` terbuka."""
    with session() as conn:
        row = conn.execute(
            "SELECT id, direction, plate_text, paired_log_id, created_at FROM gate_logs WHERE id = ?",
            (out_log_id,),
        ).fetchone()
        if row is None or row["direction"] != "OUT" or row["paired_log_id"] is not None:
            return None, None
        return _pair_exit_in_tx(conn, int(row["id"]), row["plate_text"], row["created_at"])


def insert_gate_log(**fields: Any) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    with session() as conn:
        cur = conn.execute(f"INSERT INTO gate_logs ({cols}) VALUES ({marks})", list(fields.values()))
        log_id = int(cur.lastrowid)
        if fields.get("direction") == "OUT" and fields.get("plate_text") and not fields.get("paired_log_id"):
            _pair_exit_in_tx(conn, log_id, str(fields["plate_text"]), fields.get("created_at"))
        return log_id


def get_gate_log(log_id: int) -> sqlite3.Row | None:
    with session() as conn:
        return conn.execute("SELECT * FROM gate_logs WHERE id = ?", (log_id,)).fetchone()


def list_gate_logs(
    limit: int = 50,
    decision: str | None = None,
    *,
    q: str | None = None,
    direction: str | None = None,
    visit_category: str | None = None,
    status: str | None = None,
    bc_doc_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM gate_logs"
    clauses: list[str] = []
    params: list[Any] = []

    if status == "UNCLOSED_IN":
        clauses.append("direction = 'IN' AND paired_log_id IS NULL")
    elif status and not decision:
        decision = status

    if decision:
        clauses.append("decision = ?")
        params.append(decision)
    if direction and direction.upper() in DIRECTIONS:
        clauses.append("direction = ?")
        params.append(direction.upper())
    if visit_category and visit_category in VISIT_CATEGORIES:
        clauses.append("visit_category = ?")
        params.append(visit_category)
    if bc_doc_type and bc_doc_type in BC_DOC_TYPES:
        clauses.append("bc_doc_type = ?")
        params.append(bc_doc_type)
    if date_from:
        clauses.append("date(created_at) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(created_at) <= date(?)")
        params.append(date_to)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        clauses.append(
            "(COALESCE(plate_text, '') LIKE ? OR REPLACE(COALESCE(plate_text, ''), ' ', '') LIKE ? "
            "OR COALESCE(driver_or_guest_name, '') LIKE ? OR COALESCE(company_or_vendor, '') LIKE ? "
            "OR COALESCE(visit_purpose_or_host, '') LIKE ? OR COALESCE(bc_doc_number, '') LIKE ? "
            "OR COALESCE(seal_number, '') LIKE ?)"
        )
        compact = f"%{q.strip().replace(' ', '')}%"
        params.extend([needle, compact, needle, needle, needle, needle, needle])

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
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
        unclosed_in = conn.execute(
            "SELECT COUNT(*) FROM gate_logs WHERE direction = 'IN' AND paired_log_id IS NULL"
        ).fetchone()[0]
        cargo_today = conn.execute(
            "SELECT COUNT(*) FROM gate_logs "
            "WHERE visit_category = 'CARGO_LOGISTIC' AND date(created_at) = date('now')"
        ).fetchone()[0]
        active_guest_company = conn.execute(
            "SELECT COUNT(*) FROM gate_logs "
            "WHERE visit_category IN ('GUEST', 'COMPANY_CAR') "
            "AND direction = 'IN' AND paired_log_id IS NULL"
        ).fetchone()[0]
        active_bookings = conn.execute(
            "SELECT COUNT(*) FROM vehicle_bookings WHERE status = 'ACTIVE' "
            "AND valid_from <= datetime('now') AND valid_until >= datetime('now')"
        ).fetchone()[0]
    out = {row["decision"]: row["n"] for row in rows}
    out["TOTAL"] = total
    out["VEHICLES"] = vehicles
    out["UNCLOSED_IN"] = unclosed_in
    out["CARGO_TODAY"] = cargo_today
    out["ACTIVE_GUEST_COMPANY"] = active_guest_company
    out["ACTIVE_BOOKINGS"] = active_bookings
    return out


def resolve_override(
    log_id: int,
    decision: str,
    username: str,
    note: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Catat tindakan satpam (bypass / tolak) beserta metadata operasional opsional."""
    meta = metadata or {}
    allowed_meta = (
        "direction",
        "visit_category",
        "driver_or_guest_name",
        "company_or_vendor",
        "visit_purpose_or_host",
        "bc_doc_type",
        "bc_doc_number",
        "seal_number",
    )
    extra_cols: list[str] = []
    extra_vals: list[Any] = []
    for key in allowed_meta:
        if key in meta and meta[key] is not None:
            extra_cols.append(f"{key} = ?")
            extra_vals.append(meta[key])

    set_clause = (
        "decision = ?, override_by = ?, override_note = ?, override_at = datetime('now')"
        + ((", " + ", ".join(extra_cols)) if extra_cols else "")
    )
    with session() as conn:
        cur = conn.execute(
            f"UPDATE gate_logs SET {set_clause} WHERE id = ? AND decision IN "
            "('NO_MATCH','OCR_FAILED','LOW_CONFIDENCE')",
            [decision, username, note, *extra_vals, log_id],
        )
        if cur.rowcount <= 0:
            return False
        row = conn.execute(
            "SELECT direction, plate_text, paired_log_id, created_at FROM gate_logs WHERE id = ?",
            (log_id,),
        ).fetchone()
        if row and row["direction"] == "OUT" and row["plate_text"] and row["paired_log_id"] is None:
            _pair_exit_in_tx(conn, log_id, row["plate_text"], row["created_at"])
        return True


def update_gate_log_metadata(log_id: int, metadata: dict[str, Any]) -> bool:
    """Perbarui metadata kunjungan/dokumen BC pada log existing (Satpam/Admin)."""
    allowed_meta = (
        "direction",
        "visit_category",
        "driver_or_guest_name",
        "company_or_vendor",
        "visit_purpose_or_host",
        "bc_doc_type",
        "bc_doc_number",
        "seal_number",
    )
    cols = [f"{k} = ?" for k in allowed_meta if k in metadata and metadata[k] is not None]
    if not cols:
        return False
    vals = [metadata[k] for k in allowed_meta if k in metadata and metadata[k] is not None]
    with session() as conn:
        cur = conn.execute(f"UPDATE gate_logs SET {', '.join(cols)} WHERE id = ?", [*vals, log_id])
        if cur.rowcount <= 0:
            return False
        row = conn.execute(
            "SELECT direction, plate_text, paired_log_id, created_at FROM gate_logs WHERE id = ?",
            (log_id,),
        ).fetchone()
        if row and row["direction"] == "OUT" and row["plate_text"] and row["paired_log_id"] is None:
            _pair_exit_in_tx(conn, log_id, row["plate_text"], row["created_at"])
        return True
