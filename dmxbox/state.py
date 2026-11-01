"""Nastavenia ovládané z UI a presety."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

PRESET_KEYS = ("color_fx", "move_fx", "speed", "size", "fade", "palette",
               "master", "auto", "auto_bars", "laser", "uv", "fog_auto", "style", "style_palette")


@dataclass
class Settings:
    color_fx: str = "beat_chase"
    move_fx: str = "jump"
    speed: float = 1.0          # 0.5 / 1 / 2 × BPM
    size: float = 0.7           # amplitúda pohybu / rozsah jasu
    fade: float = 0.4           # 0 = tvrdé, 1 = mäkké prechody
    palette: str = "party"
    master: float = 1.0
    blackout: bool = False
    strobe: bool = False        # drží sa tlačidlom v UI
    auto: bool = True
    auto_bars: int = 16
    style: str = "auto"         # auto = rozpoznať žáner, inak pevne: dnb/techno/house/hiphop/chill/party
    style_palette: bool = True  # v auto móde použiť paletu štýlu (inak `palette`)
    laser: bool = True
    uv: bool = True             # povoliť stály UV podklad na Belke
    manual_color: list | None = None   # [r, g, b, w] 0–1, prepíše FX
    light_delay_ms: int = 0
    line_in: bool = False
    fog: bool = False           # drží sa tlačidlom v UI
    fog_auto: bool = False      # auto výstrek na drop
    fog_burst_s: float = 3.0    # dĺžka auto výstreku
    ambient: bool = False       # svetlá bez hudby: pomalé scény bez analýzy (scenár Ambient)


class Store:
    """Zdieľané nastavenia + presety v JSON súbore."""

    def __init__(self, presets_path: Path, settings: Settings | None = None):
        self.path = presets_path
        self.s = settings or Settings()
        self.lock = threading.Lock()
        self.presets: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.presets = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.presets = {}

    def get(self) -> Settings:
        with self.lock:
            return Settings(**asdict(self.s))

    def update(self, **kw) -> Settings:
        names = {f.name for f in fields(Settings)}
        with self.lock:
            for k, v in kw.items():
                if k in names and v is not None or k == "manual_color":
                    setattr(self.s, k, v)
            return Settings(**asdict(self.s))

    def save_preset(self, slot: int) -> dict:
        with self.lock:
            data = {k: getattr(self.s, k) for k in PRESET_KEYS}
            self.presets[str(slot)] = data
            self.path.write_text(json.dumps(self.presets, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
            return data

    def load_preset(self, slot: int) -> Settings | None:
        data = self.presets.get(str(slot))
        if not data:
            return None
        return self.update(**{k: v for k, v in data.items() if k in PRESET_KEYS})
