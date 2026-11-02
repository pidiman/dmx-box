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
import subprocess
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
        self.live = {"connected": False, "reconnecting": False, "reconnects": 0, "error": "",
                     "stall_fixes": 0, "kernel_watch": False}
        # zamrznuté spojenie („link tx timeout“): bluetoothctl hlási Connected, ale zvuk netečie
        self._stall_at, self._last_fix = 0.0, 0.0
        self._wake = threading.Event()
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

    # --- zamrznuté spojenie (správy jadra) ---------------------------------------------------
    STALL_MARKS = ("link tx timeout", "killing stalled connection")

    def kernel_line(self, line: str) -> None:
        if "Bluetooth" in line and any(m in line for m in self.STALL_MARKS):
            self._stall_at = time.monotonic()
            self._wake.set()

    def _follow_kernel(self) -> None:
        """journalctl -k -f: používateľ v skupine adm/systemd-journal číta správy jadra bez sudo."""
        while not self._halt.is_set():
            started = time.monotonic()
            try:
                proc = subprocess.Popen(["journalctl", "-k", "-f", "-n", "0", "-o", "cat"],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            except OSError:
                return
            self.live["kernel_watch"] = True
            try:
                for line in proc.stdout:
                    self.kernel_line(line)
                    if self._halt.is_set():
                        break
            finally:
                proc.kill()
                self.live["kernel_watch"] = False
            if time.monotonic() - started < 5:          # bez prístupu k logu jadra – skús o minútu
                self._halt.wait(60)

    def _fix_stall(self, mac: str, want: bool) -> None:
        log.warning("BT spojenie s %s zamrzlo (link tx timeout) – odpájam a pripájam znova", mac)
        self._last_fix = time.monotonic()
        self.live["reconnecting"] = True
        try:
            self.sys.run("bluetoothctl", "disconnect", mac, timeout=15)
        except self.sys.CmdError:
            pass
        time.sleep(3)
        try:
            self.sys.run("bluetoothctl", "--timeout", "15", "connect", mac, timeout=25)
        except self.sys.CmdError as e:
            self.live.update(connected=False, error=str(e)[:120])
            return                                   # ďalší tick to skúsi bežnou cestou
        self.live.update(connected=True, reconnecting=False, error="")
        self.live["stall_fixes"] += 1
        self._restore_output(mac, want)

    def _restore_output(self, mac: str, want: bool) -> None:
        if not want:
            return
        for _ in range(8):                           # PipeWire vytvorí sink o chvíľu
            sink = self._sink_of(mac)
            if sink:
                if self._default_sink() == sink:     # už prepnuté – ďalšie prepnutie = výpadok zvuku
                    return
                try:
                    self.sys.audio_output(sink)
                except self.sys.CmdError as e:
                    self.live["error"] = str(e)[:120]
                return
            time.sleep(1)

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
        stalled = self._stall_at > self._last_fix
        if conn:
            mac, name = next(((m, n) for m, n in conn if m == target), conn[0])
            with self.lock:
                fix = (stalled and mac == target and self.state["auto"] and not self.state["paused"]
                       and time.monotonic() - self._last_fix > 20)
                want_now = self.state["want_output"]
            if fix:
                self._fix_stall(mac, want_now)
                return
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
        self._last_fix = time.monotonic()            # zamrznutie vyriešené novým spojením
        log.info("BT reproduktor %s znova pripojený", mac)
        self.live.update(connected=True, reconnecting=False, error="")
        self.live["reconnects"] += 1
        self._restore_output(mac, want)

    def run(self) -> None:
        if self.available and self.sys.has("journalctl"):
            threading.Thread(target=self._follow_kernel, daemon=True, name="bt-kernel").start()
        while not self._halt.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 – strážca nesmie spadnúť
                log.debug("speaker: %s", e)
            self._wake.wait(self.interval)             # zamrznutie zobudí strážcu hneď
            self._wake.clear()

    def stop(self) -> None:
        self._halt.set()
        self._wake.set()
