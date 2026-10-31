"""Syntetická hudba na testy bez hardvéru: kick, snare, hi-hat, basa podľa žánru."""

from __future__ import annotations

from typing import Iterator

import numpy as np

# 16 krokov = 1 takt (šestnástiny); hodnota = hlasitosť
PATTERNS: dict[str, dict] = {
    # predvolený vzor (pôvodný sim): kick na každej dobe + offbeat hat
    "default": {"bpm": 124, "kick": "x...x...x...x...", "snare": "................",
                "hat": "..x...x...x...x.", "bright": 0.5, "level": 1.0},
    "house":   {"bpm": 124, "kick": "x...x...x...x...", "snare": "....x.......x...",
                "hat": "..x...x...x...x.", "bright": 0.7, "level": 1.0, "snare_vol": 0.35},
    "techno":  {"bpm": 132, "kick": "x...x...x...x...", "snare": "................",
                "hat": "xxxxxxxxxxxxxxxx", "bright": 0.15, "level": 1.0, "hat_vol": 0.35},
    "dnb":     {"bpm": 174, "kick": "x.........x.....", "snare": "....x.......x...",
                "hat": "x.x.x.x.x.x.x.x.", "bright": 0.5, "level": 1.0, "sub": 0.18},
    "hiphop":  {"bpm": 90, "kick": "x......x..x.....", "snare": "....x.......x...",
                "hat": "x.x.x.x.x.x.x.x.", "bright": 0.45, "level": 1.0, "sub": 0.12},
    "chill":   {"bpm": 92, "kick": "x...............", "snare": "........x.......",
                "hat": "x...x...x...x...", "bright": 0.3, "level": 0.35, "kick_vol": 0.35, "snare_vol": 0.3,
                "pad": 0.25},
    "party":   {"bpm": 116, "kick": "x.......x.......", "snare": "....x.......x...",
                "hat": "x.x.x.x.x.x.x.x.", "bright": 0.85, "level": 1.0},
}


GENRES = ("house", "techno", "dnb", "hiphop", "chill", "party")


def mix_source(rate: int = 44100, hop: int = 512, seconds_each: float = 60.0,
               genres: tuple[str, ...] = GENRES) -> Iterator[np.ndarray]:
    """Nekonečný „DJ set“: žánre sa striedajú, v každom je breakdown → build → drop."""
    i = 0
    while True:
        g = genres[i % len(genres)]
        bd = (seconds_each * 0.5, seconds_each * 0.5 + 12)
        yield from synth_source(bpm=None, rate=rate, hop=hop, seconds=seconds_each,
                                seed=i + 1, genre=g, breakdown=bd)
        i += 1


def synth_source(bpm: float | None = 124.0, rate: int = 44100, hop: int = 512,
                 seconds: float | None = None, silence_every: float | None = None,
                 seed: int = 1, genre: str = "default",
                 breakdown: tuple[float, float] | None = None) -> Iterator[np.ndarray]:
    """Generuje bloky `hop` vzoriek.

    genre: kľúč z PATTERNS; bpm=None použije tempo žánru.
    silence_every: každých N s 3 s ticha.
    breakdown: (začiatok, koniec) v s – bez kicku a basy, s rastúcim hi-hat (build).
    """
    pat = PATTERNS[genre]
    bpm = bpm or pat["bpm"]
    rng = np.random.default_rng(seed)
    step = 60.0 / bpm / 4                      # šestnástina
    n = 0
    total = None if seconds is None else int(seconds * rate)

    def env(length_s: float, decay: float) -> np.ndarray:
        t = np.arange(int(length_s * rate)) / rate
        return np.exp(-t * decay), t

    ke, kt = env(0.18, 18)
    kick = np.sin(2 * np.pi * (50 + 90 * np.exp(-kt * 30)) * kt) * ke * pat.get("kick_vol", 0.9)
    se, st = env(0.16, 24)
    sn = np.diff(rng.standard_normal(len(st) + 1))     # šum s horným priepustom (snare nemá sub)
    snare = (sn * 0.45 + np.sin(2 * np.pi * 190 * st)) * se * pat.get("snare_vol", 0.6)
    he, _ = env(0.04, 120)
    hat_noise = rng.standard_normal(len(he))
    hat_noise = np.diff(hat_noise, prepend=0)          # high-pass
    hat = hat_noise * he * pat.get("hat_vol", 0.25)
    bright = pat["bright"]
    grids = {k: [i for i, c in enumerate(pat[k]) if c == "x"] for k in ("kick", "snare", "hat")}
    samples = {"kick": kick, "snare": snare, "hat": hat}

    while total is None or n < total:
        t = (n + np.arange(hop)) / rate
        out = pat.get("sub", 0.08) * np.sin(2 * np.pi * 55 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * t / (step * 16)))
        if pat.get("pad"):
            out += pat["pad"] * (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 277 * t)) * 0.3
        # jas: vyššie harmonické
        out += bright * 0.03 * np.sign(np.sin(2 * np.pi * 880 * t))
        in_bd = breakdown and breakdown[0] <= t[0] < breakdown[1]
        bar_pos = (t / step) % 16
        for name, steps in grids.items():
            if in_bd and name == "kick":
                continue
            smp = samples[name]
            for s_i in steps:
                rel = ((bar_pos - s_i) % 16) * step
                idx = (rel * rate).astype(int)
                m = idx < len(smp)
                if np.any(m):
                    gain = 1.0
                    if in_bd and name == "hat":   # build: hi-hat zosilňuje
                        gain = 0.5 + 2.0 * (t[0] - breakdown[0]) / (breakdown[1] - breakdown[0])
                    out[m] += smp[idx[m]] * gain
        if in_bd:
            out *= 0.6
        out *= pat["level"]
        out += rng.standard_normal(hop) * 0.003
        if silence_every and (t[0] % silence_every) > silence_every - 3:
            out *= 0.0
        n += hop
        yield out.astype(np.float32)
