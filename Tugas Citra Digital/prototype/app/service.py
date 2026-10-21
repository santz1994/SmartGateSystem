"""Orkestrasi: dari citra mentah sampai keputusan + log audit.

Alur satu sesi:
    citra -> pre-processing -> deteksi plat/stiker -> OCR/dekode
          -> best frame -> fusi skor -> pencocokan DB -> keputusan -> log
"""

from __future__ import annotations

import sqlite3
import hashlib
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import config, db, fusion, ocr, pipeline, sticker, vehicles
from .fusion import DECISION_ALERT, DECISION_LABEL, PENDING_DECISIONS

_DIAGNOSTIC_LAST_SAVED: tuple[float, str] | None = None


@dataclass
class FrameResult:
    label: str
    cctv_role: str | None
    image_path: str | None = None
    plate_text: str | None = None
    plate_confidence: float = 0.0
    plate_raw_text: str = ""
    sticker_code: str | None = None
    sticker_confidence: float = 0.0
    sharpness: float = 0.0
    frame_score: float = 0.0
    is_best_frame: bool = False
    ocr_backend: str = ""
    vehicle_class: str | None = None
    diagnostic_paths: list[str] = field(default_factory=list)
    detections: list[pipeline.Detection] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    session_id: str
    decision: str
    reason: str
    alert: str
    label: str
    plate_text: str | None
    plate_confidence: float
    sticker_code: str | None
    sticker_confidence: float
    fused_score: float
    plate_score: float
    sticker_score: float
    sources: int
    matched_vehicle: dict[str, Any] | None
    matched_booking: dict[str, Any] | None
    snapshot_url: str | None
    log_id: int | None
    frames: list[FrameResult]
    thresholds: dict[str, float]
    ocr_backend: str
    vehicle_class: str | None = None
    db_available: bool = True
    plate_enabled: bool = True
    sticker_enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "decision": self.decision,
            "decision_label": self.label,
            "alert": self.alert,
            "reason": self.reason,
            "plate_text": self.plate_text,
            "plate_confidence": self.plate_confidence,
            "sticker_code": self.sticker_code,
            "sticker_confidence": self.sticker_confidence,
            "fused_score": self.fused_score,
            "plate_score": self.plate_score,
            "sticker_score": self.sticker_score,
            "sources": self.sources,
            "matched_vehicle": self.matched_vehicle,
            "matched_booking": self.matched_booking,
            "snapshot_url": self.snapshot_url,
            "log_id": self.log_id,
            "ocr_backend": self.ocr_backend,
            "vehicle_class": self.vehicle_class,
            "vehicle_class_label": vehicles.label(self.vehicle_class),
            "db_available": self.db_available,
            "plate_enabled": self.plate_enabled,
            "sticker_enabled": self.sticker_enabled,
            "thresholds": self.thresholds,
            "frames": [
                {
                    "label": f.label,
                    "cctv_role": f.cctv_role,
                    "image_path": f.image_path,
                    "plate_text": f.plate_text,
                    "plate_confidence": f.plate_confidence,
                    "sticker_code": f.sticker_code,
                    "sticker_confidence": f.sticker_confidence,
                    "sharpness": round(f.sharpness, 2),
                    "frame_score": round(f.frame_score, 2),
                    "is_best_frame": f.is_best_frame,
                    "vehicle_class": f.vehicle_class,
                    "diagnostic_paths": f.diagnostic_paths,
                    "vehicle_class_label": vehicles.label(f.vehicle_class),
                    "detections": [
                        {
                            "kind": d.kind,
                            "confidence": d.confidence,
                            "payload": d.payload,
                            "bbox": d.bbox,
                            "primary": bool(d.meta.get("primary")),
                        }
                        for d in f.detections
                    ],
                }
                for f in self.frames
            ],
        }


# --- Utilitas citra -----------------------------------------------------------

def decode_image(data: bytes) -> Any:
    """Bytes upload -> np.ndarray BGR. None bila bukan citra valid."""
    cv2, np = pipeline._cv2(), pipeline._np()
    buffer = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def encode_image(image: Any, ext: str = ".jpg") -> bytes:
    cv2 = pipeline._cv2()
    ok, buffer = cv2.imencode(ext, image)
    return buffer.tobytes() if ok else b""


def _save(image: Any, relative: str) -> str:
    path = config.SNAPSHOT_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_image(image))
    return f"snapshots/{relative}"

# Siklus hidup snapshot (M1): batasi jumlah folder sesi, buang yang tertua.
MAX_SNAPSHOT_SESSIONS = 200

# Batas inferensi konkuren (M2): beberapa request YOLO+OCR paralel cukup untuk
# membuat CPU jenuh. Slot global, lintas request.
_INFERENCE_SLOTS = threading.Semaphore(int(os.getenv("SGS_MAX_CONCURRENT_INFER", "2")))

def _prune_snapshots() -> None:
    if not config.SNAPSHOT_DIR.is_dir():
        return
    sessions = [p for p in config.SNAPSHOT_DIR.iterdir() if p.is_dir()]
    if len(sessions) <= MAX_SNAPSHOT_SESSIONS:
        return
    sessions.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in sessions[MAX_SNAPSHOT_SESSIONS:]:
        shutil.rmtree(stale, ignore_errors=True)


# --- Pemrosesan satu frame ----------------------------------------------------

def _process_frame(
    label: str,
    image: Any,
    cctv_role: str | None,
    session_id: str,
    *,
    plate_enabled: bool = True,
    sticker_enabled: bool = True,
    fast: bool = False,
) -> FrameResult:
    stages = pipeline.preprocess(image, full=not fast)
    gray = stages["gray"]
    sharpness = pipeline.laplacian_variance(gray)

    # Multi-kendaraan: buang plat di luar zona gerbang / terlalu kecil, lalu buang
    # blob yang menelan kandidat lain — semua secara geometris, SEBELUM OCR.
    # Sisanya cukup 3 kandidat teratas: OCR itu mahal (~0,5 s per bacaan).
    plates: list[pipeline.Detection] = []
    if plate_enabled:
        plates = pipeline.filter_gate_zone(pipeline.detect_plates(image), image.shape)
        plates = pipeline.drop_swallowed(plates)
        # Kualitas kandidat (bingkai + struktur plat) didahulukan, kedekatan
        # gerbang pemecah seri — blob teks/video besar tidak boleh mengambil
        # slot OCR dari plat asli.
        plates = sorted(plates, key=lambda d: pipeline.candidate_score(d, image.shape), reverse=True)[: (1 if fast else 3)]
    stickers = pipeline.detect_stickers(image) if sticker_enabled and not fast else []
    # Blok warna jenuh di latar (video/layar) bukan stiker: buang yang gagal
    # terdekode agar kotak deteksi tidak "sibuk" menempel pada distraktor.
    stickers = [s for s in stickers if sticker.decode_sticker(s)[0]]

    result = FrameResult(label=label, cctv_role=cctv_role, sharpness=sharpness, stages=stages)

    if plates:
        # Evaluasi semua kandidat terbatas. Kandidat terdekat tidak selalu
        # merupakan plat: pada motor, area jalan/roda di bawah frame dapat
        # terlihat seperti papan terang. Hasil OCR berformat NRKB harus menang
        # sebelum kedekatan dipakai sebagai pemecah seri.
        # Baca dari raw_crop resolusi penuh: pada crop 64 px huruf tipis
        # (prefix "H") hilang dan yang tersisa justru stiker tanggal. Tampilan
        # cadangan (crop bermargin & crop detektor) dibaca sekali bila snap
        # pita teks memotong terlalu rapat.
        readings = []
        for det in plates:
            raw = det.meta.get("raw_crop")
            primary = raw if getattr(raw, "size", 0) else det.crop
            readings.append(
                (det, *ocr.read_plate_robust(primary, det.meta.get("vehicle_class"), fast=fast))
            )
            for view in (det.meta.get("full_crop"), det.crop):
                if getattr(view, "size", 0) and view is not primary:
                    readings.append((det, *ocr.read_plate(view)))
            # Belum ada bacaan yang masuk golongan NRKB kendaraan -> zoom-out
            # lalu baca pita-pita beririsan (crop rapat = kunci akurasi OCR).
            if not any(
                ocr._looks_like_plate(r[1]) and ocr.number_fits_class(r[1], r[0].meta.get("vehicle_class"))
                for r in readings
                if r[0] is det
            ):
                # 1) tumbuhkan crop ke baris tinta plat utuh (kotak sering hanya
                #    menutup sebagian plat), 2) zoom-out + pita beririsan.
                readings.append((det, *ocr.read_plate(pipeline.grow_to_text_line(image, det.bbox))))
                x1, y1, x2, y2 = (int(v) for v in det.bbox)
                pad_x, pad_y = int((x2 - x1) * 0.25), max(int((y2 - y1) * 0.6), 20)
                wide = image[
                    max(y1 - pad_y, 0) : min(y2 + pad_y, image.shape[0]),
                    max(x1 - pad_x, 0) : min(x2 + pad_x, image.shape[1]),
                ]
                for band in ocr.band_crops(wide):
                    readings.append((det, *ocr.read_plate(band)))
        valid_readings = [r for r in readings if ocr._looks_like_plate(r[1])]
        confident_readings = [r for r in valid_readings if r[2] >= 0.5]
        pool = confident_readings or valid_readings or [r for r in readings if r[1] and r[2] >= 0.5] or readings
        best_plate, text, confidence, backend = max(
            pool,
            key=lambda r: (
                1 if ocr._looks_like_plate(r[1]) else 0,
                1 if ocr.number_fits_class(r[1], r[0].meta.get("vehicle_class")) else 0,
                r[2],
                pipeline.closeness(r[0], image.shape),
            ),
        )
        best_plate.meta["primary"] = True
        result.plate_raw_text = text or ""
        # Gerbang keras aturan NRKB (bagian depan huruf, nomor tidak diawali 0,
        # urutan blok huruf-angka-huruf): hasil yang melanggar dianggap tidak
        # terbaca (fail-safe), bukan ditampilkan apa adanya.
        if ocr._looks_like_plate(text):
            result.plate_text = text
            result.plate_confidence = confidence
        result.ocr_backend = backend
        result.stages["plate_crop"] = best_plate.crop
        result.stages["plate_raw"] = best_plate.meta.get("raw_crop")
        result.stages["plate_enhanced"] = pipeline.enhance_plate(best_plate.crop)
        result.vehicle_class = best_plate.meta.get("vehicle_class")

    if stickers:
        best_sticker = max(stickers, key=lambda d: d.confidence)
        best_sticker.meta["primary"] = True
        code, confidence, _ = sticker.decode_sticker(best_sticker)
        result.sticker_code = code
        result.sticker_confidence = confidence
        result.stages["sticker_crop"] = best_sticker.crop

    result.detections = plates + stickers
    detection_conf = max((d.confidence for d in result.detections), default=0.0)
    result.frame_score = pipeline.frame_score(image, detection_conf)
    if plate_enabled and not fast and (
        not result.plate_text
        or result.plate_confidence < config.DEFAULTS["plat_confidence_threshold"]
    ):
        _save_failed_diagnostics(result, session_id)
    return result


def _mark_best_frames(frames: list[FrameResult]) -> None:
    """Satu best frame per sumber (per CCTV / per foto manual)."""
    groups: dict[str, list[FrameResult]] = {}
    for frame in frames:
        groups.setdefault(frame.cctv_role or frame.label, []).append(frame)
    for group in groups.values():
        max(group, key=lambda f: f.frame_score).is_best_frame = True


# --- Evaluasi sesi ------------------------------------------------------------

def evaluate(
    images: Iterable[tuple[str, Any, str | None]],
    source: str = "manual",
    session_id: str | None = None,
    persist: bool = True,
    plate_enabled: bool = True,
    sticker_enabled: bool = True,
    fast: bool = False,
) -> EvaluationResult:
    """Proses semua citra satu sesi dan hasilkan keputusan.

    ``images`` berisi tuple ``(label, np.ndarray BGR, cctv_role)``.
    """
    session_id = session_id or uuid.uuid4().hex[:12]
    thresholds = db.settings()

    with _INFERENCE_SLOTS:
        frames = [
            _process_frame(
                label,
                image,
                role,
                session_id,
                plate_enabled=plate_enabled,
                sticker_enabled=sticker_enabled,
                fast=fast,
            )
            for label, image, role in images
        ]
    if not frames:
        raise ValueError("Tidak ada citra untuk diproses")
    _mark_best_frames(frames)

    plate_confs = [f.plate_confidence for f in frames if f.plate_confidence > 0]
    sticker_confs = [f.sticker_confidence for f in frames if f.sticker_confidence > 0]
    sources = len({f.cctv_role or f.label for f in frames})
    scores = fusion.fuse_scores(
        plate_confs, sticker_confs, sources, thresholds.get("multi_camera_bonus", 0.05)
    )

    # Voting mayoritas antar-frame: menahan 1 frame buram yang salah baca.
    plate_text, plate_confidence = fusion.vote_plate(
        [(f.plate_text, f.plate_confidence, f.cctv_role) for f in frames]
    )
    sticker_code, sticker_confidence = fusion.vote_sticker(
        [(f.sticker_code, f.sticker_confidence) for f in frames]
    )

    # --- Pencocokan database (fail-safe: error DB => tidak auto-open) ---
    match = booking = None
    db_available = True
    try:
        match = db.find_vehicle(plate_text, sticker_code)
        if match is not None and not fusion.evidence_matches_vehicle(match, plate_text, sticker_code):
            match = None
            booking = None
        if match is not None and match["requires_booking"] and plate_text:
            booking = db.active_booking(plate_text)
    except sqlite3.Error:
        db_available = False
        match = booking = None

    decision, reason = fusion.decide(
        plate_text=plate_text,
        plate_confidence=plate_confidence,
        sticker_code=sticker_code,
        sticker_confidence=sticker_confidence,
        fused_score=scores.fused_score,
        match=match,
        thresholds=thresholds,
    )
    if decision == fusion.AUTO_OPEN and match is not None and match["requires_booking"] and booking is None:
        decision, reason = fusion.NO_MATCH, "Kendaraan terdaftar tapi booking tidak aktif"
    if decision == fusion.OCR_FAILED and plate_text is None and any(f.plate_raw_text for f in frames):
        reason = (
            "Hasil OCR tidak sesuai format NRKB (bagian depan huruf, "
            "nomor tidak diawali 0) — dianggap tidak terbaca"
        )
    if not db_available:
        reason = "Database tidak tersedia — dialihkan ke satpam (fail-safe)"

    # --- Simpan snapshot + log ---
    snapshot_url = None
    log_id = None
    if persist:
        for frame in frames:
            annotated = pipeline.annotate(
                frame.stages["original"], frame.detections, f"{frame.label}{' [BEST]' if frame.is_best_frame else ''}"
            )
            frame.image_path = _save(annotated, f"{session_id}/{frame.label}.jpg")
            if frame.is_best_frame and snapshot_url is None:
                snapshot_url = frame.image_path
            _save_stages(frame, session_id)
            db.insert_detection_event(
                session_id=session_id,
                source=source,
                cctv_role=frame.cctv_role,
                image_path=frame.image_path,
                plate_text=frame.plate_text,
                plate_confidence=frame.plate_confidence,
                sticker_code=frame.sticker_code,
                sticker_confidence=frame.sticker_confidence,
                fused_score=scores.fused_score,
                sharpness=frame.sharpness,
                is_best_frame=int(frame.is_best_frame),
                ocr_backend=frame.ocr_backend,
                vehicle_class=frame.vehicle_class,
            )
        log_id = db.insert_gate_log(
            session_id=session_id,
            decision=decision,
            plate_text=plate_text,
            sticker_code=sticker_code,
            fused_score=scores.fused_score,
            matched_vehicle_id=match["id"] if match is not None else None,
            matched_booking_id=booking["id"] if booking is not None else None,
            snapshot_url=snapshot_url,
            reason=reason,
        )
        _prune_snapshots()

    return EvaluationResult(
        session_id=session_id,
        decision=decision,
        reason=reason,
        alert=DECISION_ALERT[decision],
        label=DECISION_LABEL[decision],
        plate_text=plate_text,
        plate_confidence=plate_confidence,
        sticker_code=sticker_code,
        sticker_confidence=sticker_confidence,
        fused_score=scores.fused_score,
        plate_score=scores.plate_score,
        sticker_score=scores.sticker_score,
        sources=sources,
        matched_vehicle=dict(match) if match is not None else None,
        matched_booking=dict(booking) if booking is not None else None,
        snapshot_url=snapshot_url,
        log_id=log_id,
        frames=frames,
        thresholds=thresholds,
        ocr_backend=next((f.ocr_backend for f in frames if f.ocr_backend), ocr.active_backend()),
        vehicle_class=next((f.vehicle_class for f in frames if f.vehicle_class), None),
        db_available=db_available,
        plate_enabled=plate_enabled,
        sticker_enabled=sticker_enabled,
    )


def _save_stages(frame: FrameResult, session_id: str) -> None:
    """Simpan tiap tahap pipeline sebagai PNG — bahan visualisasi laporan."""
    for name in ("original", "clahe", "denoise", "gray", "plate_raw", "plate_crop", "plate_enhanced", "sticker_crop"):
        image = frame.stages.get(name)
        if image is None or getattr(image, "size", 0) == 0:
            continue
        _save(image, f"{session_id}/stages/{frame.label}_{name}.png")


def _save_failed_diagnostics(frame: FrameResult, session_id: str) -> None:
    """Simpan bukti gagal dengan deduplikasi, cooldown, dan ring buffer."""
    global _DIAGNOSTIC_LAST_SAVED
    images = {
        "frame": frame.stages.get("original"),
        "plate_raw": frame.stages.get("plate_raw"),
        "plate_crop": frame.stages.get("plate_crop"),
        "plate_enhanced": frame.stages.get("plate_enhanced"),
    }
    source = images["frame"]
    if source is None or getattr(source, "size", 0) == 0:
        return
    fingerprint = hashlib.sha1(source.tobytes()).hexdigest()
    now = time.monotonic()
    if _DIAGNOSTIC_LAST_SAVED is not None:
        saved_at, saved_fingerprint = _DIAGNOSTIC_LAST_SAVED
        if fingerprint == saved_fingerprint or now - saved_at < config.DIAGNOSTIC_COOLDOWN_SECONDS:
            return

    for name, image in images.items():
        if image is None or getattr(image, "size", 0) == 0:
            continue
        relative = f"{session_id}_{frame.label}_{name}.jpg"
        path = config.DIAGNOSTIC_DIR / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode_image(image))
        frame.diagnostic_paths.append(f"diag/ocr_failed/{relative}")
    _DIAGNOSTIC_LAST_SAVED = (now, fingerprint)

    bundles: dict[str, list[Path]] = {}
    for path in config.DIAGNOSTIC_DIR.glob("*"):
        if path.is_file():
            bundles.setdefault(path.name.split("_", 1)[0], []).append(path)
    ordered = sorted(
        bundles.items(),
        key=lambda item: max(path.stat().st_mtime for path in item[1]),
        reverse=True,
    )
    for _, paths in ordered[config.MAX_DIAGNOSTIC_BUNDLES:]:
        for path in paths:
            path.unlink(missing_ok=True)


# --- Tindakan satpam ----------------------------------------------------------

def guard_action(log_id: int, action: str, username: str, note: str) -> tuple[bool, str]:
    """Bypass (MANUAL_OVERRIDE) atau tolak (REJECTED) oleh satpam."""
    if action not in ("bypass", "reject"):
        return False, "Aksi tidak dikenal"
    if not note.strip():
        return False, "Catatan wajib diisi untuk audit"
    decision = fusion.MANUAL_OVERRIDE if action == "bypass" else fusion.REJECTED
    ok = db.resolve_override(log_id, decision, username, note.strip())
    if not ok:
        return False, "Log tidak ditemukan atau sudah final"
    return True, DECISION_LABEL[decision]


def pending_logs(limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in PENDING_DECISIONS:
        rows.extend(dict(row) for row in db.list_gate_logs(limit=limit, decision=decision))
    rows.sort(key=lambda row: row["id"], reverse=True)
    return rows[:limit]


def snapshot_path(relative: str) -> Path | None:
    """Resolve path snapshot dengan proteksi path traversal."""
    candidate = (config.SNAPSHOT_DIR / relative).resolve()
    root = config.SNAPSHOT_DIR.resolve()
    if root not in candidate.parents and candidate != root:
        return None
    return candidate if candidate.is_file() else None


def diagnostic_path(relative: str) -> Path | None:
    """Resolve diagnostic image dengan proteksi path traversal."""
    candidate = (config.DIAGNOSTIC_DIR / relative).resolve()
    root = config.DIAGNOSTIC_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None
