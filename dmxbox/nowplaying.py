"""Čo práve hrá: názov a interpret z mobilu cez Bluetooth (AVRCP) alebo AirPlay.

Mobil pripojený ako zdroj hudby posiela boxu metadáta skladby. BlueZ ich vystaví na D-Bus
ako org.bluez.MediaPlayer1 (vlastnosť Track: Title, Artist, Album, Duration; Status).
Čítame ich cez `busctl` (súčasť systemd) raz za 2 s, bez ďalších Python knižníc.
AirPlay (shairport-sync) zapisuje metadáta do rúry /tmp/shairport-sync-metadata;
číta ich vlákno AirPlayMeta. Keď hrá AirPlay, má prednosť pred Bluetooth.
Pri kábli (line-in) a simulácii nič nie je – appka potom názov nezobrazí.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass

log = logging.getLogger("dmxbox.nowplaying")


@dataclass
class Track:
    title: str = ""
    artist: str = ""
    album: str = ""
    status: str = ""          # playing | paused | stopped
    source: str = ""          # meno zariadenia (napr. iPad)

    def as_dict(self) -> dict:
        return asdict(self)


def _val(v):
    """busctl --json: hodnota variantu je {"type": "s", "data": ...}."""
    return v.get("data") if isinstance(v, dict) and "data" in v else v


def parse_objects(data: dict) -> Track:
    """Z výsledku GetManagedObjects vyberie prehrávač (prednostne ten, ktorý hrá)."""
    objs = _val(data.get("data", [data])[0]) if "data" in data else data
    names = {}
    players = []
    for path, ifaces in objs.items():
        dev = ifaces.get("org.bluez.Device1")
        if dev:
            names[path] = _val(dev.get("Alias") or dev.get("Name") or {}) or ""
        mp = ifaces.get("org.bluez.MediaPlayer1")
        if mp:
            players.append((path, mp))
    best = None
    for path, mp in players:
        status = _val(mp.get("Status", {})) or ""
        if best is None or status == "playing":
            best = (path, mp, status)
    if not best:
        return Track()
    path, mp, status = best
    track = _val(mp.get("Track", {})) or {}
    dev_path = path.rsplit("/", 1)[0]
    return Track(title=str(_val(track.get("Title", "")) or ""), artist=str(_val(track.get("Artist", "")) or ""),
                 album=str(_val(track.get("Album", "")) or ""), status=status,
                 source=names.get(dev_path, ""))


ITEM_RE = re.compile(r"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
                     r"(?:\s*<data encoding=\"base64\">\s*(.*?)</data>)?</item>", re.S)


def _fourcc(h: str) -> str:
    return bytes.fromhex(h).decode("ascii", "replace")


class AirPlayMeta(threading.Thread):
    """Číta metadáta shairport-sync z rúry: názov (minm), interpret (asar), album (asal),
    začiatok/koniec prehrávania (pbeg/pend), meno zariadenia (snam)."""

    def __init__(self, pipe: str = "/tmp/shairport-sync-metadata"):
        super().__init__(daemon=True, name="airplay-meta")
        self.pipe = pipe
        self.track = Track()
        self.playing = False

    def feed(self, text: str) -> str:
        """Spracuje kus textu z rúry, vráti nespracovaný zvyšok."""
        last = 0
        for m in ITEM_RE.finditer(text):
            last = m.end()
            typ, code = _fourcc(m.group(1)), _fourcc(m.group(2))
            data = ""
            if m.group(4):
                try:
                    data = base64.b64decode(m.group(4)).decode("utf-8", "replace")
                except ValueError:
                    data = ""
            if typ == "core" and code == "minm":
                # nová skladba = hrá sa, aj keď sme začiatok prehrávania (pbeg) zmeškali,
                # napr. po reštarte boxu počas hrania
                self.track.title = data
                self.playing = True
                if self.track.status != "paused":
                    self.track.status = "playing"
            elif typ == "core" and code == "asar":
                self.track.artist = data
            elif typ == "core" and code == "asal":
                self.track.album = data
            elif typ == "ssnc" and code == "snam":
                self.track.source = data
            elif typ == "ssnc" and code in ("pbeg", "prsm", "prgr"):
                self.playing, self.track.status = True, "playing"
            elif typ == "ssnc" and code == "pfls":
                self.track.status = "paused"
            elif typ == "ssnc" and code == "pend":
                self.playing, self.track = False, Track()
        return text[last:] if last else text[-20000:]

    def run(self) -> None:
        while True:
            if not os.path.exists(self.pipe):
                time.sleep(5)
                continue
            try:
                with open(self.pipe, encoding="utf-8", errors="replace") as f:   # čaká na shairport
                    buf = ""
                    while True:
                        chunk = f.readline()
                        if not chunk:
                            break
                        buf = self.feed(buf + chunk)
            except OSError as e:
                log.debug("airplay meta: %s", e)
                time.sleep(2)


class NowPlaying(threading.Thread):
    def __init__(self, interval: float = 2.0):
        super().__init__(daemon=True, name="nowplaying")
        self.interval = interval
        self._bt = Track()
        self._halt = threading.Event()
        self.available = shutil.which("busctl") is not None
        self.airplay = AirPlayMeta()

    @property
    def track(self) -> Track:
        if self.airplay.playing and self.airplay.track.title:
            return Track(**{**self.airplay.track.as_dict(), "source": self.airplay.track.source or "AirPlay"})
        return self._bt

    @track.setter
    def track(self, value: Track) -> None:
        self._bt = value

    def poll(self) -> Track:
        out = subprocess.run(["busctl", "--system", "--json=short", "call", "org.bluez", "/",
                              "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return Track()
        return parse_objects(json.loads(out.stdout))

    def run(self) -> None:
        self.airplay.start()
        if not self.available:
            return
        while not self._halt.is_set():
            try:
                self.track = self.poll()
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as e:
                log.debug("nowplaying: %s", e)
                self.track = Track()
            self._halt.wait(self.interval)

    def stop(self) -> None:
        self._halt.set()


def stub() -> NowPlaying:
    """Prehrávač bez vlákna (testy, Mac)."""
    np_ = NowPlaying()
    np_.available = False
    return np_


if __name__ == "__main__":   # rýchly test na Pi: python3 -m dmxbox.nowplaying
    p = NowPlaying()
    for _ in range(3):
        print(p.poll())
        time.sleep(1)
