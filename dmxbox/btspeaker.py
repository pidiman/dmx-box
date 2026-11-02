"""Bluetooth reproduktor: stav pre appku a automatické znovupripojenie po výpadku.

Každých `interval` sekúnd zistí, či je pripojený nejaký spárovaný reproduktor (ikona audio-*).
Pripojený reproduktor si zapamätá ako cieľ. Keď vypadne a automatické pripojenie je zapnuté,
skúša ho znova pripojiť; ak bol predtým výstupom zvuku, vráti naň zvuk aj analýzu.

Ručné „Odpojiť“ v appke automatiku pozastaví (box nebude reproduktor naťahovať späť),
„Pripojiť“ ju obnoví. Stav sa drží v speaker.json, aby prežil reštart boxu.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from . import system

log = logging.getLogger("dmxbox.speaker")


class SpeakerWatch(threading.Thread):
    def __init__(self, path: Path | None, interval: float = 10.0, sysmod=system):
        super().__init__(daemon=True, name="bt-speaker")
        self.path, self.interval, self.sys = path, interval, sysmod
        self.lock = threading.Lock()
        self._halt = threading.Event()
        self.state = {"auto": True, "mac": None, "name": "", "want_output": False, "paused": False}
        if path is not None:
            try:
                self.state.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        self.live = {"connected": False, "reconnecting": False, "reconnects": 0, "error": ""}
        self.available = sysmod.has("bluetoothctl")
        self._fails, self._next_try = 0, 0.0     # vypnutý reproduktor nenaháňať každých 10 s donekonečna

    # --- stav ----------------------------------------------------------------------
    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            log.warning("speaker.json: %s", e)

    def info(self) -> dict:
        with self.lock:
            return {"available": self.available, "auto": self.state["auto"], "name": self.state["name"],
                    "mac": self.state["mac"], "paused": self.state["paused"], **self.live}

    def set_auto(self, on: bool) -> dict:
        with self.lock:
            self.state["auto"] = bool(on)
            self._save()
        return self.info()

    # volané z API pri ručných akciách v appke
    def manual_connect(self, mac: str) -> None:
        """Ručné pripojenie obnoví automatiku; cieľ si strážca vezme, až keď uvidí pripojený reproduktor."""
        with self.lock:
            self.state["paused"] = False
            self._save()

    def manual_disconnect(self, mac: str) -> None:
        with self.lock:
            if self.state["mac"] == mac:
                self.state["paused"] = True
                self._save()

    def forget(self, mac: str) -> None:
        with self.lock:
            if self.state["mac"] == mac:
                self.state.update(mac=None, name="", want_output=False, paused=False)
                self._save()

    # --- kontrola ------------------------------------------------------------------
    def _speakers(self) -> list[tuple[str, str]]:
        return [(mac, name) for mac, name in self.sys._bt_devices("Connected")
                if self.sys._bt_icon(mac).startswith("audio")]

    def _default_sink(self) -> str:
        try:
            return self.sys.run("pactl", "get-default-sink", timeout=5)
        except self.sys.CmdError:
            return ""

    def _sink_of(self, mac: str) -> str | None:
        key = mac.replace(":", "_").upper()
        try:
            for s in self.sys.audio_status().get("sinks", []):
                if s["name"].startswith("bluez") and key in s["name"].upper():
                    return s["name"]
        except self.sys.CmdError:
            pass
        return None

    def tick(self) -> None:
        if not self.available:
            return
        try:
            conn = self._speakers()
        except self.sys.CmdError as e:
            self.live["error"] = str(e)
            return
        with self.lock:
            target = self.state["mac"]
        if conn:
            mac, name = next(((m, n) for m, n in conn if m == target), conn[0])
            on_bt = self._default_sink().startswith("bluez")
            self._fails, self._next_try = 0, 0.0
            with self.lock:
                changed = (mac, name, on_bt) != (self.state["mac"], self.state["name"], self.state["want_output"])
                self.state.update(mac=mac, name=name, want_output=on_bt, paused=False)
                self.live.update(connected=True, reconnecting=False, error="")
                if changed:
                    self._save()
            return
        with self.lock:
            self.live["connected"] = False
            go = self.state["auto"] and self.state["mac"] and not self.state["paused"]
            mac, want = self.state["mac"], self.state["want_output"]
        if not go:
            self.live["reconnecting"] = False
            return
        self.live["reconnecting"] = True
        if time.monotonic() < self._next_try:
            return
        try:
            self.sys.run("bluetoothctl", "--timeout", "15", "connect", mac, timeout=25)
        except self.sys.CmdError as e:
            self.live["error"] = str(e)[:120]
            self._fails += 1                     # 10 s, 20 s … max 60 s medzi pokusmi
            self._next_try = time.monotonic() + min(60.0, self.interval * self._fails)
            return
        self._fails, self._next_try = 0, 0.0
        log.info("BT reproduktor %s znova pripojený", mac)
        self.live.update(connected=True, reconnecting=False, error="")
        self.live["reconnects"] += 1
        if want:                                  # vrátiť naň zvuk (PipeWire vytvorí sink o chvíľu)
            for _ in range(8):
                sink = self._sink_of(mac)
                if sink:
                    try:
                        self.sys.audio_output(sink)
                    except self.sys.CmdError as e:
                        self.live["error"] = str(e)[:120]
                    break
                time.sleep(1)

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 – strážca nesmie spadnúť
                log.debug("speaker: %s", e)
            self._halt.wait(self.interval)

    def stop(self) -> None:
        self._halt.set()
