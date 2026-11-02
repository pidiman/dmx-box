"""Prehrávač v ovládaní: odkiaľ ide hudba, kam hrá, hlasitosť a play/pauza.

Play/pauza ovláda zdroj, ak sa dá:
  AirPlay    – diaľkové ovládanie iPadu/iPhonu cez MPRIS rozhranie shairport-sync (session bus)
  Bluetooth  – AVRCP (org.bluez.MediaPlayer1 Play/Pause), rovnaký prehrávač ako názov skladby
Inak (Spotify Connect, kábel, nič) tlačidlo stlmí/zapne zvuk boxu.

Stav sa obnovuje vo vlákne každé 2 s (pactl/wpctl), WebSocket len číta hotový slovník.
"""

from __future__ import annotations

import logging
import re
import threading
import time

from . import system

log = logging.getLogger("dmxbox.player")

MPRIS = ("org.mpris.MediaPlayer2.ShairportSync", "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player")
SOURCE_NAMES = {"airplay": "AirPlay", "bt": "Bluetooth", "spotify": "Spotify Connect", "linein": "Kábel (line-in)"}


class Player(threading.Thread):
    def __init__(self, box, interval: float = 2.0, sysmod=system):
        super().__init__(daemon=True, name="player")
        self.box, self.interval, self.sys = box, interval, sysmod
        self._halt = threading.Event()
        self.state = {"available": sysmod.has("wpctl"), "volume": None, "muted": False,
                      "output": "", "spotify": False}
        self._spot_at = 0.0

    # --- stav -----------------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            out = self.sys.run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@", timeout=5)
            m = re.search(r"Volume:\s*([\d.]+)", out)
            self.state["volume"] = round(float(m.group(1)) * 100) if m else None
            self.state["muted"] = "MUTED" in out
        except self.sys.CmdError:
            self.state["volume"] = None
        try:
            st = self.sys.audio_status()
            d = next((s for s in st.get("sinks", []) if s.get("default")), None)
            if d:
                self.state["output"] = d["description"] if d.get("kind") == "bluetooth" else d["label"]
        except self.sys.CmdError:
            pass
        if time.monotonic() - self._spot_at > 15:      # systemctl je drahší, stačí občas
            self._spot_at = time.monotonic()
            try:
                self.state["spotify"] = bool(self.sys.spotify_status().get("active"))
            except self.sys.CmdError:
                pass

    def _source(self) -> tuple[str | None, object]:
        np_ = getattr(self.box, "nowplaying", None)
        if np_ is not None:
            ap = getattr(np_, "airplay", None)
            if ap is not None and ap.playing:
                return "airplay", ap.track
            bt = getattr(np_, "_bt", None)
            if bt is not None and bt.status in ("playing", "paused") and bt.path:
                return "bt", bt
        if self.box.line_in.on:
            return "linein", None
        if self.state["spotify"]:
            return "spotify", None
        return None, None

    def info(self) -> dict:
        src, tr = self._source()
        can_pause = src in ("airplay", "bt")
        if src == "bt":
            playing = tr.status == "playing"
        elif src == "airplay":
            playing = tr.status != "paused"           # shairport: pfls = pauza, prsm/prgr = hrá
        else:
            playing = None
        return {**self.state, "source": src, "source_name": SOURCE_NAMES.get(src, ""),
                "device": getattr(tr, "source", "") if tr is not None else "",
                "can_pause": can_pause, "playing": playing}

    # --- akcie ----------------------------------------------------------------------------
    def volume(self, value: int | None = None, step: int | None = None) -> dict:
        if value is not None:
            v = max(0, min(100, int(value)))
            self.sys.run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{v}%", timeout=5)
        elif step:
            sign = "+" if step > 0 else "-"
            self.sys.run("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(int(step))}%{sign}", timeout=5)
        if self.state["muted"]:
            self.sys.run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0", timeout=5)
        self.refresh()
        return self.info()

    def toggle(self) -> dict:
        src, tr = self._source()
        if src == "airplay":
            want_play = tr.status == "paused"
            self.sys.run("busctl", "--user", "call", *MPRIS, "Play" if want_play else "Pause", timeout=5)
            tr.status = "playing" if want_play else "paused"
        elif src == "bt":
            method = "Pause" if tr.status == "playing" else "Play"
            self.sys.run("busctl", "--system", "call", "org.bluez", tr.path, "org.bluez.MediaPlayer1", method, timeout=5)
            tr.status = "paused" if method == "Pause" else "playing"      # okamžitá odozva v appke
        else:
            self.sys.run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle", timeout=5)
        self.refresh()
        return self.info()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.refresh()
            except Exception as e:  # noqa: BLE001
                log.debug("player: %s", e)
            self._halt.wait(self.interval)

    def stop(self) -> None:
        self._halt.set()
