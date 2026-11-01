"""Čo práve hrá: názov a interpret z mobilu cez Bluetooth (AVRCP).

Mobil pripojený ako zdroj hudby posiela boxu metadáta skladby. BlueZ ich vystaví na D-Bus
ako org.bluez.MediaPlayer1 (vlastnosť Track: Title, Artist, Album, Duration; Status).
Čítame ich cez `busctl` (súčasť systemd) raz za 2 s, bez ďalších Python knižníc.
Pri kábli (line-in) a simulácii nič nie je – appka potom názov nezobrazí.
"""

from __future__ import annotations

import json
import logging
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


class NowPlaying(threading.Thread):
    def __init__(self, interval: float = 2.0):
        super().__init__(daemon=True, name="nowplaying")
        self.interval = interval
        self.track = Track()
        self._halt = threading.Event()
        self.available = shutil.which("busctl") is not None

    def poll(self) -> Track:
        out = subprocess.run(["busctl", "--system", "--json=short", "call", "org.bluez", "/",
                              "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return Track()
        return parse_objects(json.loads(out.stdout))

    def run(self) -> None:
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
