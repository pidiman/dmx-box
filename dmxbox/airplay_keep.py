"""AirPlay hrá ďalej aj pri výpadku reproduktora.

Problém: AirPlay (shairport-sync) hrá priamo do BT reproduktora. Keď spojenie zamrzne
(„link tx timeout“), výstup prestane brať zvuk, shairport sa zasekne a iPad reláciu ukončí.

Riešenie: stabilný virtuálny výstup `dmxbox_airplay` (null sink, beží vždy v reálnom čase)
+ loopback z neho do skutočného výstupu boxu. AirPlay hrá do virtuálneho výstupu, takže výpadok
reproduktora nevidí; loopback sa po výpadku prepojí na jack/kartu a po znovupripojení späť na BT.

Zapnutie: systemd drop-in pre airplay.service s PULSE_SINK=dmxbox_airplay (+ reštart AirPlay).

Náskok svetiel (delay_ms): prepojenie do reproduktorov ide cez `pw-loopback --delay`, takže hudba
zaznie o pár sekúnd neskôr, kým analýza počúva virtuálny výstup hneď. Svetlá tak „vidia dopredu“
a vrchol trafí prvý úder dropu. Platí len v AirPlay scenári.
Strážca každých 5 s kontroluje, že virtuálny výstup existuje (napr. po reštarte PipeWire)
a že sa omylom nestal predvoleným výstupom (tým by vznikla slučka).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable

from . import system

log = logging.getLogger("dmxbox.airplay")

SINK = "dmxbox_airplay"
DROPIN = Path.home() / ".config" / "systemd" / "user" / "airplay.service.d" / "dmxbox-keep.conf"


class AirplayKeep(threading.Thread):
    DELAYS = (0, 1000, 2000, 3000)

    def __init__(self, path: Path | None, interval: float = 5.0, sysmod=system, dropin: Path = DROPIN,
                 on_delay: Callable[[float, str | None], None] | None = None):
        super().__init__(daemon=True, name="airplay-keep")
        self.path, self.interval, self.sys, self.dropin = path, interval, sysmod, dropin
        self._halt = threading.Event()
        self.lock = threading.Lock()
        self.keep = True
        self.delay_ms = 2000
        if path is not None:
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                self.keep = bool(d.get("keep", True))
                self.delay_ms = int(d.get("delay_ms", 2000))
            except (OSError, ValueError):
                pass
        self.available = sysmod.has("pactl") and sysmod.has("shairport-sync")
        self.live = {"active": False, "error": "", "delay_active": 0, "delay_supported": None}
        self.airplay_scenario = False        # nastaví scenár (AirPlay / BT reproduktor + AirPlay)
        self.on_delay = on_delay             # (sekundy náskoku, monitor na analýzu | None)
        self._proc: subprocess.Popen | None = None
        self._applied_delay = -1

    def info(self) -> dict:
        return {"available": self.available, "keep": self.keep, "delay_ms": self.delay_ms,
                "airplay_scenario": self.airplay_scenario, **self.live}

    # --- náskok svetiel ---------------------------------------------------------------------
    def _supports_delay(self) -> bool:
        if self.live["delay_supported"] is None:
            ok = False
            if self.sys.has("pw-loopback"):
                try:
                    r = subprocess.run(["pw-loopback", "--help"], capture_output=True, text=True, timeout=5)
                    ok = "--delay" in (r.stdout + r.stderr)
                except (OSError, subprocess.SubprocessError):
                    ok = False
            self.live["delay_supported"] = ok
        return bool(self.live["delay_supported"])

    def effective_delay(self) -> int:
        if not (self.keep and self.airplay_scenario and self.delay_ms > 0):
            return 0
        return self.delay_ms if self._supports_delay() else 0

    def _start_delay_loop(self, ms: int) -> None:
        self._stop_delay_loop()
        cmd = ["pw-loopback", "--name", "dmxbox-delay", "--delay", f"{ms / 1000:.2f}",
               "--capture-props", f"node.target={SINK} target.object={SINK} stream.capture.sink=true "
                                  "node.passive=true node.name=dmxbox_delay_in",
               "--playback-props", "node.name=dmxbox_delay_out media.role=Music"]
        log.info("AirPlay: náskok svetiel %d ms (%s)", ms, " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _stop_delay_loop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def _loop_modules(self) -> list[str]:
        out = self.sys.run("pactl", "list", "short", "modules", timeout=5)
        return [ln.split("\t")[0] for ln in out.splitlines() if "module-loopback" in ln and SINK in ln]

    def _sync_delay(self) -> None:
        """Prepojenie do reproduktorov: s oneskorením (pw-loopback) alebo bez (module-loopback)."""
        ms = self.effective_delay()
        if ms > 0:
            for mid in self._loop_modules():
                self.sys.run("pactl", "unload-module", mid, timeout=5)
            if self._proc is None or self._proc.poll() is not None or self._applied_delay != ms:
                self._start_delay_loop(ms)
        else:
            self._stop_delay_loop()
            if self.keep and SINK in self._sinks() and not self._loop_modules():
                self.sys.run("pactl", "load-module", "module-loopback", f"source={SINK}.monitor",
                             "latency_msec=60", "source_dont_move=true", timeout=10)
        if ms != self._applied_delay:
            self._applied_delay = ms
            self.live["delay_active"] = ms
            if self.on_delay:
                self.on_delay(ms / 1000.0, f"{SINK}.monitor" if ms > 0 else None)

    def set_delay(self, ms: int) -> dict:
        with self.lock:
            self.delay_ms = max(0, min(3000, int(ms)))
            self._save()
            self.apply()
        return self.info()

    def set_scenario(self, airplay: bool) -> None:
        with self.lock:
            self.airplay_scenario = bool(airplay)
            self.apply()

    def _save(self) -> None:
        if self.path is not None:
            try:
                self.path.write_text(json.dumps({"keep": self.keep, "delay_ms": self.delay_ms}), encoding="utf-8")
            except OSError:
                pass

    # --- PipeWire ------------------------------------------------------------------------
    def _sinks(self) -> dict[str, str]:
        out = self.sys.run("pactl", "list", "short", "sinks", timeout=5)
        res = {}
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) >= 2:
                res[p[1]] = p[0]
        return res

    def _modules(self) -> list[str]:
        out = self.sys.run("pactl", "list", "short", "modules", timeout=5)
        return [line.split("\t")[0] for line in out.splitlines() if SINK in line]

    def _ensure_sink(self) -> None:
        if SINK in self._sinks():
            return
        log.info("AirPlay: vytváram virtuálny výstup %s", SINK)
        # priority 0: PipeWire ho nikdy nezvolí ako predvolený výstup
        self.sys.run("pactl", "load-module", "module-null-sink", f"sink_name={SINK}",
                     "sink_properties='device.description=AirPlay-buffer priority.session=0 priority.driver=0'",
                     timeout=10)
        if not self.effective_delay():
            self.sys.run("pactl", "load-module", "module-loopback", f"source={SINK}.monitor",
                         "latency_msec=60", "source_dont_move=true", timeout=10)

    def _remove_sink(self) -> None:
        self._stop_delay_loop()
        for mid in self._modules():
            try:
                self.sys.run("pactl", "unload-module", mid, timeout=5)
            except self.sys.CmdError:
                pass

    def _guard_default(self) -> None:
        """Virtuálny výstup nesmie byť predvolený (slučka). Vráť skutočný výstup."""
        try:
            cur = self.sys.run("pactl", "get-default-sink", timeout=5)
        except self.sys.CmdError:
            return
        if cur != SINK:
            return
        sinks = [s for s in self.sys.audio_status().get("sinks", []) if not s["name"].startswith("dmxbox_")]
        pref = {"bluetooth": 0, "usb": 1, "jack": 2}
        sinks.sort(key=lambda s: pref.get(s.get("kind"), 3))
        if sinks:
            self.sys.run("pactl", "set-default-sink", sinks[0]["name"], timeout=5)

    # --- AirPlay služba ------------------------------------------------------------------
    def _dropin_wanted(self) -> str:
        return f"[Service]\nEnvironment=PULSE_SINK={SINK}\n" if self.keep else ""

    def _sync_service(self) -> bool:
        """Zapíše/zmaže drop-in. Vráti True, ak sa zmenil (treba reštart AirPlay)."""
        want = self._dropin_wanted()
        have = self.dropin.read_text(encoding="utf-8") if self.dropin.exists() else ""
        if want == have:
            return False
        if want:
            self.dropin.parent.mkdir(parents=True, exist_ok=True)
            self.dropin.write_text(want, encoding="utf-8")
        else:
            self.dropin.unlink(missing_ok=True)
        return True

    def _restart_airplay(self) -> None:
        self.sys.run("systemctl", "--user", "daemon-reload", timeout=15)
        try:
            active = self.sys.run("systemctl", "--user", "is-active", "airplay", timeout=5) == "active"
        except self.sys.CmdError:
            active = False
        if active:
            self.sys.run("systemctl", "--user", "restart", "airplay", timeout=30)

    def apply(self) -> None:
        if not self.available:
            return
        try:
            if self.keep:
                self._ensure_sink()
                self._guard_default()
            else:
                self._remove_sink()
            self._sync_delay()
            if self._sync_service():
                self._restart_airplay()
            self.live.update(active=self.keep and SINK in self._sinks(), error="")
        except (self.sys.CmdError, OSError) as e:
            self.live.update(active=False, error=str(e)[:160])

    def set_keep(self, on: bool) -> dict:
        with self.lock:
            self.keep = bool(on)
            self._save()
            self.apply()
        return self.info()

    def run(self) -> None:
        while not self._halt.is_set():
            with self.lock:
                self.apply()
            self._halt.wait(self.interval)

    def stop(self) -> None:
        self._halt.set()
        self._stop_delay_loop()
