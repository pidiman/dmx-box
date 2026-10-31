"""DMX výstup: uDMX klon (16c0:05dc) cez pyusb, po 8 kanáloch.

Lixada / anyma uDMX klon nezvláda celý univerz v jednom transfere
(USB I/O chyby, jitter na wireless linke). Posielame len prvých N kanálov
po malých kusoch cez vendor request SetChannelRange (bRequest=2).
"""

from __future__ import annotations

import collections
import logging
import threading
import time

log = logging.getLogger("dmxbox.dmx")

VID, PID = 0x16C0, 0x05DC
REQ_SET_CHANNEL_RANGE = 2
BM_REQUEST_TYPE = 0x40  # vendor | device | host→device


def _backend():
    """libusb backend; na Macu s Homebrew nie je libusb v štandardnej ceste."""
    import os

    import usb.backend.libusb1 as lb
    be = lb.get_backend()
    if be is None:
        for path in ("/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"):
            if os.path.exists(path):
                be = lb.get_backend(find_library=lambda _n, p=path: p)
                if be:
                    break
    return be


class UDMXDevice:
    def __init__(self):
        self.dev = None

    def open(self) -> bool:
        try:
            import usb.core  # pyusb
        except ImportError:
            log.error("pyusb nie je nainštalovaný (apt install python3-usb)")
            return False
        try:
            self.dev = usb.core.find(idVendor=VID, idProduct=PID, backend=_backend())
        except usb.core.NoBackendError:
            log.error("libusb nenájdený (Mac: brew install libusb, Pi: apt install libusb-1.0-0)")
            return False
        if self.dev is None:
            return False
        try:
            self.dev.set_configuration()
        except Exception:  # už nakonfigurované / bez oprávnení
            pass
        log.info("uDMX pripojený")
        return True

    def send(self, data: bytes, chunk: int) -> None:
        for start in range(0, len(data), chunk):
            part = data[start:start + chunk]
            self.dev.ctrl_transfer(BM_REQUEST_TYPE, REQ_SET_CHANNEL_RANGE,
                                   len(part), start, part, timeout=100)

    def close(self) -> None:
        self.dev = None


class DMXOut(threading.Thread):
    """Posiela posledný rámec s pevnou frekvenciou, s voliteľným oneskorením."""

    def __init__(self, driver: str = "udmx", fps: int = 40, channels: int = 32,
                 chunk: int = 8, delay_ms: int = 0):
        super().__init__(daemon=True, name="dmx-out")
        self.driver = driver
        self.period = 1.0 / max(1, fps)
        self.channels = channels
        self.chunk = chunk
        self.delay_ms = delay_ms
        self._lock = threading.Lock()
        self._queue: collections.deque[tuple[float, bytes]] = collections.deque()
        self._current = bytes(channels)
        self._halt = threading.Event()
        self.dev = UDMXDevice() if driver == "udmx" else None
        self.connected = driver == "dry"
        self.frames_sent = 0
        self.last = bytes(channels)

    # --- API pre engine -------------------------------------------------
    def submit(self, frame: bytes | bytearray) -> None:
        data = bytes(frame[: self.channels])
        with self._lock:
            self._queue.append((time.monotonic(), data))
            # v rade netreba držať viac než ~2 s
            while len(self._queue) > 200:
                self._queue.popleft()

    def set_delay(self, ms: int) -> None:
        self.delay_ms = max(0, min(1000, int(ms)))

    def blackout(self) -> None:
        with self._lock:
            self._queue.clear()
            self._current = bytes(self.channels)
        self._write(self._current)

    def stop(self, blackout: bool = True) -> None:
        if blackout:
            self.blackout()
        self._halt.set()

    # --- vlákno ---------------------------------------------------------
    def _pick(self) -> bytes:
        due = time.monotonic() - self.delay_ms / 1000.0
        with self._lock:
            while self._queue and self._queue[0][0] <= due:
                self._current = self._queue.popleft()[1]
            return self._current

    def _write(self, data: bytes) -> None:
        self.last = data
        if self.driver == "dry":
            self.frames_sent += 1
            return
        if not self.connected:
            self.connected = self.dev.open()
            if not self.connected:
                return
        try:
            self.dev.send(data, self.chunk)
            self.frames_sent += 1
        except Exception as e:  # odpojenie, I/O chyba
            log.warning("uDMX chyba (%s), skúsim znova pripojiť", e)
            self.dev.close()
            self.connected = False

    def run(self) -> None:
        next_t = time.monotonic()
        last_retry = 0.0
        while not self._halt.is_set():
            if self.driver == "udmx" and not self.connected:
                if time.monotonic() - last_retry < 2.0:
                    time.sleep(0.1)
                    continue
                last_retry = time.monotonic()
            self._write(self._pick())
            next_t += self.period
            sleep = next_t - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.monotonic()
