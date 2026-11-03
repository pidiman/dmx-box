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
        self._drop_since: float | None = None
        self._half_since: float | None = None
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
        """Ručné pripojenie v appke: tento reproduktor je odteraz cieľ, automatika beží."""
        with self.lock:
            if self.state["mac"] != mac:
                self.state.update(mac=mac, name="", want_output=True)
            self.state["paused"] = False
            self._save()
        self._drop_since = None

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

    GRACE_S = 25.0          # po výpadku nechaj reproduktor/PipeWire pripojiť sa samých (inak sa pokusy bijú)
    HALF_S = 25.0           # pripojený, ale bez zvukového výstupu tak dlho = polovičné spojenie
    CYCLE_MIN_S = 60.0      # čisté odpojenie+pripojenie najviac raz za minútu

    def _info(self, mac: str) -> str:
        try:
            return self.sys.run("bluetoothctl", "info", mac, timeout=8)
        except self.sys.CmdError:
            return ""

    def _is_connected(self, mac: str) -> bool | None:
        """True/False podľa BlueZ; None = nevieme (bluetoothctl neodpovedal) – vtedy nič nerob."""
        info = self._info(mac)
        if not info:
            return None
        return "Connected: yes" in info

    def _clean_cycle(self, mac: str, want: bool, why: str) -> None:
        log.warning("BT reproduktor %s: %s – odpájam a pripájam znova", mac, why)
        self._last_fix = time.monotonic()
        self.live["reconnecting"] = True
        try:
            self.sys.run("bluetoothctl", "disconnect", mac, timeout=15)
        except self.sys.CmdError:
            pass
        time.sleep(3)
        try:
            self.sys.run("bluetoothctl", "--timeout", "15", "connect", mac, timeout=25)
            self.live["stall_fixes"] += 1
        except self.sys.CmdError as e:
            self.live["error"] = str(e)[:120]
        self._drop_since = None
        self._restore_output(mac, want)

    def tick(self) -> None:
        if not self.available:
            return
        now = time.monotonic()
        with self.lock:
            target, auto, paused = self.state["mac"], self.state["auto"], self.state["paused"]
            want = self.state["want_output"]
        if not target:                                   # ešte nepoznáme reproduktor: nájdi pripojený
            try:
                conn = self._speakers()
            except self.sys.CmdError as e:
                self.live["error"] = str(e)
                return
            if not conn:
                self.live.update(connected=False, reconnecting=False)
                return
            target = conn[0][0]
            with self.lock:
                self.state.update(mac=target, name=conn[0][1])
                self._save()
        info = self._info(target)
        if not info:
            return
        connected = "Connected: yes" in info
        if connected and "Trusted: no" in info:     # bez dôvery BlueZ odmieta, keď sa reproduktor pripája sám
            try:
                self.sys.run("bluetoothctl", "trust", target, timeout=8)
            except self.sys.CmdError:
                pass
        if connected:
            recovered = self._drop_since is not None    # vrátil sa sám počas čakania
            self._drop_since = None
            self._fails, self._next_try = 0, 0.0
            sink = self._sink_of(target)
            if recovered and sink and want:
                self._restore_output(target, want)       # zvuk späť naň; „want“ neprepisuj jackom
            on_bt = self._default_sink().startswith("bluez")
            if sink:
                self._half_since = None
            elif self._half_since is None:
                self._half_since = now
            stalled = self._stall_at > self._last_fix
            half = self._half_since is not None and now - self._half_since > self.HALF_S
            if (auto and not paused and (stalled or (half and want))
                    and now - self._last_fix > self.CYCLE_MIN_S):
                self._clean_cycle(target, want, "zamrznuté spojenie" if stalled else "pripojený bez zvukového výstupu")
                return
            name = self.state["name"]
            if not name:
                name = next((n for m, n in self.sys._bt_devices("Connected") if m == target), "")
            with self.lock:
                changed = (name, on_bt) != (self.state["name"], self.state["want_output"]) and bool(sink)
                if sink:                                 # výstup si pamätaj len pri plnom spojení
                    self.state.update(name=name, want_output=on_bt, paused=False)
                self.live.update(connected=True, reconnecting=False, error="")
                if changed:
                    self._save()
            return
        # odpojený – ak medzitým hrá iný spárovaný reproduktor, ten je nový cieľ (nenaháňaj starý)
        try:
            other = [(m, n) for m, n in self._speakers() if m != target]
        except self.sys.CmdError:
            other = []
        if other:
            with self.lock:
                self.state.update(mac=other[0][0], name=other[0][1], paused=False)
                self._save()
            self._drop_since, self._fails, self._next_try = None, 0, 0.0
            self.live.update(connected=True, reconnecting=False, error="")
            return
        self._half_since = None
        if self.live.get("connected"):
            self.live["connected"] = False
        if not auto or paused:
            self.live["reconnecting"] = False
            self._drop_since = None
            return
        if self._drop_since is None:
            self._drop_since = now
        self.live["reconnecting"] = True
        if now - self._drop_since < self.GRACE_S or now < self._next_try:
            return
        try:
            self.sys.run("bluetoothctl", "--timeout", "15", "connect", target, timeout=25)
        except self.sys.CmdError as e:
            self.live["error"] = str(e)[:120]
            self._fails += 1                             # 10 s, 20 s … max 60 s medzi pokusmi
            self._next_try = time.monotonic() + min(60.0, self.interval * self._fails)
            return
        self._last_fix = time.monotonic()
        if self._is_connected(target):                   # over, nie naslepo
            log.info("BT reproduktor %s znova pripojený", target)
            self._fails, self._next_try, self._drop_since = 0, 0.0, None
            self.live.update(connected=True, reconnecting=False, error="")
            self.live["reconnects"] += 1
            self._restore_output(target, want)
        else:
            self._fails += 1
            self._next_try = time.monotonic() + min(60.0, self.interval * self._fails)

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
