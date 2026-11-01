"""FX koleso 2: pohyb moving headu (Fractal Mini LED Gobo Spot).

Motor nestíha plynulé kruhy v tempe → hlavný režim je skok medzi
pozíciami na beat. Plynulé pohyby len pomalé (cez viac taktov).
"""

from __future__ import annotations

import math
import random

from . import Ctx, Look

# (pan, tilt) 0–1, rozmiestnené po miestnosti; tilt limituje rig.yaml (limits)
POSITIONS = [
    (0.20, 0.55), (0.35, 0.40), (0.50, 0.60), (0.65, 0.40), (0.80, 0.55),
    (0.70, 0.70), (0.55, 0.35), (0.40, 0.70), (0.25, 0.35), (0.50, 0.45),
]


def _around(c: Ctx, pan: float, tilt: float) -> tuple[float, float]:
    """Zmenší rozptyl okolo stredu podľa `size`."""
    k = 0.3 + 0.7 * c.s.size
    return 0.5 + (pan - 0.5) * k, 0.5 + (tilt - 0.5) * k


def jump(c: Ctx, L: Look) -> None:
    """Skok na ďalšiu pozíciu na každý beat."""
    L.pan, L.tilt = _around(c, *POSITIONS[c.beat % len(POSITIONS)])
    L.pt_speed = 0.0
    L.head_dim = 0.4 + 0.6 * c.pulse()
    L.gobo = (c.bar % 7) + 1


def circle_slow(c: Ctx, L: Look) -> None:
    """Pomalý kruh cez 8 beatov (len pre pomalé tempo)."""
    ang = 2 * math.pi * c.beats / 8
    L.pan, L.tilt = _around(c, 0.5 + 0.35 * math.cos(ang), 0.5 + 0.3 * math.sin(ang))
    L.pt_speed = 0.3
    L.head_dim = 0.9
    L.gobo = 0


def sweep(c: Ctx, L: Look) -> None:
    """Pan zo strany na stranu na beat."""
    L.pan, L.tilt = _around(c, 0.2 if c.beat % 2 == 0 else 0.8, 0.5)
    L.pt_speed = 0.0
    L.head_dim = 0.5 + 0.5 * c.pulse()
    L.gobo = 3


def tilt_bounce(c: Ctx, L: Look) -> None:
    """Tilt hore-dole na beat, pan sa posúva po taktoch."""
    pan = POSITIONS[c.bar % len(POSITIONS)][0]
    L.pan, L.tilt = _around(c, pan, 0.25 if c.beat % 2 == 0 else 0.75)
    L.pt_speed = 0.0
    L.head_dim = 0.5 + 0.5 * c.pulse()
    L.gobo = 5


def snap(c: Ctx, L: Look) -> None:
    """Náhodná pozícia každý druhý beat (deterministická podľa čísla beatu)."""
    rng = random.Random(c.beat // 2)
    L.pan, L.tilt = _around(c, rng.uniform(0.15, 0.85), rng.uniform(0.25, 0.75))
    L.pt_speed = 0.0
    L.head_dim = 1.0 if c.flash > 0.3 else 0.5
    L.gobo = rng.randint(1, 7)


def audience(c: Ctx, L: Look) -> None:
    """Pomalý pohyb nad hlavami, rotujúce gobo."""
    ang = 2 * math.pi * c.beats / 16
    L.pan, L.tilt = _around(c, 0.5 + 0.3 * math.sin(ang), 0.3 + 0.08 * math.sin(2 * ang))
    L.pt_speed = 0.5
    L.head_dim = 0.8
    L.gobo, L.gobo_mode = 4, "rotate"


def gobo_beat(c: Ctx, L: Look) -> None:
    """Hlava stojí, gobo sa mení na beat."""
    L.pan, L.tilt = 0.5, 0.45
    L.pt_speed = 0.2
    L.head_dim = 0.4 + 0.6 * c.pulse()
    L.gobo = (c.beat % 7) + 1
    L.gobo_mode = "shake" if c.flash > 0.6 else "static"


def hold(c: Ctx, L: Look) -> None:
    """Hlava stojí v strede, svieti."""
    L.pan, L.tilt = 0.5, 0.5
    L.pt_speed = 0.5
    L.head_dim = 0.9
    L.gobo = 0


MOVE_FX = {
    "jump": jump,
    "circle_slow": circle_slow,
    "sweep": sweep,
    "tilt_bounce": tilt_bounce,
    "snap": snap,
    "audience": audience,
    "gobo_beat": gobo_beat,
    "hold": hold,
}
