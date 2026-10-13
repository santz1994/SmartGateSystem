"""Profil kelas kendaraan.

Satu set ambang geometri tidak cukup untuk semua kendaraan: plat motor 1 baris
dan kecil, plat truk/bus sering 2 baris, plat custom/dealer ukurannya bebas.
Modul ini memisahkan ambang tersebut dari pipeline supaya deteksi tidak kaku.

Semua nilai rasio mengacu ukuran TNKB Indonesia:

* mobil 460x130 mm -> rasio 3.54
* motor 250x105 mm -> rasio 2.38
* plat 2 baris 230x130 mm -> rasio 1.77
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class Profile:
    """Ambang geometri untuk satu kelas kendaraan."""

    key: str
    label: str
    ideals: tuple[float, ...]  # rasio w/h yang diharapkan (2 baris = rasio kecil)
    tolerance: float  # toleransi absolut terhadap nilai ideal
    rows: tuple[int, ...]  # jumlah baris teks yang sah
    min_glyphs: tuple[int, int]  # min karakter: index 0 = 1 baris, 1 = 2 baris
    min_area_ratio: float = 0.0015
    min_width_px: int = 40

    @property
    def aspect_min(self) -> float:
        # Kontur selalu dirotasi agar lebar >= tinggi, jadi batas bawah praktis 1.
        return max(min(self.ideals) - self.tolerance, 1.0)

    @property
    def aspect_max(self) -> float:
        return max(self.ideals) + self.tolerance

    def accepts_rows(self, rows: int) -> bool:
        return rows in self.rows

    def glyph_floor(self, rows: int) -> int:
        return self.min_glyphs[0] if rows <= 1 else self.min_glyphs[1]

PROFILES: dict[str, Profile] = {
    "car": Profile("car", "Mobil", (3.54,), 1.20, (1,), (4, 0), 0.0015, 56),
    "motorcycle": Profile("motorcycle", "Motor", (2.38,), 0.75, (1,), (3, 0), 0.0008, 34),
    "truck": Profile("truck", "Truk/Bus", (3.54, 1.77), 1.20, (1, 2), (4, 4), 0.0015, 48),
    "custom": Profile("custom", "Plat Custom/Dealer", (3.00, 2.00, 1.40), 0.70, (1, 2), (3, 3), 0.0006, 30),
}

# Ambang gabungan (union semua profil) untuk tahap *pencarian* kontur. Deteksi
# dibuat permisif; penyaringan ketat dilakukan setelah karakter dihitung —
# lihat ``pipeline.plate_plausibility``.
DETECT_BOUNDS = Profile(
    "detect", "Semua Kelas", (1.40, 2.00, 3.00, 3.54), 4.50, (1, 2), (3, 3), 0.0006, 28
)

def match_aspect(aspect: float) -> tuple[float, str]:
    """Kelas paling cocok + skornya untuk sebuah rasio w/h."""
    best_score, best_key = 0.0, "custom"
    for profile in PROFILES.values():
        for ideal in profile.ideals:
            score = 1.0 - min(abs(aspect - ideal) / ideal, 1.0)
            if score > best_score:
                best_score, best_key = score, profile.key
    return round(best_score, 4), best_key

def classify(aspect: float, rows: int) -> str:
    """Tentukan kelas kendaraan dari rasio plat + jumlah baris teks."""
    best_cost, best_key = float("inf"), "custom"
    for profile in PROFILES.values():
        ideal = min((abs(aspect - i) / i for i in profile.ideals), default=1.0)
        cost = ideal + (0.0 if profile.accepts_rows(rows) else 0.5)
        if cost < best_cost:
            best_cost, best_key = cost, profile.key
    return best_key

def label(key: str | None) -> str:
    profile = PROFILES.get(key or "")
    return profile.label if profile else "Tidak diketahui"
