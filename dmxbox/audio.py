"""Audio analýza: pásma, onsety (spectral flux), BPM a fáza beatu.

Vstup je mono float32 stream po blokoch `hop` vzoriek – na Pi z `parec`
(monitor výstupného sinku), v testoch zo simulátora. Len numpy, bez aubio.
"""

from __future__ import annotations

import collections
import math
import copy
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

from .genre import MusicAnalyzer

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
    # štýl a fáza skladby (genre.py)
    style: str = "party"
    style_confidence: float = 0.0
    style_scores: dict = field(default_factory=dict)
    section: str = "main"       # main | breakdown | build | drop
    drop_count: int = 0
    build_progress: float = 0.0
    features: dict = field(default_factory=dict)
    # vizualizácia v appke: 24 pásiem (basy → výšky) pre ľavý a pravý kanál, 0–1
    viz_l: list = field(default_factory=list)
    viz_r: list = field(default_factory=list)

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
    """Nekonečný generátor stereo blokov (hop × 2) z parec. Pri páde ho znova spustí."""
    if not shutil.which("parec"):
        raise RuntimeError("parec nenájdený (apt install pulseaudio-utils)")
    bytes_per_block = hop * 4 * 2
    while True:
        dev = default_monitor() if device == "auto" else device
        cmd = ["parec", "-d", dev, "--format=float32le", f"--rate={rate}",
               "--channels=2", "--latency-msec=20"]
        log.info("audio: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                raw = proc.stdout.read(bytes_per_block)
                if not raw or len(raw) < bytes_per_block:
                    break
                yield np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
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


# --- vizualizácia -------------------------------------------------------------

class StereoViz:
    """Spektrum pre appku: 24 logaritmických pásiem 40 Hz – 16 kHz pre L aj R.

    Počíta sa len každý `every`-tý blok (~29×/s), stačí to na plynulú animáciu a šetrí Pi.
    Hodnoty sú v dB vzhľadom na pomaly klesajúce maximum, takže sedia pri tichej aj hlasnej hudbe.
    """

    def __init__(self, rate: int, fft: int = 1024, bands: int = 24, every: int = 3):
        self.fft, self.every, self.n = fft, every, 0
        self.window = np.hanning(fft).astype(np.float32)
        freqs = np.fft.rfftfreq(fft, 1.0 / rate)
        edges = np.geomspace(40, min(16000, rate / 2 - 1), bands + 1)
        self.idx = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            sel = np.nonzero((freqs >= lo) & (freqs < hi))[0]
            if not len(sel):                       # úzke basové pásma: najbližší bin
                sel = np.array([int(np.argmin(np.abs(freqs - (lo + hi) / 2)))])
            self.idx.append(sel)
        self.buf = np.zeros((fft, 2), dtype=np.float32)
        self.peak = -20.0
        self.l = np.zeros(bands)
        self.r = np.zeros(bands)

    def _bands(self, x: np.ndarray) -> np.ndarray:
        mag = np.abs(np.fft.rfft(x * self.window))
        return np.array([20 * np.log10(mag[i].mean() + 1e-9) for i in self.idx])

    def process(self, stereo: np.ndarray) -> None:
        n = len(stereo)
        self.buf = np.concatenate((self.buf[n:], stereo.astype(np.float32)))
        self.n += 1
        if self.n % self.every:
            return
        dl, dr = self._bands(self.buf[:, 0]), self._bands(self.buf[:, 1])
        top = max(float(dl.max()), float(dr.max()))
        self.peak = max(top, self.peak - 0.15)       # ~4 dB/s dolu
        rng = 45.0                                    # zobrazený rozsah v dB
        nl = np.clip((dl - (self.peak - rng)) / rng, 0, 1)
        nr = np.clip((dr - (self.peak - rng)) / rng, 0, 1)
        self.l = np.maximum(nl, self.l * 0.8)        # rýchly nábeh, plynulý pokles
        self.r = np.maximum(nr, self.r * 0.8)


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
            "kick": (freqs >= 30) & (freqs < 115),   # úzko: snare/tom presakuje do 130+ Hz
            "bass": (freqs >= 20) & (freqs < 150),
            "mid": (freqs >= 150) & (freqs < 2000),
            "high": (freqs >= 2000) & (freqs < 16000),
            "snare": (freqs >= 150) & (freqs < 1000),   # telo snare/clapu; hi-haty sú vyššie
            "hat": (freqs >= 6000) & (freqs < 16000),
        }
        self.freqs = freqs
        self.music = MusicAnalyzer()
        self.buf = np.zeros(fft, dtype=np.float32)
        self.viz = StereoViz(rate, fft)
        self.prev_mag: np.ndarray | None = None
        self.prev_lin: np.ndarray | None = None
        self._kick_lin_peak = 1e-6   # lineárny flux basy: kick vs. presak snare (log flux ich zrovná)

        hist = int(self.frame_rate * 8)     # 8 s histórie onset krivky
        self.flux_hist: collections.deque[float] = collections.deque(maxlen=hist)
        self.kick_hist: collections.deque[float] = collections.deque(maxlen=int(self.frame_rate))
        self.snare_hist: collections.deque[float] = collections.deque(maxlen=int(self.frame_rate))
        self.hat_hist: collections.deque[float] = collections.deque(maxlen=int(self.frame_rate))
        self._mean_kick = 1e-3
        self._band_peak = {"snare": 1e-3, "hat": 1e-3}
        self._kick_peak = 1e-3      # pomaly klesajúce maximum kick fluxu (brána proti šumu)
        self._mean_flux = 1e-3
        self._mean_snare = 1e-3
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
        self._pending_source: tuple[Iterator[np.ndarray], bool] | None = None

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
    def switch_source(self, source: Iterator[np.ndarray], realtime: bool = False) -> None:
        """Vymení zdroj zvuku za behu (scenár: demo, iný výstup → nový monitor)."""
        self._pending_source = (source, realtime)

    def run(self) -> None:
        period = self.hop / self.rate
        while not self._halt.is_set():
            t0, f0 = time.monotonic(), self._frames
            src = self.source
            for block in src:
                if self._halt.is_set() or self._pending_source is not None:
                    break
                self.process(block)
                if self.realtime:
                    sleep = t0 + (self._frames - f0) * period - time.monotonic()
                    if sleep > 0:
                        time.sleep(sleep)
            if self._pending_source is None:
                break            # zdroj skončil (testy, konečná simulácia)
            self.source, self.realtime = self._pending_source
            self._pending_source = None
            close = getattr(src, "close", None)
            if close:
                close()          # ukončí parec (finally v generátore)
            log.info("audio: zdroj vymenený")

    def process(self, block: np.ndarray) -> None:
        if block.ndim == 2:                  # stereo: vizualizácia L/R, analýza z mixu
            self.viz.process(block)
            block = block.mean(axis=1)
        else:
            self.viz.process(np.repeat(block[:, None], 2, axis=1))
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
        km = self.bands["kick"]
        lin = mag[km]
        kick_lin = float(np.sum(np.maximum(lin - self.prev_lin, 0.0))) if self.prev_lin is not None else 0.0
        self.prev_lin = lin
        self._kick_lin_peak = max(kick_lin, self._kick_lin_peak * math.exp(-dt / 10.0))
        kick = float(np.sum(diff[self.bands["kick"]]))
        snare_f = float(np.sum(diff[self.bands["snare"]]))
        hat_f = float(np.sum(diff[self.bands["hat"]]))
        p = mag ** 2
        total_e = float(p.sum()) + 1e-12
        centroid = float((self.freqs * p).sum() / total_e)
        sub = energies["bass"] * self.bands["bass"].sum() / total_e
        # krivka pre tempo: hlavne kick (16-kové hi-haty inak ťahajú tempo mimo)
        self._mean_kick += (kick - self._mean_kick) * 0.002
        self._mean_flux += (flux - self._mean_flux) * 0.002
        self._mean_snare += (snare_f - self._mean_snare) * 0.002
        kick_rel = kick / (self._mean_kick + 1e-9)
        snare_rel = snare_f / (self._mean_snare + 1e-9)
        self.flux_hist.append(kick_rel + 0.6 * snare_rel + 0.3 * flux / (self._mean_flux + 1e-9))
        self.kick_hist.append(kick)
        self.snare_hist.append(snare_f)
        self.hat_hist.append(hat_f)

        def peak(x: float, hist, key: str) -> float:
            """Len výrazné údery: nad lokálnou úrovňou pásma aj nad 30 % jeho nedávneho maxima (nie šum)."""
            self._band_peak[key] = max(x, self._band_peak[key] * math.exp(-dt / 10.0))
            if len(hist) < 10 or x < 0.3 * self._band_peak[key]:
                return 0.0
            arr = np.fromiter(hist, dtype=np.float64)
            thr = float(np.median(arr) + 1.2 * np.std(arr))
            return max(0.0, x - thr)

        snare_pk = peak(snare_f, self.snare_hist, "snare")
        hat_pk = peak(hat_f, self.hat_hist, "hat")

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
            self._kick_peak = max(kick, self._kick_peak * math.exp(-dt / 10.0))
            if kick > thr and kick > 0.3 * self._kick_peak and t - self._last_onset_t > 0.12:
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
            pos2 = (s.beat_count % 2) + s.beat_phase
            beats_now = s.beat_count + s.beat_phase
            bpm_now = self._override_bpm or s.bpm
        # do rytmického profilu len údery, kde prevláda basové pásmo (nie snare)
        kick_hit = onset and kick_lin > 0.45 * self._kick_lin_peak
        # snare do profilu len ak v tej chvíli nebije kick (klik kicku presakuje do stredov)
        if kick_lin > 0.2 * self._kick_lin_peak:
            snare_pk = 0.0
        info = self.music.update(t, dt, pos2=pos2, beats=beats_now, bpm=bpm_now,
                                 kick=strength if kick_hit else 0.0, snare=snare_pk, hat=hat_pk, centroid=centroid, sub=sub,
                                 level=vals["level"], high=vals["high"], onset=kick_hit,
                                 onset_strength=strength, silent=silent)
        with self._lock:
            s.viz_l, s.viz_r = self.viz.l.tolist(), self.viz.r.tolist()
            s.style, s.style_confidence = info.style, info.style_confidence
            s.style_scores = dict(info.scores)
            s.section, s.drop_count = info.section, info.drop_count
            s.build_progress = info.build_progress
            s.features = info.features

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
        for mult in (2, 4):          # párne metrum (4/4) – trojnásobky by ťahali na 4/3 tempa
            for j, lag in enumerate(lags):
                c = lag * mult
                if c + mult < len(ac):   # okno ±mult snímok: úzke špičky sa pri zaokrúhlení lagu strácajú
                    score[j] += ac[c - mult:c + mult + 1].max() * 0.5
        # prior okolo 120 BPM (Ellis 2007) – rieši half/double nejednoznačnosť
        bpms = 60.0 * fr / lags
        prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 1.4) ** 2)
        score = np.where(score > 0, score * prior, score)
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
