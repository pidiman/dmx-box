"""AirPlay hrá ďalej aj pri výpadku reproduktora.

Problém: AirPlay (shairport-sync) hrá priamo do BT reproduktora. Keď spojenie zamrzne
(„link tx timeout“), výstup prestane brať zvuk, shairport sa zasekne a iPad reláciu ukončí.

Riešenie: stabilný virtuálny výstup `dmxbox_airplay` (null sink, beží vždy v reálnom čase)
+ loopback z neho do skutočného výstupu boxu. AirPlay hrá do virtuálneho výstupu, takže výpadok
reproduktora nevidí; loopback sa po výpadku prepojí na jack/kartu a po znovupripojení späť na BT.

Zapnutie: systemd drop-in pre airplay.service s PULSE_SINK=dmxbox_airplay (+ reštart AirPlay).
Strážca každých 5 s kontroluje, že virtuálny výstup existuje (napr. po reštarte PipeWire)
a že sa omylom nestal predvoleným výstupom (tým by vznikla slučka).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from . import system

log = logging.getLogger("dmxbox.airplay")

SINK = "dmxbox_airplay"
DROPIN = Path.home() / ".config" / "systemd" / "user" / "airplay.service.d" / "dmxbox-keep.conf"


class AirplayKeep(threading.Thread):
    def __init__(self, path: Path | None, interval: float = 5.0, sysmod=system, dropin: Path = DROPIN):
        super().__init__(daemon=True, name="airplay-keep")
        self.path, self.interval, self.sys, self.dropin = path, interval, sysmod, dropin
        self._halt = threading.Event()
        self.lock = threading.Lock()
        self.keep = True
        if path is not None:
            try:
                self.keep = bool(json.loads(path.read_text(encoding="utf-8")).get("keep", True))
            except (OSError, ValueError):
                pass
        self.available = sysmod.has("pactl") and sysmod.has("shairport-sync")
        self.live = {"active": False, "error": ""}

    def info(self) -> dict:
        return {"available": self.available, "keep": self.keep, **self.live}

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
        self.sys.run("pactl", "load-module", "module-loopback", f"source={SINK}.monitor",
                     "latency_msec=60", "source_dont_move=true", timeout=10)

    def _remove_sink(self) -> None:
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
            if self._sync_service():
                self._restart_airplay()
            self.live.update(active=self.keep and SINK in self._sinks(), error="")
        except (self.sys.CmdError, OSError) as e:
            self.live.update(active=False, error=str(e)[:160])

    def set_keep(self, on: bool) -> dict:
        with self.lock:
            self.keep = bool(on)
            if self.path is not None:
                try:
                    self.path.write_text(json.dumps({"keep": self.keep}), encoding="utf-8")
                except OSError:
                    pass
            self.apply()
        return self.info()

    def run(self) -> None:
        while not self._halt.is_set():
            with self.lock:
                self.apply()
            self._halt.wait(self.interval)

    def stop(self) -> None:
        self._halt.set()
