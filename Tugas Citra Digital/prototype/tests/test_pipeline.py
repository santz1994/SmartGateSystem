"""Self-check prototipe. Jalankan: python tests/test_pipeline.py

Tanpa framework — cukup assert. Fokus pada logika murni (normalisasi plat, fusi,
keputusan) plus satu uji end-to-end pipeline citra sintetis.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fusion, ocr, pipeline, simulate  # noqa: E402

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
        "8 1234 XYZ": "B1234XYZ",  # B terbaca 8
        "BI234XYZ": "B1234XYZ",  # 1 terbaca I
        "D 5678 ABC": "D5678ABC",
        "B 9O12 QWE": "B9012QWE",  # O terbaca di blok angka
        "": "",
    }
    for raw, expected in cases.items():
        got = ocr.normalize_plate(raw)
        check(f"{raw!r} -> {expected}", got == expected, f"(dapat {got!r})")


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
        text, confidence, backend = ocr.read_plate(max(plates, key=lambda d: d.confidence).crop)
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

def main() -> int:
    tests = [
        test_normalize_plate,
        test_fuse_scores,
        test_vote_plate,
        test_pick_primary_plate,
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
