"""Načítanie config.yaml s predvolenými hodnotami."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "audio": {
        "source": "auto",
        "rate": 44100,
        "hop": 512,
        "fft": 1024,
        "bpm_min": 80,
        "bpm_max": 180,
        "silence_seconds": 4,
    },
    "dmx": {"driver": "udmx", "fps": 40, "channels": 32, "chunk": 8},
    "output": {"mode": "cable", "light_delay_ms": 0},
    "web": {"host": "0.0.0.0", "port": 80},
    "presets_file": "presets.json",
    "fixtures_file": "fixtures.yaml",
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def load_config(path: str | Path = "config.yaml") -> dict:
    p = resolve(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _merge(DEFAULTS, data or {})
