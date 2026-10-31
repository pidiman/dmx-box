"""FX kolesá: farby (color) a pohyb (movement)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..audio import AudioState
from ..state import Settings

RGBW = tuple[float, float, float, float]
OFF: RGBW = (0.0, 0.0, 0.0, 0.0)


@dataclass
class Ctx:
    """Všetko, čo efekt potrebuje v jednom frame."""
    a: AudioState
    s: Settings
    beats: float        # spojitý čas v beatoch, už so speed násobkom
    beat: int           # celé číslo beatu
    phase: float        # 0–1 v rámci beatu
    bar: int            # takt (4 beaty)
    onset: bool         # nový kick od minulého frame
    flash: float        # 1 → 0 dozvuk posledného kicku
    palette: list[RGBW]
    t: float            # sekundy (monotonic)

    def color(self, i: int) -> RGBW:
        return self.palette[i % len(self.palette)]

    def pulse(self, sharp: float = 6.0) -> float:
        """Jas, ktorý na beat vyskočí a s fázou dozneje (fade zmäkčuje)."""
        import math
        k = sharp * (1.1 - self.s.fade)
        return math.exp(-self.phase * k)


@dataclass
class Look:
    """Abstraktný stav svetiel (0–1), engine ho prevedie na DMX."""
    # MAX PartyBar4 – celá lišta jedna farba
    bar: RGBW = OFF
    bar_dim: float = 0.0
    # Belka
    par: RGBW = OFF
    derby: RGBW = OFF
    derby_motor: float = 0.0
    laser: str = "off"          # off | red | green | both
    strobe_uv: float = 0.0      # jas modulu
    strobe_speed: float = 0.0   # 0 = svieti stále (UV)
    # moving head
    head_color: RGBW = (0, 0, 0, 1)
    head_dim: float = 0.0
    pan: float = 0.5
    tilt: float = 0.5
    pt_speed: float = 0.0       # 0 = najrýchlejšie
    gobo: int = 0               # 0 = otvorené, 1–7 gobo
    gobo_mode: str = "static"   # static | shake | rotate
    head_strobe: float = 0.0
    ring: float = 0.0


def scale(c: RGBW, k: float) -> RGBW:
    return (c[0] * k, c[1] * k, c[2] * k, c[3] * k)
