"""Záznam prevádzky: čo box počas hrania robil, na neskoršie vylepšovanie.

Jeden JSON riadok na udalosť v logs/RRRR-MM-DD.jsonl. Druhy udalostí (`ev`):
  start    štart boxu (verzia, svetlá, DMX driver)
  track    nová skladba (názov, interpret, zdroj)
  music    každých 30 s: BPM, istota, štýl a skóre žánrov, časť skladby, hlasitosť
  style    zmena rozpoznaného štýlu
  section  zmena časti skladby (main/breakdown/build/drop), drop
  fx       efekty, ktoré beží (AUTO alebo ručne)
  silence  začiatok/koniec ticha
  action   ručný zásah v appke (POST/PUT/DELETE na /api, bez hesiel a PINov)
  sys      každú minútu: CPU, RAM, SD, teplota
  dmx / speaker  pripojenie a výpadky DMX donglu a BT reproduktora
  log      varovania a chyby z logu boxu

Zápis po dávkach (každých 30 s), aby sa šetrila SD karta. Uchováva sa najviac
`keep_days` dní a `max_mb` MB, staršie súbory sa mažú.
"""

from __future__ import annotations

import collections
import math
import io
import json
import logging
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger("dmxbox.sessionlog")

SECRET_KEYS = {"password", "pin", "new_pin", "psk", "secret"}
SKIP_PATHS = ("/api/auth", "/api/rig/test", "/api/log")     # test kanálov posiela keepalive


def _redact(data):
    if isinstance(data, dict):
        return {k: ("***" if k.lower() in SECRET_KEYS else _redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(v) for v in data[:50]]
    return data


class SessionLog(threading.Thread):
    def __init__(self, folder: Path, box=None, flush_s: float = 30.0, sample_s: float = 1.0,
                 keep_days: int = 14, max_mb: float = 20.0):
        super().__init__(daemon=True, name="sessionlog")
        self.dir = Path(folder)
        self.box = box
        self.flush_s, self.sample_s = flush_s, sample_s
        self.keep_days, self.max_bytes = keep_days, int(max_mb * 1024 * 1024)
        self.lock = threading.Lock()
        self.buf: list[dict] = []
        self._pending: dict[str, tuple[float, dict]] = {}     # zlúčenie posuvníkov (master…)
        self._halt = threading.Event()
        self._prev: dict = {}
        self._last = collections.defaultdict(float)
        self.cfg_path = self.dir / "settings.json"
        self.enabled = True
        try:
            self.enabled = bool(json.loads(self.cfg_path.read_text(encoding="utf-8")).get("enabled", True))
        except (OSError, ValueError):
            pass

    # --- zápis -----------------------------------------------------------------------
    def event(self, ev: str, **data) -> None:
        if not self.enabled:
            return
        rec = {"t": datetime.now().isoformat(timespec="seconds"), "ev": ev, **data}
        with self.lock:
            self.buf.append(rec)
            big = len(self.buf) >= 500
        if big:
            self.flush()

    def action(self, method: str, path: str, body: bytes, status: int) -> None:
        """Ručný zásah z appky. Rovnaká cesta v rade za sebou (posuvník) sa zlúči do posledného."""
        if not self.enabled or not path.startswith("/api/") or path.startswith(SKIP_PATHS):
            return
        try:
            data = _redact(json.loads(body)) if body else None
        except ValueError:
            data = None
        rec = {"method": method, "path": path, "body": data, "status": status}
        with self.lock:
            self._pending[f"{method} {path}"] = (time.monotonic(), rec)

    def _release_actions(self, force: bool = False) -> None:
        now = time.monotonic()
        with self.lock:
            ready = [k for k, (t, _) in self._pending.items() if force or now - t > 1.5]
            recs = [self._pending.pop(k)[1] for k in ready]
        for r in recs:
            self.event("action", **r)

    def flush(self) -> None:
        with self.lock:
            recs, self.buf = self.buf, []
        if not recs:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            by_day: dict[str, list[dict]] = collections.defaultdict(list)
            for r in recs:
                by_day[r["t"][:10]].append(r)
            for day, rs in by_day.items():
                with open(self.dir / f"{day}.jsonl", "a", encoding="utf-8") as f:
                    f.write("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rs))
            self._prune()
        except OSError as e:
            log.debug("sessionlog: %s", e)

    def _prune(self) -> None:
        files = sorted(self.dir.glob("*.jsonl"))
        while len(files) > self.keep_days:
            files.pop(0).unlink(missing_ok=True)
        total = sum(f.stat().st_size for f in files)
        while files and total > self.max_bytes and len(files) > 1:
            f = files.pop(0)
            total -= f.stat().st_size
            f.unlink(missing_ok=True)

    def set_enabled(self, on: bool) -> None:
        if on and not self.enabled:
            self.enabled = True
            self.event("log_on")
        elif not on and self.enabled:
            self.event("log_off")
            self.flush()
            self.enabled = False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.cfg_path.write_text(json.dumps({"enabled": self.enabled}), encoding="utf-8")
        except OSError:
            pass

    # --- čítanie ---------------------------------------------------------------------
    def files(self) -> list[dict]:
        self.flush()
        if not self.dir.is_dir():
            return []
        return [{"day": f.stem, "bytes": f.stat().st_size} for f in sorted(self.dir.glob("*.jsonl"), reverse=True)]

    def path_of(self, day: str) -> Path | None:
        if len(day) != 10 or not day.replace("-", "").isdigit():
            return None
        self.flush()
        p = self.dir / f"{day}.jsonl"
        return p if p.exists() else None

    def zip_all(self) -> bytes:
        self.flush()
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(self.dir.glob("*.jsonl")):
                z.write(f, f.name)
        return mem.getvalue()

    @staticmethod
    def read(path: Path) -> list[dict]:
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out

    def summary(self, day: str) -> dict | None:
        p = self.path_of(day)
        if not p:
            return None
        return summarize(self.read(p))

    # --- vzorkovanie stavu boxu ------------------------------------------------------------
    def _every(self, key: str, sec: float) -> bool:
        now = time.monotonic()
        if now - self._last[key] >= sec:
            self._last[key] = now
            return True
        return False

    def _changed(self, key: str, value) -> bool:
        if self._prev.get(key, object()) != value:
            first = key not in self._prev
            self._prev[key] = value
            return not first or key in ("track", "fx")
        return False

    def sample(self) -> None:
        b = self.box
        if b is None or not self.enabled:
            return
        a = b.analyzer.snapshot()
        st = b.engine.status
        s = b.store.get()
        np_ = getattr(b, "nowplaying", None)
        tr = np_.track if np_ else None
        if tr is not None and tr.title and self._changed("track", (tr.title, tr.artist)):
            self.event("track", title=tr.title, artist=tr.artist, album=tr.album, source=tr.source)
        if self._changed("silent", a.silent):
            self.event("silence", on=a.silent)
        if not a.silent:
            if self._changed("style", a.style):
                self.event("style", style=a.style, confidence=round(a.style_confidence, 2),
                           engine_style=st.style, fixed=not st.style_auto)
            if self._changed("section", a.section):
                self.event("section", section=a.section, build=round(a.build_progress, 2))
            if self._changed("drops", a.drop_count):
                self.event("drop", n=a.drop_count, bpm=round(a.bpm, 1))
            if self._changed("fx", (st.color_fx, st.move_fx, s.auto)):
                self.event("fx", color=st.color_fx, move=st.move_fx, auto=s.auto, style=st.style)
            if self._every("music", 30):
                self.event("music", bpm=round(a.bpm, 1), confident=a.bpm_confident, style=a.style,
                           confidence=round(a.style_confidence, 2),
                           scores={k: round(v, 2) for k, v in a.style_scores.items()},
                           section=a.section, level=round(a.level, 3), bass=round(a.bass, 3),
                           high=round(a.high, 3), master=s.master, delay_ms=s.light_delay_ms)
        out = b.out
        if self._changed("dmx", (out.driver, out.connected)):
            self.event("dmx", driver=out.driver, connected=out.connected)
        sp = getattr(b, "speaker", None)
        if sp is not None:
            i = sp.info()
            if self._changed("speaker", (i["connected"], i["reconnecting"], i["mac"])):
                self.event("speaker", name=i["name"], connected=i["connected"],
                           reconnecting=i["reconnecting"], reconnects=i["reconnects"], error=i["error"])
        stats = getattr(b, "sysstats", None)
        if stats is not None and self._every("sys", 60):
            v = stats.get()
            if v:
                self.event("sys", **v)

    def run(self) -> None:
        if self.box is not None:
            rig = getattr(self.box.engine, "rig", None)
            self.event("start", driver=self.box.out.driver,
                       fixtures=[f"{f.label} {f.name}".strip() for f in rig.fx.values()] if rig else [])
        next_flush = time.monotonic() + self.flush_s
        while not self._halt.is_set():
            try:
                self.sample()
                self._release_actions()
            except Exception as e:  # noqa: BLE001 – záznam nesmie zhodiť box
                log.debug("sessionlog sample: %s", e)
            if time.monotonic() >= next_flush:
                self.flush()
                next_flush = time.monotonic() + self.flush_s
            self._halt.wait(self.sample_s)
        self._release_actions(force=True)
        self.flush()

    def stop(self) -> None:
        self._halt.set()


class LogHandler(logging.Handler):
    """Varovania a chyby z logu boxu → udalosť `log` (aby boli pri sebe s tým, čo sa dialo)."""

    def __init__(self, slog: SessionLog):
        super().__init__(level=logging.WARNING)
        self.slog = slog

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("dmxbox.sessionlog"):
            return
        try:
            self.slog.event("log", level=record.levelname, src=record.name, msg=record.getMessage()[:300])
        except Exception:  # noqa: BLE001
            pass


def summarize(recs: list[dict]) -> dict:
    """Súhrn jedného dňa pre appku."""
    if not recs:
        return {"events": 0}
    tracks, drops, actions, outages, errors = [], 0, 0, [], 0
    style_time: dict[str, float] = collections.defaultdict(float)
    cpu, temp = [], []
    music = [r for r in recs if r["ev"] == "music"]
    for r in recs:
        ev = r["ev"]
        if ev == "track":
            tracks.append(f"{r.get('artist', '')} – {r.get('title', '')}".strip(" –"))
        elif ev == "drop":
            drops += 1
        elif ev == "action":
            actions += 1
        elif ev == "sys":
            if r.get("cpu") is not None:
                cpu.append(r["cpu"])
            if r.get("temp") is not None:
                temp.append(r["temp"])
        elif ev == "speaker" and not r.get("connected") and r.get("name"):
            outages.append({"t": r["t"][11:16], "what": f"BT reproduktor {r['name']}"})
        elif ev == "dmx" and not r.get("connected") and r.get("driver") != "dry":
            outages.append({"t": r["t"][11:16], "what": "DMX dongle"})
        elif ev == "log" and r.get("level") in ("ERROR", "CRITICAL"):
            errors += 1
    for r in music:
        style_time[r.get("style", "?")] += 0.5            # 1 záznam = 30 s
    t0, t1 = recs[0]["t"], recs[-1]["t"]
    return {
        "events": len(recs), "from": t0[11:16], "to": t1[11:16],
        "music_min": round(len(music) * 0.5), "tracks": len(tracks), "track_list": tracks[-30:],
        "styles_min": {k: math.ceil(v) for k, v in sorted(style_time.items(), key=lambda x: -x[1])},
        "drops": drops, "actions": actions, "outages": outages[-20:], "errors": errors,
        "cpu_avg": round(sum(cpu) / len(cpu)) if cpu else None, "cpu_max": max(cpu) if cpu else None,
        "temp_max": max(temp) if temp else None,
        "bpm_avg": round(sum(r.get("bpm", 0) for r in music) / len(music)) if music else None,
    }
