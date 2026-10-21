"""Aplikasi web Flask: dashboard satpam, upload foto manual, simulasi CCTV, log.

Sengaja tanpa WebSocket: dashboard melakukan polling ringan ke ``/api/alerts``
tiap 3 detik. Untuk prototipe ini cukup, dan menghilangkan satu dependensi.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

from . import config, db, detect_yolo, fusion, ocr, pipeline, service, simulate, sticker, vehicles

ROLE_CHOICES = ("satpam1", "admin")
VEHICLE_TYPES = ("car", "motorcycle", "truck", "custom")
OWNER_TYPES = ("warga", "karyawan", "tamu")

# Run training YOLO — dipantau halaman /training. Pilih run terbaru otomatis
# (Colab V5 pakai runs/detect/smartgate-colab-v5, training lama runs/detect/runs/detect/smartgate).
def _latest_train_run() -> Path:
    candidates = [
        d.parent for d in config.BASE_DIR.glob("runs/detect/*/results.csv")
    ] + [
        d.parent for d in config.BASE_DIR.glob("runs/detect/runs/detect/*/results.csv")
    ]
    candidates = [d for d in candidates if d.is_dir()]
    if not candidates:
        return config.BASE_DIR / "runs" / "detect" / "smartgate-colab-v5"
    return max(candidates, key=lambda d: (d / "results.csv").stat().st_mtime)


TRAIN_RUN_DIR = _latest_train_run()
TRAIN_PLOTS = (
    "results.png",
    "labels.jpg",
    "train_batch0.jpg",
    "confusion_matrix_normalized.png",
    "confusion_matrix.png",
)


def create_app() -> Flask:
    config.ensure_dirs()
    db.init_db()

    try:
        detect_yolo.set_variant(db.raw_setting("yolo_variant", "yolov8n"))
    except ValueError:
        pass  # nilai tersimpan tidak valid -> pakai default

    import threading

    threading.Thread(target=ocr.warmup, daemon=True).start()  # model siap sebelum scan pertama

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

    @app.get("/camera")
    def camera_page() -> str:
        return render_template("camera.html", backend=ocr.active_backend())

    @app.get("/training")
    def training_page() -> str:
        return render_template("training.html", status=training_status(), backend=ocr.active_backend())

    @app.get("/training/plot/<name>")
    def training_plot(name: str) -> Any:
        if name not in TRAIN_PLOTS:
            abort(404)
        path = TRAIN_RUN_DIR / name
        if not path.is_file():
            abort(404)
        return send_file(path)

    # --- Manajemen kendaraan ---------------------------------------------------

    @app.get("/vehicles")
    def vehicles_page() -> str:
        edit_id = request.args.get("edit", type=int)
        row = db.get_vehicle(edit_id) if edit_id else None
        return _vehicles_page(edit=dict(row) if row else None)

    @app.post("/vehicles/save")
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

        def enabled(name: str, default: str = "1") -> bool:
            return request.args.get(name, default).strip().lower() not in {"0", "false", "off"}

        # Fast hanya untuk auto scan; unggahan manual & scan simpan-log selalu penuh.
        fast = enabled("fast", "0")
        result = service.evaluate(
            images,
            source="manual",
            persist=request.args.get("persist", "1") != "0",
            plate_enabled=enabled("plate"),
            sticker_enabled=enabled("sticker"),
            fast=fast,
        )
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
        return jsonify(
            {
                **db.settings(),
                "yolo_variant": detect_yolo.current_variant(),
                "yolo_variants": detect_yolo.available_variants(),
            }
        )

    @app.post("/api/settings")
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
    def snapshot(relative: str) -> Any:
        path = service.snapshot_path(relative)
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/jpeg" if path.suffix == ".jpg" else "image/png")

    @app.get("/diagnostics/<path:relative>")
    def diagnostic(relative: str) -> Any:
        path = service.diagnostic_path(relative)
        if path is None:
            abort(404)
        return send_file(path, mimetype="image/jpeg")

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

def training_status() -> dict[str, Any]:
    """Status training YOLO dari results.csv run — untuk halaman /training."""
    import csv

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
    if not fields["plate_number"]:
        return "Plat nomor wajib diisi."
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
