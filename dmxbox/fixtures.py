"""Kanálové mapy svetiel z fixtures.yaml a zápis do DMX rámca."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import resolve


def clamp8(v: float) -> int:
    return 0 if v <= 0 else 255 if v >= 255 else int(round(v))


@dataclass
class Fixture:
    key: str
    name: str
    start: int
    channels: dict[str, int]
    ranges: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

    def addr(self, ch: str) -> int | None:
        """Absolútna DMX adresa (1–512) logického kanála, alebo None."""
        rel = self.channels.get(ch)
        if rel is None or self.start is None:
            return None
        return self.start + rel - 1

    def set(self, frame: bytearray, ch: str, value: float) -> None:
        a = self.addr(ch)
        if a is not None and 1 <= a <= len(frame):
            frame[a - 1] = clamp8(value)

    def get(self, frame: bytearray, ch: str) -> int:
        a = self.addr(ch)
        return frame[a - 1] if a is not None else 0

    def limit(self, ch: str, value: float) -> int:
        """Premietne 0–255 do povoleného rozsahu kanála (napr. tilt)."""
        lo, hi = self.limits.get(ch, (0, 255))
        return clamp8(lo + (hi - lo) * clamp8(value) / 255)


class Rig:
    """Všetky svetlá + spoločný DMX rámec."""

    def __init__(self, fixtures: dict[str, Fixture], universe_channels: int = 32):
        self.fx = fixtures
        self.universe_channels = universe_channels

    def __getitem__(self, key: str) -> Fixture:
        return self.fx[key]

    def __contains__(self, key: str) -> bool:
        return key in self.fx

    def new_frame(self) -> bytearray:
        return bytearray(512)


def load_rig(path: str | Path = "fixtures.yaml") -> Rig:
    data = yaml.safe_load(resolve(path).read_text(encoding="utf-8"))
    fixtures = {}
    for key, d in (data.get("fixtures") or {}).items():
        fixtures[key] = Fixture(
            key=key,
            name=d.get("name", key),
            start=d.get("start"),
            channels={k: v for k, v in (d.get("channels") or {}).items() if v is not None},
            ranges=d.get("ranges") or {},
            values=d.get("values") or {},
            limits={k: tuple(v) for k, v in (d.get("limits") or {}).items()},
        )
    return Rig(fixtures, int(data.get("universe_channels", 32)))
