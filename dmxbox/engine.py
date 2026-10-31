"""Engine: 40 Hz slučka, skladá vrstvy a zapisuje DMX rámec.

Poradie vrstiev (vyššia prepíše nižšiu):
blackout > strobe hold > manuálna farba > FX koleso 1 (farby) + 2 (pohyb) > master
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass

from .audio import Analyzer, AudioState
from .dmx_out import DMXOut
from .effects import Ctx, Look, scale
from .effects.color import COLOR_FX, PALETTES
from .effects.movement import MOVE_FX
from .fixtures import Rig, clamp8
from .fog import FogController
from .state import Store

log = logging.getLogger("dmxbox.engine")

# Auto mód: dvojice (farby, pohyb) podľa tempa
AUTO_SETS = {
    "slow": [("rainbow", "circle_slow"), ("color_step", "audience"), ("bass_pump", "gobo_beat")],
    "mid": [("beat_chase", "jump"), ("split", "sweep"), ("bass_pump", "tilt_bounce"),
            ("derby_party", "snap"), ("color_step", "gobo_beat"), ("kick_flash", "jump")],
    "fast": [("kick_flash", "snap"), ("split", "jump"), ("build_up", "sweep"),
             ("derby_party", "jump")],
}

# farby kolieska moving headu (fixtures.yaml → values.color) ako RGB
HEAD_WHEEL = {
    "white": (1, 1, 1), "red": (1, 0, 0), "yellow": (1, 1, 0), "blue": (0, 0, 1),
    "green": (0, 1, 0), "orange": (1, 0.5, 0), "pink": (1, 0, 1), "cyan": (0, 1, 1),
}


def tempo_class(bpm: float) -> str:
    return "slow" if bpm < 100 else "fast" if bpm >= 150 else "mid"


@dataclass
class Status:
    color_fx: str = ""
    move_fx: str = ""
    auto_index: int = 0
    idle: bool = True
    frame: int = 0


class Engine(threading.Thread):
    def __init__(self, rig: Rig, analyzer: Analyzer, store: Store, out: DMXOut, fps: int = 40):
        super().__init__(daemon=True, name="engine")
        self.rig, self.an, self.store, self.out = rig, analyzer, store, out
        self.period = 1.0 / fps
        self.status = Status()
        self._halt = threading.Event()
        self._last_onset = 0
        self._flash = 0.0
        self._auto_bar = -1
        self._auto_i = 0
        self.last_frame = bytearray(512)
        self.fog = FogController()

    def stop(self) -> None:
        self._halt.set()

    # --- výpočet jedného frame ------------------------------------------------
    def compute(self, a: AudioState, now: float) -> bytearray:
        s = self.store.get()
        onset = a.onset_count != self._last_onset
        self._last_onset = a.onset_count
        self._flash = 1.0 if onset else self._flash * 0.82

        beats = a.beats * s.speed
        beat = int(math.floor(beats))
        ctx = Ctx(a=a, s=s, beats=beats, beat=beat, phase=beats - beat, bar=beat // 4,
                  onset=onset, flash=self._flash,
                  palette=PALETTES.get(s.palette, PALETTES["party"]), t=now)

        color_name, move_name = self._pick_fx(s, a, ctx.bar)
        L = Look()
        if a.silent and not s.strobe:
            self._idle(ctx, L)
            self.status.idle = True
        else:
            COLOR_FX[color_name](ctx, L)
            MOVE_FX[move_name](ctx, L)
            self.status.idle = False
        self.status.color_fx, self.status.move_fx = color_name, move_name

        if s.manual_color:
            mc = tuple(float(x) for x in s.manual_color[:4])
            L.bar, L.par, L.derby, L.head_color = mc, mc, mc, mc
            L.bar_dim = max(L.bar_dim, 0.8)
        if not s.laser:
            L.laser = "off"
        if not s.uv and L.strobe_speed == 0:
            L.strobe_uv = 0.0

        fog_on = self.fog.update(now, a, s.fog, s.fog_auto, s.fog_burst_s, s.blackout)

        frame = self.rig.new_frame()
        self._write(frame, L, s.master, strobe=s.strobe)
        self._write_fog(frame, L, fog_on, s.master)
        if s.blackout:
            frame = self.rig.new_frame()
            self._write_safe_defaults(frame)
        self.status.frame += 1
        return frame

    def _pick_fx(self, s, a: AudioState, bar: int) -> tuple[str, str]:
        if not s.auto:
            return s.color_fx, s.move_fx
        sets = AUTO_SETS[tempo_class(a.bpm)]
        if self._auto_bar < 0 or (bar - self._auto_bar) >= max(1, s.auto_bars) or bar < self._auto_bar:
            if self._auto_bar >= 0:
                self._auto_i += 1
            self._auto_bar = bar
        self.status.auto_index = self._auto_i
        return sets[self._auto_i % len(sets)]

    def _idle(self, c: Ctx, L: Look) -> None:
        """Ticho: pomalé dýchanie lišty, ostatné zhasnuté."""
        breath = 0.5 + 0.5 * math.sin(2 * math.pi * c.t / 6.0)
        L.bar = c.palette[int(c.t / 12) % len(c.palette)]
        L.bar_dim = 0.08 + 0.12 * breath
        L.head_dim = 0.0
        L.pan, L.tilt = 0.5, 0.5
        L.pt_speed = 1.0

    # --- Look → DMX -----------------------------------------------------------
    def _write_safe_defaults(self, f: bytearray) -> None:
        """Kanály, ktoré musia mať konkrétnu hodnotu aj pri blackoute."""
        if "movinghead" in self.rig:
            h = self.rig["movinghead"]
            h.set(f, "pan", 128)
            h.set(f, "tilt", h.limit("tilt", 128))

    def _write(self, f: bytearray, L: Look, master: float, strobe: bool) -> None:
        m = max(0.0, min(1.0, master))

        if "parbar" in self.rig:
            p = self.rig["parbar"]
            p.set(f, "macro", 0)            # 0–10 = priame DMX RGBW
            p.set(f, "color_macro", 0)
            p.set(f, "speed", 0)
            p.set(f, "dimmer", 255 * L.bar_dim * m)
            for ch, v in zip(("red", "green", "blue", "white"), L.bar):
                p.set(f, ch, 255 * v)
            if strobe:
                p.set(f, "macro", 230)      # 201–255 strobe all colour
                p.set(f, "speed", 255)
                p.set(f, "dimmer", 255 * m)

        if "belka" in self.rig:
            b = self.rig["belka"]
            for ch, v in zip(("derby_red", "derby_green", "derby_blue", "derby_white"), L.derby):
                b.set(f, ch, 255 * v * m)
            b.set(f, "derby_motor", 255 * L.derby_motor if any(L.derby) else 0)
            for ch, v in zip(("par_red", "par_green", "par_blue", "par_white"), L.par):
                b.set(f, ch, 255 * v * m)
            rng = b.ranges.get("laser", {}).get(L.laser) if L.laser != "off" else None
            b.set(f, "laser", (rng[0] + rng[1]) / 2 if rng else 0)
            su, ss = (1.0, 0.95) if strobe else (L.strobe_uv, L.strobe_speed)
            b.set(f, "strobe_uv", 255 * su * (m if not strobe else 1))
            b.set(f, "strobe_speed", 255 * ss)

        if "movinghead" in self.rig:
            h = self.rig["movinghead"]
            h.set(f, "pan", 255 * L.pan)
            h.set(f, "pan_fine", 0)
            h.set(f, "tilt", h.limit("tilt", 255 * L.tilt))
            h.set(f, "tilt_fine", 0)
            h.set(f, "color", self._wheel(h, L.head_color))
            h.set(f, "gobo", self._gobo(h, L.gobo, L.gobo_mode))
            h.set(f, "strobe", 200 if strobe else 255 * L.head_strobe)
            h.set(f, "dimmer", 255 * (1.0 if strobe else L.head_dim) * m)
            h.set(f, "pt_speed", 255 * L.pt_speed)
            h.set(f, "program", 0)
            h.set(f, "reset", 0)
            h.set(f, "led_ring", 255 * L.ring)

    def _write_fog(self, f: bytearray, L: Look, on: bool, master: float) -> None:
        if "fog" not in self.rig:
            return
        fg = self.rig["fog"]
        fg.set(f, "fog", 255 if on else 0)
        # LED dymostroja svieti farbou lišty, aby bol dym farebný
        for ch, v in zip(("red", "green", "blue"), L.bar[:3]):
            w = L.bar[3]
            fg.set(f, ch, 255 * min(1.0, v + w) * L.bar_dim * master)

    @staticmethod
    def _wheel(h, rgbw) -> int:
        vals = h.values.get("color", {})
        r, g, b, w = rgbw
        rgb = (min(1, r + w), min(1, g + w), min(1, b + w))
        best, dist = "white", 9.0
        for name, ref in HEAD_WHEEL.items():
            if name not in vals:
                continue
            d = sum((x - y) ** 2 for x, y in zip(rgb, ref))
            if d < dist:
                best, dist = name, d
        v = vals.get(best, 0)
        return v if isinstance(v, int) else 0

    @staticmethod
    def _gobo(h, idx: int, mode: str) -> int:
        g = h.values.get("gobo", {})
        if idx <= 0:
            return g.get("open", 0)
        gobos = g.get("gobos", [8, 16, 24, 32, 40, 48, 56])
        if mode == "rotate":
            lo, hi = g.get("rotate", [128, 255])
            return lo + (hi - lo) // 3
        if mode == "shake":
            lo, hi = g.get("shake", [72, 127])
            return min(hi, lo + (idx - 1) * 8)
        return gobos[(idx - 1) % len(gobos)]

    # --- slučka -------------------------------------------------------------
    def run(self) -> None:
        next_t = time.monotonic()
        while not self._halt.is_set():
            now = time.monotonic()
            try:
                s = self.store.get()
                self.out.set_delay(s.light_delay_ms)
                frame = self.compute(self.an.snapshot(), now)
                self.last_frame = frame
                self.out.submit(frame)
            except Exception:  # jeden zlý frame nesmie zastaviť show
                log.exception("chyba v engine, pokračujem")
            next_t += self.period
            sleep = next_t - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.monotonic()
