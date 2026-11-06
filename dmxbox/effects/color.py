"""FX koleso 1: farby (PartyBar4, Belka PAR, derby, laser, strobo/UV)."""

from __future__ import annotations

import colorsys
import math

from . import OFF, RGBW, Ctx, Look, scale

PALETTES: dict[str, list[RGBW]] = {
    "party": [(1, 0, 0, 0), (1, 0, 1, 0), (0, 0, 1, 0), (0, 1, 1, 0),
              (0, 1, 0, 0), (1, 0.6, 0, 0)],
    "cool": [(0, 0, 1, 0), (0, 1, 1, 0), (0.5, 0, 1, 0), (0, 0.3, 1, 0.3)],
    "warm": [(1, 0, 0, 0), (1, 0.4, 0, 0), (1, 0.15, 0.3, 0), (1, 0.7, 0, 0.2)],
    "ice": [(0, 0, 0, 1), (0, 0.6, 1, 0.3), (0, 0, 1, 0), (0, 1, 1, 0.5)],
    "fire": [(1, 0, 0, 0), (1, 0.3, 0, 0), (1, 0.6, 0, 0), (1, 0, 0, 0.3)],
    "urban": [(0.6, 0, 1, 0), (1, 0.55, 0, 0), (1, 0, 0.6, 0), (0.1, 0, 1, 0)],   # fialová, zlatá
}
WHITE: RGBW = (0, 0, 0, 1)


def _laser_on_beat(c: Ctx, every: int = 2) -> str:
    if not c.s.laser:
        return "off"
    return ("red", "green", "both")[(c.beat // every) % 3] if c.beat % every == 0 else "off"


def beat_chase(c: Ctx, L: Look) -> None:
    """Každý beat iná farba, lišta → PAR → derby sa posúvajú v palete."""
    p = c.pulse()
    L.bar, L.bar_dim = c.color(c.beat), 0.25 + 0.75 * p
    L.par = scale(c.color(c.beat + 1), 0.3 + 0.7 * p)
    L.derby = c.color(c.beat + 2)
    L.derby_motor = 0.6
    L.head_color = c.color(c.beat + 3)
    L.laser = _laser_on_beat(c, 4)


def bass_pump(c: Ctx, L: Look) -> None:
    """Jas všetkého podľa basy, farba sa mení každý takt."""
    k = 0.1 + 0.9 * c.a.bass
    L.bar, L.bar_dim = c.color(c.bar), k
    L.par = scale(c.color(c.bar + 1), k)
    L.derby = scale(c.color(c.bar + 2), k)
    L.derby_motor = 0.4
    L.head_color = c.color(c.bar)


def color_step(c: Ctx, L: Look) -> None:
    """Stála farba, mení sa každý takt; derby pomaly."""
    L.bar, L.bar_dim = c.color(c.bar), 1.0
    L.par = c.color(c.bar)
    L.derby = c.color(c.bar + 1)
    L.derby_motor = 0.25
    L.head_color = c.color(c.bar + 2)


def rainbow(c: Ctx, L: Look) -> None:
    """Plynulá dúha, rýchlosť z tempa (jedna otočka za 16 beatov)."""
    def hue(off: float) -> RGBW:
        r, g, b = colorsys.hsv_to_rgb((c.beats / 16 + off) % 1.0, 1, 1)
        return (r, g, b, 0)
    L.bar, L.bar_dim = hue(0), 0.9
    L.par = hue(0.33)
    L.derby = hue(0.66)
    L.derby_motor = 0.2
    L.head_color = hue(0.5)
    L.strobe_uv = 0.4 if c.s.uv else 0.0


def split(c: Ctx, L: Look) -> None:
    """Lišta a Belka PAR sa striedajú na beat."""
    p = c.pulse(4)
    even = c.beat % 2 == 0
    col = c.color(c.bar)
    L.bar, L.bar_dim = col, (0.2 + 0.8 * p) if even else 0.05
    L.par = scale(c.color(c.bar + 1), 0.05 if even else 0.2 + 0.8 * p)
    L.derby = c.color(c.bar + 2) if not even else OFF
    L.derby_motor = 0.5
    L.head_color = col
    L.laser = _laser_on_beat(c, 2)


def kick_flash(c: Ctx, L: Look) -> None:
    """Biely záblesk na kick, inak tlmená farba (DnB, techno)."""
    f = c.flash
    base = c.color(c.bar)
    L.bar = tuple(base[i] * (1 - f) + WHITE[i] * f for i in range(4))
    L.bar_dim = 0.15 + 0.85 * f
    # Belka PAR: udrie aj na mriežku beatov, nie len na detekovaný kick (ten pri hustej hudbe chýba)
    k = max(f, c.pulse(6.0))
    L.par = tuple(base[i] * 0.25 * (1 - k) + WHITE[i] * k for i in range(4)) if k > 0.2 else scale(base, 0.25)
    L.derby = scale(c.color(c.bar + 1), 0.3 + 0.7 * k)
    L.derby_motor = 0.8
    L.head_color = WHITE if f > 0.5 else base
    L.laser = ("green" if c.s.laser and f > 0.6 else "off")


def build_up(c: Ctx, L: Look) -> None:
    """Rastúce výšky = rýchlejšie blikanie, plná energia = strobo."""
    energy = 0.5 * c.a.high + 0.5 * c.a.level
    color_step(c, L)
    if energy > 0.85 and c.a.bass > 0.7:
        L.strobe_uv, L.strobe_speed = 1.0, 0.9
        L.bar_dim = 1.0
    else:
        blink = 0.5 + 0.5 * math.cos(2 * math.pi * c.beats * (1 + 3 * energy))
        L.bar_dim = 0.3 + 0.7 * blink * energy
        L.strobe_uv = 0.3 if c.s.uv else 0.0


def derby_party(c: Ctx, L: Look) -> None:
    """Derby a laser naplno na refrénoch (vysoký level), inak UV podklad."""
    loud = c.a.level > 0.6
    L.bar, L.bar_dim = c.color(c.bar), 0.4 + 0.6 * c.pulse()
    L.par = scale(c.color(c.bar + 1), 0.5)
    L.derby = c.color(c.beat) if loud else scale(c.color(c.bar), 0.4)
    L.derby_motor = 1.0 if loud else 0.3
    L.laser = _laser_on_beat(c, 1) if loud else "off"
    L.strobe_uv = 0.0 if loud else (0.6 if c.s.uv else 0.0)
    L.head_color = c.color(c.beat + 1)


COLOR_FX = {
    "beat_chase": beat_chase,
    "bass_pump": bass_pump,
    "color_step": color_step,
    "rainbow": rainbow,
    "split": split,
    "kick_flash": kick_flash,
    "build_up": build_up,
    "derby_party": derby_party,
}
