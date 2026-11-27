"""Aplikasi web Flask: dashboard satpam, HRGA, Bea Cukai, upload foto manual, simulasi CCTV, log.

Sengaja tanpa WebSocket: dashboard melakukan polling ringan ke ``/api/alerts``
tiap 3 detik. Untuk prototipe ini cukup, dan menghilangkan satu dependensi.
"""

from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from . import auth, config, db, detect_yolo, fusion, ocr, pipeline, service, simulate, sticker, vehicles

VEHICLE_TYPES = ("car", "motorcycle", "truck", "custom")
OWNER_TYPES = ("warga", "karyawan", "tamu")

# Rate-limiting login berbasis memori per IP (SEC-1): maks 5 gagal per 60 detik.
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 60.0
_LOGIN_FAILURES: dict[str, list[float]] = {}
_PLATE_INPUT_RE = re.compile(r"^[A-Z0-9 ]+$")


def _login_rate_limited(remote_addr: str) -> bool:
    """True bila IP telah mencapai batas gagal login dalam jendela aktif."""
    now = time.monotonic()
    key = remote_addr or "local"
    recent = [ts for ts in _LOGIN_FAILURES.get(key, []) if now - ts < LOGIN_WINDOW_SECONDS]
    if recent:
        _LOGIN_FAILURES[key] = recent
    else:
        _LOGIN_FAILURES.pop(key, None)
    return len(recent) >= LOGIN_MAX_FAILURES


def _record_login_failure(remote_addr: str) -> None:
    now = time.monotonic()
    key = remote_addr or "local"
    recent = [ts for ts in _LOGIN_FAILURES.get(key, []) if now - ts < LOGIN_WINDOW_SECONDS]
    recent.append(now)
    _LOGIN_FAILURES[key] = recent


def _clear_login_failures(remote_addr: str) -> None:
    _LOGIN_FAILURES.pop(remote_addr or "local", None)


# Run training YOLO — dipantau halaman /training. Pilih run terbaru otomatis.
def _latest_train_run() -> Path:
    candidates = [
        d.parent for d in config.BASE_DIR.glob("runs/detect/*/results.csv") if d.parent.is_dir()
    ]
    if not candidates:
        return config.BASE_DIR / "runs" / "detect" / "smartgate-colab-v6-yolo11n"
    return max(candidates, key=lambda d: (d / "results.csv").stat().st_mtime)


TRAIN_RUN_DIR = _latest_train_run()
TRAIN_PLOTS = (
    "results.png",
    "labels.jpg",
    "train_batch0.jpg",
    "confusion_matrix_normalized.png",
    "confusion_matrix.png",
)


def _csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def _secret_key() -> str:
    """Kunci sesi: ``SGS_SECRET_KEY`` (produksi) atau file acak persisten (demo)."""
    from_env = os.getenv("SGS_SECRET_KEY", "").strip()
    if from_env:
        return from_env
    path = config.DATA_DIR / "secret_key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    config.ensure_dirs()
    value = secrets.token_hex(32)
    path.write_text(value, encoding="utf-8")
    return value


def _csv_safe(value: Any) -> str:
    """Cegah CSV formula injection saat berkas dibuka di Microsoft Excel."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _extract_log_filters(args: Any, role: str | None) -> dict[str, str]:
    """Ambil & normalisasi parameter filter log dari query string."""
    visit_category = (args.get("visit_category") or "").strip().upper()
    # Role Bea Cukai default otomatis terfilter ke CARGO_LOGISTIC bila tidak memilih kategori lain.
    if role == "beacukai" and not visit_category and "visit_category" not in args:
        visit_category = "CARGO_LOGISTIC"
    return {
        "q": (args.get("q") or "").strip(),
        "direction": (args.get("direction") or "").strip().upper(),
        "visit_category": visit_category,
        "status": (args.get("status") or args.get("decision") or "").strip().upper(),
        "bc_doc_type": (args.get("bc_doc_type") or "").strip().upper(),
        "date_from": (args.get("date_from") or "").strip(),
        "date_to": (args.get("date_to") or "").strip(),
    }


def _query_logs_from_filters(filters: dict[str, str], limit: int = 200) -> list[Any]:
    return db.list_gate_logs(
        limit=limit,
        q=filters["q"] or None,
        direction=filters["direction"] or None,
        visit_category=filters["visit_category"] or None,
        status=filters["status"] or None,
        bc_doc_type=filters["bc_doc_type"] or None,
        date_from=filters["date_from"] or None,
        date_to=filters["date_to"] or None,
    )


def create_app() -> Flask:
    config.ensure_dirs()
    db.init_db()

    try:
        detect_yolo.set_variant(db.raw_setting("yolo_variant", "yolov8n"))
    except ValueError:
        pass  # nilai tersimpan tidak valid -> pakai default

    import threading

    def _warmup_models() -> None:
        ocr.warmup()
        detect_yolo.available()  # YOLO hangat di awal — scan pertama tidak lambat

    threading.Thread(target=_warmup_models, daemon=True).start()  # model siap sebelum scan pertama

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False
    app.secret_key = _secret_key()
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # --- Login ----------------------------------------------------------------

    @app.get("/login")
    def login_page() -> str:
        return render_template("login.html", error=None)

    @app.post("/login")
    def login_submit() -> Any:
        client_ip = request.remote_addr or "local"
        if _login_rate_limited(client_ip):
            return (
                render_template(
                    "login.html",
                    error="Terlalu banyak percobaan login gagal. Silakan tunggu 60 detik sebelum mencoba lagi.",
                ),
                429,
            )
        try:
            auth.login((request.form.get("username") or "").strip(), request.form.get("password") or "")
        except ValueError as exc:
            _record_login_failure(client_ip)
            return render_template("login.html", error=str(exc)), 401
        _clear_login_failures(client_ip)
        target = request.args.get("next") or ""
        if target.startswith("/") and not target.startswith("//"):
            return redirect(target)
        if auth.current_role() == "beacukai":
            return redirect(url_for("logs_page"))
        return redirect(url_for("dashboard"))

    @app.post("/logout")
    def logout() -> Any:
        auth.logout()
        return redirect(url_for("login_page"))

    @app.after_request
    def security_headers(resp: Any) -> Any:
        """Header keamanan (M3) — CSP juga menahan XSS yang lolos escape."""
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    @app.before_request
    def csrf_protect() -> Any:
        """Tolak POST/PUT/DELETE tanpa token sesi (H5). Anonymous tetap ditolak
        401 oleh login_required — jangan tukar pesan errornya."""
        if request.method not in ("POST", "PUT", "DELETE") or auth.current_user() is None:
            return None
        token = request.form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
        if not secrets.compare_digest(token, session.get("csrf", "")):
            abort(403, "CSRF token invalid")
        return None

    @app.context_processor
    def _inject_auth() -> dict[str, Any]:
        return {
            "auth": auth,
            "csrf_token": _csrf_token(),
            "app_version": config.APP_VERSION,
            "role_labels": auth.ROLE_LABELS,
            "visit_category_labels": db.VISIT_CATEGORY_LABELS,
            "format_dwell": db.format_dwell,
        }

    # --- Halaman --------------------------------------------------------------

    @app.get("/")
    @auth.login_required
    def dashboard() -> Any:
        role = auth.current_role()
        recent_logs = (
            db.list_gate_logs(limit=12, visit_category="CARGO_LOGISTIC")
            if role == "beacukai"
            else db.list_gate_logs(limit=12)
        )
        return render_template(
            "dashboard.html",
            stats=db.stats(),
            pending=service.pending_logs(limit=8) if role in ("admin", "satpam") else [],
            logs=recent_logs,
            labels=fusion.DECISION_LABEL,
            alerts=fusion.DECISION_ALERT,
            backend=ocr.active_backend(),
            decoders=sticker.available_decoders(),
            vehicles=_vehicles(),
            can_operate=role in ("admin", "satpam"),
            can_manage_bookings=role in ("admin", "hrga"),
        )

    @app.get("/upload")
    @auth.login_required
    @auth.roles_required("admin", "satpam")
    def upload_page() -> str:
        return render_template("upload.html", backend=ocr.active_backend())

    @app.get("/logs")
    @auth.login_required
    def logs_page() -> str:
        role = auth.current_role()
        filters = _extract_log_filters(request.args, role)
        rows = _query_logs_from_filters(filters, limit=200)
        return render_template(
            "logs.html",
            logs=rows,
            labels=fusion.DECISION_LABEL,
            alerts=fusion.DECISION_ALERT,
            filters=filters,
            visit_categories=db.VISIT_CATEGORIES,
            bc_doc_types=db.BC_DOC_TYPES,
            backend=ocr.active_backend(),
        )

    @app.get("/logs/<int:log_id>")
    @auth.login_required
    def log_detail(log_id: int) -> str:
        row = db.get_gate_log(log_id)
        if row is None:
            abort(404)
        log_dict = dict(row)
        paired_row = db.get_gate_log(log_dict["paired_log_id"]) if log_dict.get("paired_log_id") else None
        role = auth.current_role()
        return render_template(
            "log_detail.html",
            log=log_dict,
            paired_log=dict(paired_row) if paired_row is not None else None,
            dwell_label=db.format_dwell(log_dict.get("dwell_minutes")),
            events=[dict(e) for e in db.list_detection_events(row["session_id"])],
            labels=fusion.DECISION_LABEL,
            alerts=fusion.DECISION_ALERT,
            pending=row["decision"] in fusion.PENDING_DECISIONS,
            can_act=role in ("admin", "satpam"),
            visit_categories=db.VISIT_CATEGORIES,
            bc_doc_types=db.BC_DOC_TYPES,
            stages=_stage_files(row["session_id"]),
            backend=ocr.active_backend(),
        )

    @app.get("/camera")
    @auth.login_required
    @auth.roles_required("admin", "satpam")
    def camera_page() -> str:
        return render_template("camera.html", backend=ocr.active_backend())

    @app.get("/training")
    @auth.login_required
    @auth.admin_required
    def training_page() -> str:
        return render_template("training.html", status=training_status(), backend=ocr.active_backend())

    @app.get("/training/plot/<name>")
    @auth.login_required
    @auth.admin_required
    def training_plot(name: str) -> Any:
        if name not in TRAIN_PLOTS:
            abort(404)
        path = TRAIN_RUN_DIR / name
        if not path.is_file():
            abort(404)
        return send_file(path)

    # --- Jadwal / Izin Kendaraan (HRGA & Admin) -------------------------------

    @app.get("/bookings")
    @auth.login_required
    @auth.roles_required("admin", "hrga")
    def bookings_page() -> str:
        status_filter = (request.args.get("status") or "").strip().upper() or None
        return _bookings_page(status_filter=status_filter)

    @app.post("/bookings/save")
    @auth.login_required
    @auth.roles_required("admin", "hrga")
    def bookings_save() -> Any:
        raw_plate = (request.form.get("plate_number") or "").strip().upper()
        fields = {
            "plate_number": raw_plate,
            "visit_category": (request.form.get("visit_category") or "GUEST").strip().upper(),
            "driver_or_guest_name": (request.form.get("driver_or_guest_name") or "").strip(),
            "company_or_vendor": (request.form.get("company_or_vendor") or "").strip(),
            "visit_purpose_or_host": (request.form.get("visit_purpose_or_host") or "").strip(),
            "bc_doc_type": (request.form.get("bc_doc_type") or "NONE").strip().upper(),
            "bc_doc_number": (request.form.get("bc_doc_number") or "").strip(),
            "valid_from": _normalize_dt_input(request.form.get("valid_from") or ""),
            "valid_until": _normalize_dt_input(request.form.get("valid_until") or ""),
            "status": "ACTIVE",
            "created_by": auth.current_user() or "",
        }
        error = _validate_booking(fields)
        if error:
            return _bookings_page(form_data=fields, error=error), 400
        db.insert_vehicle_booking(**fields)
        return redirect(url_for("bookings_page"))

    @app.post("/bookings/<int:booking_id>/status")
    @auth.login_required
    @auth.roles_required("admin", "hrga")
    def bookings_status(booking_id: int) -> Any:
        new_status = (request.form.get("status") or "").strip().upper()
        if new_status not in db.BOOKING_STATUSES:
            abort(400)
        db.update_vehicle_booking_status(booking_id, new_status)
        return redirect(url_for("bookings_page"))

    # --- Manajemen kendaraan ---------------------------------------------------

    @app.get("/vehicles")
    @auth.login_required
    @auth.roles_required("admin", "satpam", "hrga")
    def vehicles_page() -> str:
        edit_id = request.args.get("edit", type=int)
        row = db.get_vehicle(edit_id) if (edit_id and auth.current_role() == "admin") else None
        return _vehicles_page(edit=dict(row) if row else None)

    @app.post("/vehicles/save")
    @auth.login_required
    @auth.admin_required
    def vehicles_save() -> Any:
        vehicle_id = request.form.get("id", type=int)
        fields = {
            "plate_number": (request.form.get("plate_number") or "").strip().upper(),
            "sticker_code": (request.form.get("sticker_code") or "").strip().upper() or None,
            "owner_name": (request.form.get("owner_name") or "").strip(),
            "owner_type": (request.form.get("owner_type") or "").strip(),
            "vehicle_type": (request.form.get("vehicle_type") or "").strip(),
            "requires_booking": 1 if request.form.get("requires_booking") else 0,
            "valid_until": (request.form.get("valid_until") or "").strip() or None,
            "is_active": 1 if request.form.get("is_active") else 0,
        }
        error = _validate_vehicle(fields)
        if not error:
            try:
                if vehicle_id:
                    db.update_vehicle(vehicle_id, **fields)
                else:
                    db.insert_vehicle(**fields)
            except sqlite3.IntegrityError:
                error = "Plat nomor atau kode stiker sudah terdaftar."
        if error:
            return _vehicles_page(edit={**fields, "id": vehicle_id}, error=error), 400
        return redirect(url_for("vehicles_page"))

    @app.post("/vehicles/<int:vehicle_id>/delete")
    @auth.login_required
    @auth.admin_required
    def vehicles_delete(vehicle_id: int) -> Any:
        """Hapus kendaraan; bila sudah tercatat di log audit, cukup nonaktifkan
        agar jejak foto & keputusan tidak putus (FK menolak hard delete)."""
        try:
            db.delete_vehicle(vehicle_id)
        except sqlite3.IntegrityError:
            db.update_vehicle(vehicle_id, is_active=0)
        return redirect(url_for("vehicles_page"))

    # --- API ------------------------------------------------------------------

    @app.post("/api/evaluate")
    @auth.login_required
    @auth.roles_required("admin", "satpam")
    def api_evaluate() -> Any:
        """Foto manual / kamera: 1..N berkas diunggah, diproses sebagai satu sesi."""
        files = [f for f in request.files.getlist("images") if f and f.filename]
        if not files:
            return jsonify({"error": "Tidak ada berkas yang diunggah"}), 400
        if len(files) > 6:
            return jsonify({"error": "Maksimal 6 berkas per permintaan"}), 400

        images: list[tuple[str, Any, str | None]] = []
        for index, storage in enumerate(files, start=1):
            image = service.decode_image(storage.read())
            if image is None:
                return jsonify({"error": f"Berkas '{storage.filename}' bukan citra yang valid"}), 400
            images.append((f"manual{index}", image, None))

        def enabled(name: str, default: str = "1") -> bool:
            return request.args.get(name, default).strip().lower() not in {"0", "false", "off"}

        direction = (request.args.get("direction") or request.form.get("direction") or "IN").strip().upper()
        if direction not in db.DIRECTIONS:
            direction = "IN"

        # Fast hanya untuk auto scan; unggahan manual & scan simpan-log selalu penuh.
        fast = enabled("fast", "0")
        result = service.evaluate(
            images,
            source="manual",
            persist=request.args.get("persist", "1") != "0",
            plate_enabled=enabled("plate"),
            sticker_enabled=enabled("sticker"),
            fast=fast,
            direction=direction,
        )
        return jsonify({**result.as_dict(), "direction": direction})

    @app.post("/api/simulate")
    @auth.login_required
    @auth.roles_required("admin", "satpam")
    def api_simulate() -> Any:
        """Simulasi sepasang frame CCTV 1 + CCTV 2."""
        payload = request.get_json(silent=True) or {}
        plate = (payload.get("plate") or "B 1234 XYZ").strip()
        sticker_code = (payload.get("sticker") or "").strip() or None
        hard = bool(payload.get("hard"))
        direction = str(payload.get("direction") or "IN").strip().upper()
        if direction not in db.DIRECTIONS:
            direction = "IN"
        vehicle = (payload.get("vehicle") or "car").strip().lower()
        if vehicle not in simulate.VEHICLES:
            return jsonify({"error": f"Kelas kendaraan tidak dikenal: {vehicle}"}), 400
        frames = simulate.cctv_pair(
            plate, sticker_code, seed=int(payload.get("seed") or 0), hard=hard, vehicle=vehicle
        )
        result = service.evaluate(frames, source="cctv", direction=direction)
        return jsonify({**result.as_dict(), "direction": direction})

    @app.get("/api/logs")
    @auth.login_required
    def api_list_logs() -> Any:
        role = auth.current_role()
        filters = _extract_log_filters(request.args, role)
        limit = min(max(request.args.get("limit", default=100, type=int) or 100, 1), 500)
        rows = _query_logs_from_filters(filters, limit=limit)
        return jsonify({"filters": filters, "count": len(rows), "logs": [dict(r) for r in rows]})

    @app.get("/api/logs/export.csv")
    @auth.login_required
    def api_export_logs_csv() -> Any:
        """Ekspor laporan audit CSV UTF-8 dengan BOM (siap dibuka langsung di Excel)."""
        role = auth.current_role()
        filters = _extract_log_filters(request.args, role)
        rows = _query_logs_from_filters(filters, limit=5000)

        buf = io.StringIO()
        buf.write("\ufeff")  # UTF-8 BOM untuk Microsoft Excel
        writer = csv.writer(buf)
        writer.writerow(
            [
                "ID",
                "Waktu",
                "Arah",
                "Kategori",
                "Plat Nomor",
                "Stiker",
                "Keputusan",
                "Skor Fusi",
                "Pasangan Log ID",
                "Durasi (Menit)",
                "Nama Pengemudi / Tamu",
                "Perusahaan / Ekspedisi",
                "Tujuan / PIC",
                "Jenis Dokumen BC",
                "No. Dokumen BC / Surat Jalan",
                "No. Segel",
                "Petugas Override",
                "Catatan Audit",
                "Waktu Override",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row["id"]),
                    _csv_safe(row["created_at"]),
                    _csv_safe(row["direction"]),
                    _csv_safe(row["visit_category"]),
                    _csv_safe(row["plate_text"] or ""),
                    _csv_safe(row["sticker_code"] or ""),
                    _csv_safe(row["decision"]),
                    f"{float(row['fused_score'] or 0.0):.2f}",
                    _csv_safe(row["paired_log_id"] if row["paired_log_id"] is not None else ""),
                    _csv_safe(row["dwell_minutes"] if row["dwell_minutes"] is not None else ""),
                    _csv_safe(row["driver_or_guest_name"]),
                    _csv_safe(row["company_or_vendor"]),
                    _csv_safe(row["visit_purpose_or_host"]),
                    _csv_safe(row["bc_doc_type"]),
                    _csv_safe(row["bc_doc_number"]),
                    _csv_safe(row["seal_number"]),
                    _csv_safe(row["override_by"] or ""),
                    _csv_safe(row["override_note"] or ""),
                    _csv_safe(row["override_at"] or ""),
                ]
            )

        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="smartgate_logs_{stamp}.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/logs/<int:log_id>/action")
    @auth.login_required
    @auth.roles_required("admin", "satpam")
    def api_guard_action(log_id: int) -> Any:
        payload = request.get_json(silent=True) or {}
        meta_keys = (
            "direction",
            "visit_category",
            "driver_or_guest_name",
            "company_or_vendor",
            "visit_purpose_or_host",
            "bc_doc_type",
            "bc_doc_number",
            "seal_number",
        )
        metadata = {k: payload[k] for k in meta_keys if k in payload}
        ok, message = service.guard_action(
            log_id,
            str(payload.get("action", "")),
            auth.current_user() or "",  # identitas dari sesi server, bukan body (C2)
            str(payload.get("note") or ""),
            metadata=metadata or None,
        )
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.get("/api/alerts")
    @auth.login_required
    def api_alerts() -> Any:
        """Polling dashboard: log terbaru + daftar yang menunggu tindakan."""
        role = auth.current_role()
        return jsonify(
            {
                "pending": service.pending_logs(limit=10) if role in ("admin", "satpam") else [],
                "stats": db.stats(),
                "latest_id": (db.list_gate_logs(limit=1) or [{"id": 0}])[0]["id"],
            }
        )

    @app.get("/api/settings")
    @auth.login_required
    @auth.admin_required
    def api_get_settings() -> Any:
        return jsonify(
            {
                **db.settings(),
                "yolo_variant": detect_yolo.current_variant(),
                "yolo_variants": detect_yolo.available_variants(),
            }
        )

    @app.post("/api/settings")
    @auth.login_required
    @auth.admin_required
    def api_set_settings() -> Any:
        payload = request.get_json(silent=True) or {}
        updated: dict[str, Any] = {}
        if "yolo_variant" in payload:
            variant = str(payload.pop("yolo_variant"))
            try:
                detect_yolo.set_variant(variant)
            except ValueError:
                return jsonify({"error": f"Varian model tidak dikenal: {variant}"}), 400
            db.set_setting("yolo_variant", variant)
            updated["yolo_variant"] = variant
        for key, value in payload.items():
            if key not in config.DEFAULTS:
                continue
            try:
                db.set_setting(key, float(value))
                updated[key] = float(value)
            except (TypeError, ValueError):
                return jsonify({"error": f"Nilai tidak valid untuk {key}"}), 400
        return jsonify({"updated": updated, "settings": db.settings()})

    @app.get("/api/health")
    @auth.login_required
    def api_health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "plate_backend": detect_yolo.status(),
                "ocr_backend": ocr.active_backend(),
                "detection_roi": config.DETECTION_ROI,
                "detection_gamma": config.DETECTION_GAMMA,
                "sticker_decoders": sticker.available_decoders(),
                "db": str(config.DB_PATH),
            }
        )

    @app.get("/snapshots/<path:relative>")
    @auth.login_required
    def snapshot(relative: str) -> Any:
        path = service.snapshot_path(relative)
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/jpeg" if path.suffix == ".jpg" else "image/png")

    @app.get("/diagnostics/<path:relative>")
    @auth.login_required
    def diagnostic(relative: str) -> Any:
        path = service.diagnostic_path(relative)
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/jpeg")

    @app.errorhandler(413)
    def too_large(_: Any) -> Any:
        return jsonify({"error": f"Ukuran unggahan melebihi {config.MAX_UPLOAD_MB} MB"}), 413

    return app


def _normalize_dt_input(raw: str) -> str:
    """Ubah input HTML datetime-local ('YYYY-MM-DDTHH:MM') menjadi 'YYYY-MM-DD HH:MM:00'."""
    val = raw.strip().replace("T", " ")
    if len(val) == 10:
        return f"{val} 00:00:00"
    if len(val) == 16:
        return f"{val}:00"
    return val


def _validate_booking(fields: dict[str, Any]) -> str | None:
    plate = fields.get("plate_number") or ""
    if not plate:
        return "Plat nomor wajib diisi."
    if len(plate) > 16 or not _PLATE_INPUT_RE.fullmatch(plate):
        return "Plat nomor maksimal 16 karakter dan hanya boleh berisi huruf, angka, atau spasi."
    _, err = service.validate_log_metadata(fields)
    if err:
        return err
    if not fields.get("valid_from") or not fields.get("valid_until"):
        return "Waktu mulai dan berakhir wajib diisi."
    if fields["valid_from"] > fields["valid_until"]:
        return "Waktu berakhir harus lebih besar dari waktu mulai."
    return None


def _bookings_page(
    form_data: dict[str, Any] | None = None,
    error: str | None = None,
    status_filter: str | None = None,
) -> str:
    return render_template(
        "bookings.html",
        rows=db.list_vehicle_bookings(status=status_filter, limit=200),
        form_data=form_data or {},
        error=error,
        status_filter=status_filter or "",
        visit_categories=db.VISIT_CATEGORIES,
        bc_doc_types=db.BC_DOC_TYPES,
        booking_statuses=db.BOOKING_STATUSES,
        backend=ocr.active_backend(),
    )


def _vehicles() -> list[dict[str, Any]]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT plate_number, sticker_code, owner_name, owner_type, requires_booking "
            "FROM master_vehicles WHERE is_active = 1 ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def training_status() -> dict[str, Any]:
    """Status training YOLO dari results.csv run — untuk halaman /training."""
    epochs: list[dict[str, str]] = []
    csv_path = TRAIN_RUN_DIR / "results.csv"
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as fh:
            epochs = [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(fh)]
    weights = TRAIN_RUN_DIR / "weights" / "best.pt"
    summary: dict[str, Any] = {}
    summary_path = TRAIN_RUN_DIR / "evaluation_summary.json"
    if summary_path.is_file():
        import json

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "run_name": TRAIN_RUN_DIR.name,
        "summary": summary,
        "epochs": epochs,
        "latest": epochs[-1] if epochs else None,
        "plots": [name for name in TRAIN_PLOTS if (TRAIN_RUN_DIR / name).is_file()],
        "weights_ready": weights.is_file(),
        "weights_size_mb": round(weights.stat().st_size / 1e6, 1) if weights.is_file() else 0,
        "variants": detect_yolo.available_variants(),
        "active_variant": detect_yolo.current_variant(),
        "plate_backend": detect_yolo.status(),
    }


def _validate_vehicle(fields: dict[str, Any]) -> str | None:
    plate = fields.get("plate_number") or ""
    if not plate:
        return "Plat nomor wajib diisi."
    if len(plate) > 16 or not _PLATE_INPUT_RE.fullmatch(plate):
        return "Plat nomor maksimal 16 karakter dan hanya boleh berisi huruf, angka, atau spasi."
    sticker_code = fields.get("sticker_code")
    if sticker_code and len(str(sticker_code)) > 64:
        return "Kode stiker maksimal 64 karakter."
    if not fields["owner_name"]:
        return "Nama pemilik wajib diisi."
    if fields["owner_type"] not in OWNER_TYPES:
        return "Jenis pemilik tidak valid."
    if fields["vehicle_type"] not in VEHICLE_TYPES:
        return "Jenis kendaraan tidak valid."
    if fields["valid_until"] and len(fields["valid_until"]) != 10:
        return "Format 'berlaku s.d.' harus YYYY-MM-DD."
    return None


def _vehicles_page(edit: dict[str, Any] | None = None, error: str | None = None) -> str:
    return render_template(
        "vehicles.html",
        rows=db.list_vehicles(),
        edit=edit,
        error=error,
        vehicle_types=[(key, vehicles.label(key)) for key in VEHICLE_TYPES],
        owner_types=OWNER_TYPES,
        can_edit=auth.current_role() == "admin",
        backend=ocr.active_backend(),
    )


def _stage_files(session_id: str) -> list[dict[str, str]]:
    """Daftar gambar tahap pipeline untuk halaman detail log."""
    folder = config.SNAPSHOT_DIR / session_id / "stages"
    if not folder.is_dir():
        return []
    order = ["original", "clahe", "denoise", "gray", "plate_raw", "plate_crop", "plate_enhanced", "sticker_crop"]
    files = sorted(folder.glob("*.png"))
    files.sort(key=lambda p: (order.index(p.stem.split("_")[-1]) if p.stem.split("_")[-1] in order else 99, p.name))
    return [{"name": p.stem, "url": f"snapshots/{session_id}/stages/{p.name}"} for p in files]
