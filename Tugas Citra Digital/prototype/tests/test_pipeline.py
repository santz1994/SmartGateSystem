"""Self-check prototipe. Jalankan: python tests/test_pipeline.py

Tanpa framework — cukup assert. Fokus pada logika murni (normalisasi plat, fusi,
keputusan) plus satu uji end-to-end pipeline citra sintetis.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fusion, ocr, pipeline, simulate, sticker  # noqa: E402

PASSED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"GAGAL: {label} {detail}")
    PASSED += 1
    print(f"  ok  {label}")


def test_normalize_plate() -> None:
    print("normalize_plate")
    cases = {
        "B 1234 XYZ": "B1234XYZ",
        "b1234xyz": "B1234XYZ",
        "B-1234-XYZ": "B1234XYZ",
        "8 1234 XYZ": "B1234XYZ",  # 8 di blok huruf depan = B
        "BI234XYZ": "B1234XYZ",  # I di blok angka = 1
        "D 5678 ABC": "D5678ABC",
        "B 9O12 QWE": "B9012OWE",  # O di blok angka = 0; Q bukan huruf NRKB -> O
        "B1G34XYZ": "B1634XYZ",  # G di blok angka = 6
        "B1234X6": "B1234XG",  # 6 di blok huruf belakang = G
        "81257PR": "B1257PR",  # 8 di prefix dan 5 di angka
        "AA5O45YN": "AA5045YN",  # O di blok angka
        "B19990G": "B1999OG",  # 0 di suffix
        "DD 1223 MG": "DD1223MG",
        "AA 5045 YN": "AA5045YN",
        "": "",
    }
    for raw, expected in cases.items():
        got = ocr.normalize_plate(raw)
        check(f"{raw!r} -> {expected}", got == expected, f"(dapat {got!r})")

def test_number_fits_class() -> None:
    print("number_fits_class (golongan NRKB)")
    check("5045 = motor", ocr.number_fits_class("AA5045YN", "motorcycle"))
    check("5045 bukan mobil", not ocr.number_fits_class("AA5045YN", "car"))
    check("1257 = mobil", ocr.number_fits_class("L1257PR", "car"))
    check("8223 = barang/truk", ocr.number_fits_class("B8223XY", "truck"))
    check("9001 = khusus", ocr.number_fits_class("B9001AA", "custom"))
    check("tanpa kelas = False", not ocr.number_fits_class("L1257PR", None))


def test_fuse_scores() -> None:
    print("fuse_scores")
    single = fusion.fuse_scores([0.90], [], sources=1)
    check("plat tunggal", abs(single.fused_score - 0.90) < 1e-6, f"(dapat {single.fused_score})")

    boosted = fusion.fuse_scores([0.90], [], sources=2)
    check("bonus multi-kamera", boosted.fused_score > single.fused_score)

    sticker_helps = fusion.fuse_scores([0.70], [0.95], sources=1)
    check("stiker mengangkat skor", sticker_helps.fused_score >= 0.90, f"(dapat {sticker_helps.fused_score})")

    capped = fusion.fuse_scores([0.99, 0.99, 0.99], [0.99], sources=3)
    check("dibatasi 1.0", capped.fused_score <= 1.0)

    empty = fusion.fuse_scores([], [], sources=1)
    check("tanpa deteksi = 0", empty.fused_score == 0.0)


def test_decide() -> None:
    print("decide")
    thresholds = {"low_confidence_floor": 0.60, "fused_confidence_threshold": 0.90}

    decision, _ = fusion.decide(
        plate_text="B1234XYZ", plate_confidence=0.95, sticker_code=None, sticker_confidence=0.0,
        fused_score=0.95, match={"id": 1}, thresholds=thresholds,
    )
    check("cocok + skor tinggi -> AUTO_OPEN", decision == fusion.AUTO_OPEN)

    decision, _ = fusion.decide(
        plate_text="B9999ZZZ", plate_confidence=0.95, sticker_code=None, sticker_confidence=0.0,
        fused_score=0.95, match=None, thresholds=thresholds,
    )
    check("tidak terdaftar -> NO_MATCH", decision == fusion.NO_MATCH)

    decision, _ = fusion.decide(
        plate_text=None, plate_confidence=0.20, sticker_code=None, sticker_confidence=0.0,
        fused_score=0.20, match=None, thresholds=thresholds,
    )
    check("gagal baca -> OCR_FAILED", decision == fusion.OCR_FAILED)

    decision, _ = fusion.decide(
        plate_text="B1234XYZ", plate_confidence=0.80, sticker_code=None, sticker_confidence=0.0,
        fused_score=0.80, match={"id": 1}, thresholds=thresholds,
    )
    check("cocok tapi skor rendah -> LOW_CONFIDENCE", decision == fusion.LOW_CONFIDENCE)

    decision, _ = fusion.decide(
        plate_text="B1234XYZ", plate_confidence=0.95, sticker_code=None, sticker_confidence=0.0,
        fused_score=0.95, match=None, thresholds=thresholds,
    )
    check("DB mati (match None) tidak pernah AUTO_OPEN", decision != fusion.AUTO_OPEN)


def test_geometry() -> None:
    print("geometri")
    np = pipeline._np()
    pts = np.array([[10, 10], [110, 12], [112, 60], [8, 58]], dtype="float32")
    ordered = pipeline.order_points(pts)
    check("order_points tl paling kiri-atas", tuple(ordered[0]) == (10.0, 10.0), f"(dapat {ordered[0]})")

    image = np.zeros((80, 160, 3), dtype=np.uint8)
    warped = pipeline.four_point_transform(image, pts)
    check("warp menghasilkan citra", warped.shape[0] > 0 and warped.shape[1] > 0, f"(dapat {warped.shape})")

    sharp = np.zeros((64, 64), dtype=np.uint8)
    sharp[::2, :] = 255
    flat = np.full((64, 64), 128, dtype=np.uint8)
    check("Laplacian variance: tajam > rata", pipeline.laplacian_variance(sharp) > pipeline.laplacian_variance(flat))

    # Warna latar plat dan bodi dapat mirip; quality gate harus tetap memakai
    # struktur tepi karakter, bukan mengharuskan plat putih/kontras global.
    colored = np.full((48, 160, 3), (92, 86, 110), dtype=np.uint8)
    for x in range(18, 145, 20):
        colored[14:36, x : x + 7] = (70, 66, 84)
    check("plat berwarna dengan bodi serupa lolos tekstur", pipeline.plate_texture_ok(colored))


def test_end_to_end() -> None:
    print("end-to-end pipeline (citra sintetis)")
    frames = simulate.cctv_pair("B 1234 XYZ", "STK-WRG-0042", seed=7)
    check("dua frame CCTV", len(frames) == 2)

    label, image, role = frames[1]  # CCTV 2 = paling dekat
    stages = pipeline.preprocess(image)
    check("pre-processing menghasilkan 4 tahap", len(stages) == 4)

    plates = pipeline.detect_plates(image)
    check("plat terdeteksi", len(plates) > 0, f"(dapat {len(plates)})")

    if plates:
        picked = pipeline.pick_primary_plate(plates, image.shape)
        text, confidence, backend = ocr.read_plate_robust(picked.crop)
        check(f"OCR membaca plat (backend={backend})", text == "B1234XYZ", f"(dapat {text!r} conf={confidence})")
        check("keyakinan OCR wajar", confidence > 0.5, f"(dapat {confidence})")

    stickers = pipeline.detect_stickers(image)
    check("stiker terdeteksi", len(stickers) > 0, f"(dapat {len(stickers)})")


def test_vote_plate() -> None:
    print("vote_plate")
    text, conf = fusion.vote_plate(
        [("B 1234 XYZ", 0.9), ("B1234XYZ", 0.8), ("B1284XYZ", 0.95), (None, 0.0)]
    )
    check("mayoritas menang", text == "B1234XYZ", f"(dapat {text!r})")
    check("keyakinan = rata-rata pemenang", abs(conf - 0.85) < 1e-6, f"(dapat {conf})")
    text, conf = fusion.vote_plate([(None, 0.0), ("", 0.4)])
    check("tanpa pembacaan -> (None, 0)", text is None and conf == 0.0)
    text, _ = fusion.vote_plate([("AA5O45YN", 0.9), ("AA5045YN", 0.8)])
    check("voting menggunakan normalisasi NRKB", text == "AA5045YN", f"(dapat {text!r})")
    text, conf = fusion.vote_plate(
        [("AA1111AA", 0.95, "approach"), ("DD1884UA", 0.70, "gate")]
    )
    check("kamera gate berbobot lebih tinggi", text == "DD1884UA", f"(dapat {text!r})")
    check("bobot gate tidak menaikkan confidence palsu", abs(conf - 0.70) < 1e-6)

def test_evidence_fusion() -> None:
    print("fusi bukti")
    match = {"plate_number": "B 1234 XYZ", "sticker_code": "STK-1"}
    check("plat + stiker konsisten", fusion.evidence_matches_vehicle(match, "B1234XYZ", "STK-1"))
    check("konflik plat ditolak", not fusion.evidence_matches_vehicle(match, "D5678ABC", "STK-1"))
    check("konflik stiker ditolak", not fusion.evidence_matches_vehicle(match, "B1234XYZ", "STK-2"))
    sticker, confidence = fusion.vote_sticker(
        [("STK-1", 0.8), ("STK-1", 0.9), ("STK-2", 0.99)]
    )
    check("stiker mayoritas menang", sticker == "STK-1" and abs(confidence - 0.85) < 1e-6)

def test_pick_primary_plate() -> None:
    print("pick_primary_plate")

    def det(box: tuple[int, int, int, int], conf: float) -> pipeline.Detection:
        x1, y1, x2, y2 = box
        quad = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        return pipeline.Detection(kind="plate", quad=quad, confidence=conf)

    far = det((400, 100, 480, 120), 0.9)  # kecil, atas frame (mengekor)
    near = det((300, 400, 500, 460), 0.7)  # besar, bawah frame (siap masuk)
    shape = (600, 800, 3)
    picked = pipeline.pick_primary_plate([far, near], shape)
    check("kendaraan paling depan dipilih", picked is near, f"(dapat {picked.bbox if picked else None})")
    check("daftar kosong -> None", pipeline.pick_primary_plate([], shape) is None)

def test_read_plate_robust() -> None:
    print("read_plate_robust (enhance + zoom + retry)")
    frames = simulate.cctv_pair("B 1234 XYZ", None, seed=3)
    _, image, _ = frames[1]
    plates = pipeline.detect_plates(image)
    picked = pipeline.pick_primary_plate(plates, image.shape)
    if picked is not None:
        text, conf, backend = ocr.read_plate_robust(picked.crop)
        check("retry membaca plat valid", text == "B1234XYZ", f"(dapat {text!r} [{backend}])")
        check("retry keyakinan wajar", conf > 0.5, f"(dapat {conf})")

def test_date_sticker_row() -> None:
    print("stiker tanggal di bawah baris plat")
    cv2, np = pipeline._cv2(), pipeline._np()
    plate = simulate.render_plate("B 1234 XYZ", height=110, aspect=3.54)
    # Stiker masa berlaku (mis. "12 26") di bawah plat: kecil tapi kontras
    # tinggi — pembaca lama menyerah pada stiker ini, bukan pada nomor plat.
    h, w = plate.shape[:2]
    canvas = np.full((h + 44, w, 3), 255, np.uint8)
    canvas[:h] = plate
    cv2.putText(canvas, "12 26", (int(w * 0.33), h + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    text, conf, _ = ocr.read_plate_robust(canvas)
    check("baris plat menang atas stiker tanggal", text == "B1234XYZ", f"(dapat {text!r} conf {conf})")

def test_filter_gate_zone() -> None:
    print("filter_gate_zone (ROI gate + ukuran minimum)")

    def det(box: tuple[int, int, int, int], conf: float = 0.8) -> pipeline.Detection:
        x1, y1, x2, y2 = box
        return pipeline.Detection(kind="plate", quad=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]], confidence=conf)

    shape = (600, 800, 3)  # h, w
    near = det((300, 400, 500, 460))    # dekat gerbang, lebar 200
    far = det((400, 100, 470, 125))     # mengekor jauh, lebar 70
    outside = det((5, 50, 60, 70))      # di luar ROI, lebar 55

    kept = pipeline.filter_gate_zone([near, far, outside], shape)
    check("hanya kandidat zona & ukuran yang lolos", kept == [near], f"(dapat {[d.bbox for d in kept]})")

    only = det((100, 100, 200, 130))
    check("kandidat tunggal selalu lolos", pipeline.filter_gate_zone([only], shape) == [only])

def test_yolo_quality_gate() -> None:
    print("YOLO quality gate")
    from app import detect_yolo

    check("confidence YOLO aman", 0.05 <= detect_yolo.DEFAULT_CONF <= 0.50)
    check("kandidat tanpa glyph ditolak", detect_yolo.MIN_PLAUSIBILITY > 0.0)
    check("box terlalu memanjang ditolak", not detect_yolo._box_geometry_ok(0, 0, 482, 68, (831, 768, 3)))
    check("plat motor proporsional diterima", detect_yolo._box_geometry_ok(0, 0, 160, 65, (831, 768, 3)))
    check("plat motor miring diterima", detect_yolo._box_geometry_ok(0, 0, 120, 90, (831, 768, 3)))
    check("box terlalu luas ditolak", not detect_yolo._box_geometry_ok(0, 0, 500, 400, (831, 768, 3)))

def test_detection_roi() -> None:
    print("detection ROI dan exposure")
    np = pipeline._np()
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    roi, offset = pipeline.detection_roi(image)
    check("ROI memotong bagian atas frame", roi.shape[:2] == (65, 180), f"(dapat {roi.shape})")
    check("offset kembali ke frame asli", offset == (10, 35), f"(dapat {offset})")
    corrected = pipeline.detection_preprocess(np.full((8, 8, 3), 255, dtype=np.uint8), gamma=1.2)
    check("preprocess exposure menghasilkan citra", corrected.shape == (8, 8, 3))

def test_plate_text_quality_gate() -> None:
    print("pemilihan hasil OCR kandidat")
    check("plat valid DD2760XCL", ocr._looks_like_plate("DD2760XCL"))
    check("hasil gabungan bukan plat valid", not ocr._looks_like_plate("O02760XCL1029"))
    check("angka pertama tidak boleh nol", not ocr._looks_like_plate("DD02760XCL"))
    check("nol setelah digit pertama diperbolehkan", ocr._looks_like_plate("DD2060XCL"))
    check("nomor urut valid", ocr.number_group("DD2760XCL") == 2760)
    check("nomor urut nol ditolak", ocr.number_group("DD02760XCL") is None)
    check(
        "kandidat kotak OCR: plat menang atas stiker tanggal",
        ocr.best_plate_text(["H", "2518", "OK", "12 26"]) == "H2518OK",
        f"(dapat {ocr.best_plate_text(['H', '2518', 'OK', '12 26'])!r})",
    )
    check(
        "gabungan penuh yang menyertakan stiker ditolak",
        ocr.best_plate_text(["H2518OK", "1226"]) == "H2518OK",
    )
    check(
        "Q di blok huruf = O (H 2518 QK -> H2518OK)",
        ocr.best_plate_text(["H", "2518", "QK", "12 26"]) == "H2518OK",
        f"(dapat {ocr.best_plate_text(['H', '2518', 'QK', '12 26'])!r})",
    )
    winner, _ = fusion.vote_plate([("O02760XCL1029", 0.9), ("B 1234 X6", 0.8)])
    check("voting membuang teks melanggar aturan", winner == "B1234XG", f"(dapat {winner!r})")
    winner, _ = fusion.vote_plate([("O02760XCL1029", 0.9)])
    check("voting hanya berisi pelanggar -> tidak terbaca", winner is None)

def test_signed_sticker_token() -> None:
    print("signed sticker token")
    import os
    previous = os.environ.get("SGS_STICKER_SIGNING_KEY")
    os.environ["SGS_STICKER_SIGNING_KEY"] = "x" * 32
    token = sticker.create_signed_token(1, "STK-TEST-001", ttl_seconds=3600)
    payload = sticker.verify_signed_token(token)
    check("token valid", payload is not None and payload["c"] == "STK-TEST-001")
    check("token yang diubah ditolak", sticker.verify_signed_token(token + "x") is None)
    if previous is None:
        os.environ.pop("SGS_STICKER_SIGNING_KEY", None)
    else:
        os.environ["SGS_STICKER_SIGNING_KEY"] = previous

def test_monitor_moire() -> None:
    print("plat di layar monitor (moiré, banding, pantulan)")
    cv2, np = pipeline._cv2(), pipeline._np()

    def degrade(img, seed, strength):
        h, w = img.shape[:2]
        y = np.arange(h, dtype=np.float32)
        x = np.arange(w, dtype=np.float32)
        out = img.astype(np.float32)
        out += np.sin(2 * np.pi * x / 6.0)[None, :, None] * 8 * strength
        out += np.sin(2 * np.pi * y / 3.0)[:, None, None] * 8 * strength
        out += np.sin(2 * np.pi * y / 55.0)[:, None, None] * 14 * strength
        glare = np.zeros((h, w), np.float32)
        cv2.line(glare, (0, 0), (w, h), 1.0, 50)
        glare = cv2.GaussianBlur(glare, (0, 0), 18)
        out = np.clip(out + glare[:, :, None] * 60 * strength, 0, 255).astype(np.uint8)
        out = cv2.GaussianBlur(out, (3, 3), 0.6)
        return np.clip(
            out.astype(np.int16) + np.random.default_rng(seed).normal(0, 5, out.shape), 0, 255
        ).astype(np.uint8)

    clean = simulate.render_plate("B 1234 XYZ", height=110, aspect=3.54)
    text, conf, _ = ocr.read_plate_robust(degrade(clean, 1, 1.0))
    check("moiré sedang: teks benar & conf >= ambang 0.85", text == "B1234XYZ" and conf >= 0.85,
          f"(dapat {text!r} conf {conf})")

    hard = simulate.render_plate("B 1999 OG", height=110, aspect=3.54)
    text, conf, _ = ocr.read_plate_robust(degrade(hard, 7, 1.8))
    check("moiré berat: teks tetap benar", text == "B1999OG", f"(dapat {text!r} conf {conf})")

def test_distractors() -> None:
    print("distraktor layar/video (subtitle + blok warna)")
    cv2, np = pipeline._cv2(), pipeline._np()
    frame = np.full((480, 854, 3), 30, np.uint8)
    screen = np.zeros((300, 520, 3), np.uint8)  # layar gelap dengan subtitle putih
    cv2.putText(screen, "WELCOME TO MY PODCAST", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    frame[60:360, 30:550] = screen
    cv2.rectangle(frame, (600, 40), (750, 190), (60, 180, 255), -1)  # blok warna jenuh
    plate = cv2.resize(simulate.render_plate("DD 5678 XY", height=110, aspect=3.54), (220, 62))
    frame[190:252, 610:830] = plate

    check("bingkai plat terdeteksi tinggi", pipeline.plate_border_score(plate) > 0.25,
          f"(dapat {pipeline.plate_border_score(plate):.2f})")
    subtitle = screen[60:200, 10:500]
    check("subtitle tanpa bingkai plat", pipeline.plate_border_score(subtitle) < 0.15,
          f"(dapat {pipeline.plate_border_score(subtitle):.2f})")

    dets = pipeline.detect_plates(frame)
    best = max(dets, key=lambda d: pipeline.candidate_score(d, frame.shape)) if dets else None
    check("kandidat teratas = plat, bukan distraktor", best is not None and best.bbox[0] > 550,
          f"(dapat {best.bbox if best else None})")

    stickers = pipeline.detect_stickers(frame)
    check(
        "blok warna video bukan bukti stiker",
        not any(sticker.decode_sticker(s)[0] for s in stickers if s.meta.get("decoder") == "color_patch"),
    )

def test_model_variant() -> None:
    print("pemilihan model YOLO")
    from app import detect_yolo

    detect_yolo.set_variant("yolov8n")
    path_n = detect_yolo.weights_path()
    check("varian yolov8n -> bobot v6-n", path_n is not None and "yolov8n" in str(path_n), f"(dapat {path_n})")
    detect_yolo.set_variant("yolo11n")
    path_x = detect_yolo.weights_path()
    if detect_yolo.available_variants()["yolo11n"]["ready"]:
        check("varian yolo11n -> bobot yolo11n", path_x is not None and "yolo11n" in str(path_x), f"(dapat {path_x})")
    else:
        check("varian yolo11n tanpa bobot -> fallback ke v6-n", path_x == path_n, f"(dapat {path_x})")
    detect_yolo.set_variant("yolov8x")
    if detect_yolo.available_variants()["yolov8x"]["ready"]:
        check("varian yolov8x -> bobot v6-x", "yolov8x" in str(detect_yolo.weights_path()), f"(dapat {detect_yolo.weights_path()})")
    detect_yolo.set_variant("yolov8n")
    check("current_variant kembali yolov8n", detect_yolo.current_variant() == "yolov8n")
    try:
        detect_yolo.set_variant("salah")
        check("varian tak dikenal ditolak", False, "tidak melempar ValueError")
    except ValueError:
        check("varian tak dikenal ditolak", True)
    variants = detect_yolo.available_variants()
    check(
        "daftar varian lengkap + bobot siap + metrik evaluasi",
        set(variants) == {"yolov8n", "yolov8x", "yolo11n"}
        and variants["yolov8n"]["ready"]
        and "metrics" in variants["yolov8n"],
        f"(dapat {variants})",
    )


def main() -> int:
    tests = [
        test_normalize_plate,
        test_number_fits_class,
        test_fuse_scores,
        test_vote_plate,
        test_evidence_fusion,
        test_pick_primary_plate,
        test_filter_gate_zone,
        test_yolo_quality_gate,
        test_model_variant,
        test_detection_roi,
        test_plate_text_quality_gate,
        test_signed_sticker_token,
        test_read_plate_robust,
        test_date_sticker_row,
        test_monitor_moire,
        test_distractors,
        test_decide,
        test_geometry,
        test_end_to_end,
    ]
    for test in tests:
        test()
    print(f"\n{PASSED} pemeriksaan lulus.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\n{exc}")
        raise SystemExit(1)
