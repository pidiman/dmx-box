"""Ovládanie PipeWire cez pactl: line-in loopback (UCA202 IN → výstup)."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("dmxbox.audioctl")


def _pactl(*args: str) -> str:
    return subprocess.run(["pactl", *args], capture_output=True, text=True,
                          timeout=5, check=True).stdout.strip()


def _first(kind: str, needle: str = "usb") -> str | None:
    for line in _pactl("list", "short", kind).splitlines():
        name = line.split("\t")[1] if "\t" in line else ""
        if needle in name and not name.endswith(".monitor"):
            return name
    return None


class LineIn:
    def __init__(self, source: str = "auto", sink: str = "auto", latency_ms: int = 20):
        self.source, self.sink, self.latency = source, sink, latency_ms
        self.module_id: str | None = None

    @property
    def on(self) -> bool:
        return self.module_id is not None

    def set(self, on: bool) -> bool:
        try:
            if on and not self.on:
                src = _first("sources") if self.source == "auto" else self.source
                snk = _pactl("get-default-sink") if self.sink == "auto" else self.sink
                if not src:
                    log.warning("line-in: USB vstup nenájdený")
                    return False
                self.module_id = _pactl("load-module", "module-loopback", f"source={src}",
                                        f"sink={snk}", f"latency_msec={self.latency}")
                log.info("line-in zapnutý (%s → %s)", src, snk)
            elif not on and self.on:
                _pactl("unload-module", self.module_id)
                self.module_id = None
                log.info("line-in vypnutý")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("line-in: %s", e)
            return False
