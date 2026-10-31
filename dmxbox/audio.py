"""Audio analýza: pásma, onsety (spectral flux), BPM a fáza beatu.

Vstup je mono float32 stream po blokoch `hop` vzoriek – na Pi z `parec`
(monitor výstupného sinku), v testoch zo simulátora. Len numpy, bez aubio.
"""

from __future__ import annotations

import collections
import copy
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Iterator

import numpy as np

log = logging.getLogger("dmxbox.audio")


@dataclass
class AudioState:
    bpm: float = 120.0
    bpm_confident: bool = False
    beat_phase: float = 0.0     # 0–1 v rámci beatu
    beat_count: int = 0         # rastie s každým beatom
    onset_count: int = 0        # rastie s každým kickom
    onset_strength: float = 0.0 # 0–1, sila posledného kicku
    bass: float = 0.0           # 0–1 po AGC
    mid: float = 0.0
    high: float = 0.0
    level: float = 0.0          # 0–1 celková hlasitosť po AGC
    rms: float = 0.0            # surová hlasitosť
    silent: bool = True
    t: float = 0.0              # čas v sekundách podľa počtu vzoriek

    @property
    def beats(self) -> float:
        """Spojitý čas v beatoch (beat_count + fáza)."""
        return self.beat_count + self.beat_phase


# --- zdroje -----------------------------------------------------------------

def default_monitor() -> str:
    try:
        sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
        if sink:
            return sink + ".monitor"
    except (OSError, subprocess.SubprocessError):
        pass
    return "@DEFAULT_MONITOR@"


def parec_source(device: str, rate: int, hop: int) -> Iterator[np.ndarray]:
    """Nekonečný generátor blokov z parec. Pri páde ho znova spustí."""
    if not shutil.which("parec"):
        raise RuntimeError("parec nenájdený (apt install pulseaudio-utils)")
    bytes_per_block = hop * 4
    while True:
        dev = default_monitor() if device == "auto" else device
        cmd = ["parec", "-d", dev, "--format=float32le", f"--rate={rate}",
               "--channels=1", "--latency-msec=10"]
        log.info("audio: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                raw = proc.stdout.read(bytes_per_block)
                if not raw or len(raw) < bytes_per_block:
                    break
                yield np.frombuffer(raw, dtype=np.float32)
        finally:
            proc.kill()
        log.warning("parec skončil, reštart o 1 s")
        time.sleep(1)


def list_inputs() -> list[str]:
    """Vstupné zvukové zariadenia (sounddevice) – na Mac/PC."""
    import sounddevice as sd
    return [f"{i}: {d['name']} ({d['max_input_channels']} ch)"
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def device_source(device: str, rate: int, hop: int) -> Iterator[np.ndarray]:
    """Bloky zo zvukového vstupu cez sounddevice, napr. 'BlackHole 2ch' na Macu.

    Na Pi sa nepoužíva (tam parec monitor), slúži na testy na Macu/PC.
    """
    import queue

    import sounddevice as sd
    dev: str | int = int(device) if device.isdigit() else device
    info = sd.query_devices(dev, "input")
    ch = max(1, min(2, int(info["max_input_channels"])))
    q: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)

    def cb(indata, frames, _time, status):  # noqa: ANN001
        if status:
            log.debug("audio status: %s", status)
        try:
            q.put_nowait(indata.mean(axis=1).astype(np.float32).copy())
        except queue.Full:
            pass

    log.info("audio: %s, %d ch, %d Hz", info["name"], ch, rate)
    with sd.InputStream(device=dev, channels=ch, samplerate=rate, blocksize=hop,
                        dtype="float32", callback=cb):
        while True:
            yield q.get()


# --- analyzátor ---------------------------------------------------------------

class Envelope:
    """Rýchly nábeh, pomalý dozvuk."""

    def __init__(self, attack: float, decay: float):
        self.a, self.d, self.v = attack, decay, 0.0

    def __call__(self, x: float) -> float:
        k = self.a if x > self.v else self.d
        self.v += (x - self.v) * k
        return self.v


class AGC:
    """Normalizuje hodnotu na 0–1 voči pomaly klesajúcemu maximu."""

    def __init__(self, fall: float = 0.9993, floor: float = 1e-4):
        self.peak, self.fall, self.floor = floor, fall, floor

    def __call__(self, x: float) -> float:
        self.peak = max(x, self.peak * self.fall, self.floor)
        return min(1.0, x / self.peak)


class Analyzer(threading.Thread):
    def __init__(self, source: Iterator[np.ndarray], rate: int = 44100, hop: int = 512,
                 fft: int = 1024, bpm_min: float = 80, bpm_max: float = 180,
                 silence_seconds: float = 4.0, realtime: bool = False):
        super().__init__(daemon=True, name="audio")
        self.source = source
        self.rate, self.hop, self.fft = rate, hop, fft
        self.bpm_min, self.bpm_max = bpm_min, bpm_max
        self.silence_seconds = silence_seconds
        self.realtime = realtime            # simulátor: spomaliť na reálny čas
        self.frame_rate = rate / hop        # ~86 Hz

        self.window = np.hanning(fft).astype(np.float32)
        freqs = np.fft.rfftfreq(fft, 1.0 / rate)
        self.bands = {
            "kick": (freqs >= 40) & (freqs < 160),
            "bass": (freqs >= 20) & (freqs < 150),
            "mid": (freqs >= 150) & (freqs < 2000),
            "high": (freqs >= 2000) & (freqs < 16000),
        }
        self.buf = np.zeros(fft, dtype=np.float32)
        self.prev_mag: np.ndarray | None = None

        hist = int(self.frame_rate * 8)     # 8 s histórie onset krivky
        self.flux_hist: collections.deque[float] = collections.deque(maxlen=hist)
        self.kick_hist: collections.deque[float] = collections.deque(maxlen=int(self.frame_rate))
        self.bpm_votes: collections.deque[float] = collections.deque(maxlen=7)
        self.agc = {k: AGC() for k in ("bass", "mid", "high", "level")}
        self.env = {k: Envelope(0.6, 0.08) for k in ("bass", "mid", "high", "level")}
        self.silence_floor = 1e-3

        self.state = AudioState()
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._frames = 0
        self._last_onset_t = -1.0
        self._quiet_since = 0.0
        self._override_bpm: float | None = None
        self._taps: collections.deque[float] = collections.deque(maxlen=8)

    # --- verejné API --------------------------------------------------------
    def snapshot(self) -> AudioState:
        with self._lock:
            return copy.copy(self.state)

    def stop(self) -> None:
        self._halt.set()

    def set_bpm_override(self, bpm: float | None) -> None:
        with self._lock:
            self._override_bpm = float(bpm) if bpm else None
            if bpm:
                self.state.bpm = float(bpm)

    def scale_bpm(self, factor: float) -> None:
        """Tlačidlá ½× / 2× pri chybe half/double tempa."""
        with self._lock:
            bpm = max(40.0, min(240.0, self.state.bpm * factor))
            self._override_bpm = bpm
            self.state.bpm = bpm

    def tap(self) -> None:
        """Tap tempo – každé ťuknutie zarovná fázu, z intervalov sa ráta BPM."""
        now = time.monotonic()
        if self._taps and now - self._taps[-1] > 2.0:
            self._taps.clear()
        self._taps.append(now)
        with self._lock:
            self.state.beat_phase = 0.0
            self.state.beat_count += 1
            if len(self._taps) >= 3:
                iv = np.diff(np.array(self._taps))
                self._override_bpm = 60.0 / float(np.median(iv))
                self.state.bpm = self._override_bpm

    # --- spracovanie ---------------------------------------------------------
    def run(self) -> None:
        period = self.hop / self.rate
        t0 = time.monotonic()
        for block in self.source:
            if self._halt.is_set():
                break
            self.process(block)
            if self.realtime:
                sleep = t0 + self._frames * period - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)

    def process(self, block: np.ndarray) -> None:
        n = len(block)
        self.buf = np.concatenate((self.buf[n:], block.astype(np.float32)))
        self._frames += 1
        t = self._frames * self.hop / self.rate
        dt = n / self.rate

        mag = np.abs(np.fft.rfft(self.buf * self.window))
        rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))

        # pásma po AGC + obálka
        energies = {k: float(np.mean(mag[m] ** 2)) for k, m in self.bands.items()}
        vals = {}
        for k in ("bass", "mid", "high"):
            vals[k] = self.env[k](self.agc[k](np.sqrt(energies[k])))
        vals["level"] = self.env["level"](self.agc["level"](rms))

        # spectral flux: celé spektrum (tempo) a kick pásmo (onsety)
        logmag = np.log1p(mag * 10.0)
        if self.prev_mag is None:
            self.prev_mag = logmag
        diff = np.maximum(logmag - self.prev_mag, 0.0)
        self.prev_mag = logmag
        flux = float(np.sum(diff))
        kick = float(np.sum(diff[self.bands["kick"]]))
        self.flux_hist.append(flux)
        self.kick_hist.append(kick)

        silent_now = rms < self.silence_floor
        if not silent_now:
            self._quiet_since = t
        silent = (t - self._quiet_since) > self.silence_seconds

        # onset detekcia s adaptívnym prahom
        onset = False
        strength = 0.0
        if len(self.kick_hist) > 10 and not silent_now:
            arr = np.fromiter(self.kick_hist, dtype=np.float64)
            thr = float(np.median(arr) + 1.6 * np.std(arr)) + 1e-3
            if kick > thr and t - self._last_onset_t > 0.12:
                onset = True
                strength = min(1.0, kick / (thr * 2.0))
                self._last_onset_t = t

        # odhad tempa raz za ~0,5 s
        if self._frames % max(1, int(self.frame_rate / 2)) == 0:
            self._estimate_tempo()

        with self._lock:
            s = self.state
            bpm = self._override_bpm or s.bpm
            # beat clock (PLL): fáza beží podľa BPM, onsety ju dolaďujú
            s.beat_phase += dt * bpm / 60.0
            if onset and self._override_bpm is None:
                err = s.beat_phase - round(s.beat_phase)  # -0.5..0.5 od najbližšieho beatu
                if abs(err) < 0.3:
                    s.beat_phase -= 0.35 * err
            while s.beat_phase >= 1.0:
                s.beat_phase -= 1.0
                s.beat_count += 1
            while s.beat_phase < 0.0:
                s.beat_phase += 1.0
            if onset:
                s.onset_count += 1
                s.onset_strength = strength
            s.bass, s.mid, s.high, s.level = vals["bass"], vals["mid"], vals["high"], vals["level"]
            s.rms = rms
            s.silent = silent
            s.t = t

    def _estimate_tempo(self) -> None:
        if self._override_bpm is not None or len(self.flux_hist) < self.frame_rate * 4:
            return
        x = np.fromiter(self.flux_hist, dtype=np.float64)
        x = x - x.mean()
        if not np.any(x):
            return
        ac = np.correlate(x, x, mode="full")[len(x) - 1:]
        fr = self.frame_rate
        lag_min = int(fr * 60.0 / self.bpm_max)
        lag_max = int(fr * 60.0 / self.bpm_min) + 1
        if lag_max >= len(ac):
            return
        lags = np.arange(lag_min, lag_max)
        # skóre: hlavný lag + jeho násobky (stabilnejšie voči half/double)
        score = ac[lags].copy()
        for mult in (2, 3, 4):
            idx = lags * mult
            ok = idx < len(ac)
            score[ok] += ac[idx[ok]] * 0.5
        best = int(lags[int(np.argmax(score))])
        # parabolická interpolácia pre presnejší lag
        if lag_min < best < lag_max - 1:
            a, b, c = ac[best - 1], ac[best], ac[best + 1]
            denom = a - 2 * b + c
            off = 0.5 * (a - c) / denom if denom else 0.0
        else:
            off = 0.0
        bpm = 60.0 * fr / (best + off)
        confident = ac[best] > 0.15 * ac[0]
        if confident:
            self.bpm_votes.append(bpm)
        with self._lock:
            if self.bpm_votes:
                self.state.bpm = float(np.median(self.bpm_votes))
            self.state.bpm_confident = bool(confident)
