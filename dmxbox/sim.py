"""Syntetická hudba na testy bez hardvéru (kick, hi-hat, basa, pauzy)."""

from __future__ import annotations

from typing import Iterator

import numpy as np


def synth_source(bpm: float = 124.0, rate: int = 44100, hop: int = 512,
                 seconds: float | None = None, silence_every: float | None = None,
                 seed: int = 1) -> Iterator[np.ndarray]:
    """Generuje bloky `hop` vzoriek. `silence_every` = každých N s 3 s ticho."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    n = 0
    total = None if seconds is None else int(seconds * rate)
    kick_len = int(0.18 * rate)
    kt = np.arange(kick_len) / rate
    kick = np.sin(2 * np.pi * (50 + 90 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 18)
    hat_len = int(0.04 * rate)
    hat = rng.standard_normal(hat_len) * np.exp(-np.arange(hat_len) / rate * 120) * 0.25
    while total is None or n < total:
        t = (n + np.arange(hop)) / rate
        out = 0.08 * np.sin(2 * np.pi * 55 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * t / (beat * 4)))
        k = ((t % beat) * rate).astype(int)
        m = k < kick_len
        out[m] += 0.9 * kick[k[m]]
        h = (((t + beat / 2) % beat) * rate).astype(int)
        m = h < hat_len
        out[m] += hat[h[m]]
        out += rng.standard_normal(hop) * 0.003
        if silence_every and (t[0] % silence_every) > silence_every - 3:
            out *= 0.0
        n += hop
        yield out.astype(np.float32)
