"""Engine: 40 Hz slučka, skladá vrstvy a zapisuje DMX rámec.

Poradie vrstiev (vyššia prepíše nižšiu):
blackout > strobe hold > manuálna farba > FX koleso 1 (farby) + 2 (pohyb) > master

Auto mód: FX dvojice, paleta a povolené efekty podľa štýlu hudby (styles.py, rozpoznaný
alebo pevne zvolený) a fázy skladby (breakdown / build / drop).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, replace

from .audio import Analyzer, AudioState
from .dmx_out import DMXOut
from .effects import OFF, Ctx, Look, scale
from .effects.color import COLOR_FX, PALETTES
from .effects.movement import MOVE_FX
from .fixtures import Rig
from .fog import FogController
from .state import Store
from .styles import LOOKS, StyleLook, look_for

log = logging.getLogger("dmxbox.engine")

# farby kolieska moving headu (profil → values.color) ako RGB
HEAD_WHEEL = {
    "white": (1, 1, 1), "red": (1, 0, 0), "yellow": (1, 1, 0), "blue": (0, 0, 1),
    "green": (0, 1, 0), "orange": (1, 0.5, 0), "pink": (1, 0, 1), "cyan": (0, 1, 1),
}


@dataclass
class Status:
    color_fx: str = ""
    move_fx: str = ""
    auto_index: int = 0
    idle: bool = True
    frame: int = 0
    style: str = "party"        # štýl, podľa ktorého sa práve svieti
    style_auto: bool = True     # rozpoznaný (True) alebo pevne zvolený
    section: str = "main"


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
        self._drop_count = 0
        self.identify: tuple | None = None      # (Fixture, do kedy) – svetlo bliká na bielo
        self.test: tuple | None = None          # (Fixture, {kanál: hodnota}, do kedy) – test kanálov z appky
        self._drop_beat = -1e9      # beat, kedy začal posledný drop

    def stop(self) -> None:
        self._halt.set()

    # --- výpočet jedného frame ------------------------------------------------
    def compute(self, a: AudioState, now: float) -> bytearray:
        s = self.store.get()
        if s.ambient:
            a, s = self._ambient(a, s, now)
        onset = a.onset_count != self._last_onset
        self._last_onset = a.onset_count
        self._flash = 1.0 if onset else self._flash * 0.82

        # štýl: rozpoznaný z hudby alebo pevne zvolený
        style_auto = s.style not in LOOKS
        look = look_for(a.style if style_auto else s.style)
        self.status.style, self.status.style_auto = look.key, style_auto
        section = a.section if s.auto else "main"
        self.status.section = section
        drop_event = a.drop_count != self._drop_count
        if drop_event:
            self._drop_count = a.drop_count
            self._drop_beat = a.beats

        palette_name = s.palette
        fs = s                       # nastavenia pre efekty (štýl ich v auto móde doladí)
        if s.auto:
            if s.style_palette:
                palette_name = look.palette
            fs = replace(s, fade=min(1.0, max(0.0, s.fade + look.fade_bias)),
                         size=min(1.0, max(0.0, s.size * look.size_k)),
                         laser=s.laser and look.laser and section != "breakdown",
                         uv=s.uv and look.uv)

        beats = a.beats * s.speed
        beat = int(math.floor(beats))
        ctx = Ctx(a=a, s=fs, beats=beats, beat=beat, phase=beats - beat, bar=beat // 4,
                  onset=onset, flash=self._flash,
                  palette=PALETTES.get(palette_name, PALETTES["party"]), t=now)

        color_name, move_name = self._pick_fx(s, a, ctx.bar, look, section)
        L = Look()
        drop_strobe = False
        if a.silent and not s.strobe:
            self._idle(ctx, L)
            self.status.idle = True
        else:
            COLOR_FX[color_name](ctx, L)
            MOVE_FX[move_name](ctx, L)
            self.status.idle = False
            if s.auto:
                drop_strobe = self._shape(L, look, section, a, fs)
        self.status.color_fx, self.status.move_fx = color_name, move_name

        if s.manual_color:
            mc = tuple(float(x) for x in s.manual_color[:4])
            L.bar, L.par, L.derby, L.head_color = mc, mc, mc, mc
            L.bar_dim = max(L.bar_dim, 0.8)
        if not s.laser:
            L.laser = "off"
        if not s.uv and L.strobe_speed == 0:
            L.strobe_uv = 0.0

        fog_on = self.fog.update(now, a, s.fog, s.fog_auto, s.fog_burst_s, s.blackout,
                                 drop=drop_event and look.fog_drop and not a.silent)

        frame = self.rig.new_frame()
        self._write(frame, L, s.master, strobe=s.strobe or drop_strobe)
        self._write_generic(frame, L, s.master, strobe=s.strobe or drop_strobe, fog_on=fog_on)
        self._write_fog(frame, L, fog_on, s.master)
        if s.blackout:
            frame = self.rig.new_frame()
            self._write_safe_defaults(frame)
        frame = self._overrides(frame, now)
        self.status.frame += 1
        return frame

    # --- identifikácia a test kanálov (správa svetiel) ---------------------------------------
    def _overrides(self, frame: bytearray, now: float) -> bytearray:
        if self.test and now < self.test[2]:
            fx, vals, _ = self.test
            frame = self.rig.new_frame()
            self._write_safe_defaults(frame)
            for ch, v in vals.items():
                fx.set(frame, ch, v)
            return frame
        if self.identify and now < self.identify[1]:
            fx = self.identify[0]
            frame = self.rig.new_frame()
            self._write_safe_defaults(frame)
            on = int(now * 4) % 2 == 0          # 2× za sekundu, aby bolo jasné, ktoré svieti
            for ch, fn in fx.fns.items():
                if fn in ("dimmer", "red", "green", "blue", "white", "amber"):
                    fx.set(frame, ch, 255 if on else 0)
                elif fn in ("pan", "tilt"):
                    fx.set(frame, ch, fx.limit(fn, 128))
            return frame
        return frame

    # --- ďalšie svetlá podľa funkcií kanálov (pridané v appke) --------------------------------
    KNOWN = ("parbar", "movinghead", "belka", "fog")

    def _write_generic(self, f: bytearray, L: Look, master: float, strobe: bool, fog_on: bool) -> None:
        m = max(0.0, min(1.0, master))
        for i, fx in enumerate(v for k, v in self.rig.fx.items() if k not in self.KNOWN):
            head = fx.type == "moving_head"
            color = L.head_color if head else L.derby if fx.type == "effect" else (L.par if i % 2 == 0 else L.bar)
            dim = L.head_dim if head else L.bar_dim
            has_dimmer = bool(fx.by_fn("dimmer"))
            k = 1.0 if has_dimmer else dim * m
            rgbw = {"red": color[0], "green": color[1], "blue": color[2], "white": color[3]}
            for ch, fn in fx.fns.items():
                if fn in rgbw:
                    fx.set(f, ch, 255 * rgbw[fn] * k)
                elif fn == "dimmer":
                    fx.set(f, ch, 255 * (1.0 if strobe else dim) * m)
                elif fn == "strobe":
                    fx.set(f, ch, 200 if strobe else 0)
                elif fn == "uv":
                    fx.set(f, ch, 255 * L.strobe_uv * m)
                elif fn in ("pan", "tilt"):
                    fx.set(f, ch, fx.limit(fn, 255 * (L.pan if fn == "pan" else L.tilt)))
                elif fn == "pt_speed":
                    fx.set(f, ch, 255 * L.pt_speed)
                elif fn == "color_wheel" and fx.values.get("color"):
                    fx.set(f, ch, self._wheel(fx, L.head_color))
                elif fn == "gobo" and fx.values.get("gobo"):
                    fx.set(f, ch, self._gobo(fx, L.gobo, L.gobo_mode))
                elif fn == "motor":
                    fx.set(f, ch, 255 * L.derby_motor if any(L.derby) else 0)
                elif fn == "fog":
                    fx.set(f, ch, 255 if fog_on else 0)
                # ostatné (makro, program, reset, efekt, iné) ostávajú 0 = DMX režim

    def _pick_fx(self, s, a: AudioState, bar: int, look: StyleLook, section: str) -> tuple[str, str]:
        if not s.auto:
            return s.color_fx, s.move_fx
        if section == "breakdown":
            return look.calm
        if section == "build":
            return look.build
        if section == "drop":
            return look.drop
        # main: striedanie dvojíc štýlu; auto_bars (predvolene 16) škáluje tempo striedania štýlu
        every = max(1, round(look.bars * s.auto_bars / 16))
        if self._auto_bar < 0 or (bar - self._auto_bar) >= every or bar < self._auto_bar:
            if self._auto_bar >= 0:
                self._auto_i += 1
            self._auto_bar = bar
        self.status.auto_index = self._auto_i
        return look.sets[self._auto_i % len(look.sets)]

    def _shape(self, L: Look, look: StyleLook, section: str, a: AudioState, fs) -> bool:
        """Úprava podľa štýlu a fázy skladby. Vráti True, ak má ísť krátke strobo dropu."""
        if not look.derby:
            L.derby, L.derby_motor = OFF, 0.0
        L.pt_speed = max(L.pt_speed, look.pt_slow)
        if section == "breakdown":
            # pokoj: tlmené farby, pomalý pohyb, bez lasera a stroboskopu (UV môže ostať)
            L.bar_dim *= 0.5
            L.par = scale(L.par, 0.4)
            L.derby, L.derby_motor = OFF, 0.0
            L.head_dim *= 0.6
            L.laser = "off"
            L.strobe_speed = 0.0
            L.strobe_uv = 0.6 if fs.uv else 0.0
            L.pt_speed = max(L.pt_speed, 0.7)
        elif section == "build":
            # napätie rastie: Belka strobo postupne zrýchľuje, lišta jasnie
            p = a.build_progress
            L.bar_dim = max(L.bar_dim, 0.3 + 0.5 * p)
            if look.strobe_drop and p > 0.25:
                L.strobe_uv, L.strobe_speed = 0.4 + 0.6 * p, 0.15 + 0.75 * p
        elif section == "drop":
            since = a.beats - self._drop_beat
            L.bar_dim = max(L.bar_dim, 0.9)
            L.head_dim = max(L.head_dim, 0.9)
            return look.strobe_drop and 0.0 <= since < 1.0     # strobo len 1 dobu
        return False

    AMBIENT_BPM = 30.0

    def _ambient(self, a: AudioState, s, now: float):
        """Svetlá bez hudby: pokojný štýl chill na pomalom „metronóme“, bez analýzy zvuku."""
        beats = now * self.AMBIENT_BPM / 60.0
        wave = 0.5 + 0.5 * math.sin(2 * math.pi * now / 8.0)
        fake = replace(a, bpm=self.AMBIENT_BPM, bpm_confident=True, beat_count=int(beats),
                       beat_phase=beats % 1.0, silent=False, onset_count=self._last_onset,
                       bass=0.3 + 0.3 * wave, mid=0.4, high=0.3, level=0.45 + 0.2 * wave,
                       style="chill", section="main", drop_count=self._drop_count,
                       build_progress=0.0)
        return fake, replace(s, auto=True, style="chill", laser=False, fog_auto=False,
                             strobe=s.strobe)

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

