"""Aplikasi web Flask: dashboard satpam, upload foto manual, simulasi CCTV, log.

Sengaja tanpa WebSocket: dashboard melakukan polling ringan ke ``/api/alerts``
tiap 3 detik. Untuk prototipe ini cukup, dan menghilangkan satu dependensi.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_file

from . import config, db, detect_yolo, fusion, ocr, pipeline, service, simulate, sticker

ROLE_CHOICES = ("satpam1", "admin")


def create_app() -> Flask:
    config.ensure_dirs()
    db.init_db()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False

    # --- Halaman --------------------------------------------------------------

    @app.get("/")
    def dashboard() -> str:
        return render_template(
            "dashboard.html",
            stats=db.stats(),
            pending=service.pending_logs(limit=8),
            logs=db.list_gate_logs(limit=12),
            labels=fusion.DECISION_LABEL,
            alerts=fusion.DECISION_ALERT,
            backend=ocr.active_backend(),
            decoders=sticker.available_decoders(),
            vehicles=_vehicles(),
        )

    @app.get("/upload")
    def upload_page() -> str:
        return render_template("upload.html", backend=ocr.active_backend())

    @app.get("/logs")
    def logs_page() -> str:
        decision = request.args.get("decision") or None
        return render_template(
            "logs.html",
            logs=db.list_gate_logs(limit=100, decision=decision),
            labels=fusion.DECISION_LABEL,
            alerts=fusion.DECISION_ALERT,
            selected=decision or "",
        )

    @app.get("/logs/<int:log_id>")
    def log_detail(log_id: int) -> str:
        row = db.get_gate_log(log_id)
        if row is None:
            abort(404)
        return render_template(
            "log_detail.html",
            log=dict(row),
            events=[dict(e) for e in db.list_detection_events(row["session_id"])],
            labels=fusion.DECISION_LABEL,
            alerts=fusion.DECISION_ALERT,
            pending=row["decision"] in fusion.PENDING_DECISIONS,
            stages=_stage_files(row["session_id"]),
        )

    # --- API ------------------------------------------------------------------

    @app.post("/api/evaluate")
    def api_evaluate() -> Any:
        """Foto manual: 1..N berkas diunggah, diproses sebagai satu sesi."""
        files = [f for f in request.files.getlist("images") if f and f.filename]
        if not files:
            return jsonify({"error": "Tidak ada berkas yang diunggah"}), 400

        images: list[tuple[str, Any, str | None]] = []
        for index, storage in enumerate(files, start=1):
            image = service.decode_image(storage.read())
            if image is None:
                return jsonify({"error": f"Berkas '{storage.filename}' bukan citra yang valid"}), 400
            images.append((f"manual{index}", image, None))

        result = service.evaluate(images, source="manual")
        return jsonify(result.as_dict())

    @app.post("/api/simulate")
    def api_simulate() -> Any:
        """Simulasi sepasang frame CCTV 1 + CCTV 2."""
        payload = request.get_json(silent=True) or {}
        plate = (payload.get("plate") or "B 1234 XYZ").strip()
        sticker_code = (payload.get("sticker") or "").strip() or None
        hard = bool(payload.get("hard"))
        vehicle = (payload.get("vehicle") or "car").strip().lower()
        if vehicle not in simulate.VEHICLES:
            return jsonify({"error": f"Kelas kendaraan tidak dikenal: {vehicle}"}), 400
        frames = simulate.cctv_pair(
            plate, sticker_code, seed=int(payload.get("seed") or 0), hard=hard, vehicle=vehicle
        )
        result = service.evaluate(frames, source="cctv")
        return jsonify(result.as_dict())

    @app.post("/api/logs/<int:log_id>/action")
    def api_guard_action(log_id: int) -> Any:
        payload = request.get_json(silent=True) or {}
        ok, message = service.guard_action(
            log_id,
            str(payload.get("action", "")),
            str(payload.get("username") or "satpam1"),
            str(payload.get("note") or ""),
        )
        return jsonify({"ok": ok, "message": message}), (200 if ok else 400)

    @app.get("/api/alerts")
    def api_alerts() -> Any:
        """Polling dashboard: log terbaru + daftar yang menunggu tindakan."""
        return jsonify(
            {
                "pending": service.pending_logs(limit=10),
                "stats": db.stats(),
                "latest_id": (db.list_gate_logs(limit=1) or [{"id": 0}])[0]["id"],
            }
        )

    @app.get("/api/settings")
    def api_get_settings() -> Any:
        return jsonify(db.settings())

    @app.post("/api/settings")
    def api_set_settings() -> Any:
        payload = request.get_json(silent=True) or {}
        updated = {}
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
    def api_health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "plate_backend": detect_yolo.status(),
                "ocr_backend": ocr.active_backend(),
                "sticker_decoders": sticker.available_decoders(),
                "db": str(config.DB_PATH),
            }
        )

    @app.get("/snapshots/<path:relative>")
    def snapshot(relative: str) -> Any:
        path = service.snapshot_path(relative)
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/jpeg" if path.suffix == ".jpg" else "image/png")

    @app.errorhandler(413)
    def too_large(_: Any) -> Any:
        return jsonify({"error": f"Ukuran unggahan melebihi {config.MAX_UPLOAD_MB} MB"}), 413

    return app


def _vehicles() -> list[dict[str, Any]]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT plate_number, sticker_code, owner_name, owner_type, requires_booking "
            "FROM master_vehicles WHERE is_active = 1 ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def _stage_files(session_id: str) -> list[dict[str, str]]:
    """Daftar gambar tahap pipeline untuk halaman detail log."""
    folder = config.SNAPSHOT_DIR / session_id / "stages"
    if not folder.is_dir():
        return []
    order = ["original", "clahe", "denoise", "gray", "plate_raw", "plate_crop", "plate_enhanced", "sticker_crop"]
    files = sorted(folder.glob("*.png"))
    files.sort(key=lambda p: (order.index(p.stem.split("_")[-1]) if p.stem.split("_")[-1] in order else 99, p.name))
    return [{"name": p.stem, "url": f"snapshots/{session_id}/stages/{p.name}"} for p in files]
