"""Rozpoznanie štýlu hudby a fázy skladby v reálnom čase (len numpy, beží aj na Pi 3B+).

Žáner sa odhaduje pravidlami nad rytmickým profilom, nie neurónovou sieťou:
- **rytmický profil**: kde v 2-beatovom cykle (8 šestnástin) padá kick, snare a hi-hat,
- **tempo** aj s polovičným/dvojnásobným výkladom (DnB 174 = 87 half-time),
- **farba zvuku** (spektrálny centroid), podiel basy, hustota a sila kickov.

Typické znaky (djclass.net, ISMIR literatúra):
  house   118–130 BPM, four-on-the-floor, offbeat hi-hat
  techno  125–150 BPM, four-on-the-floor, tmavší zvuk, 16-ky hi-hat
  dnb     160–180 BPM, breakbeat (kick nie na každej dobe), snare 2 a 4, silná basa
  hiphop   70–100 BPM, synkopovaný kick, snare 2 a 4 (trap ~140 half-time)
  chill   pomalé, slabé/riedke kicky, nízka energia
  party   pop/rock a všetko ostatné (backbeat bez four-on-the-floor)

Fáza skladby (ako rekordbox Phrase / MaestroDMX energia): main, breakdown, build, drop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

STYLES = ("party", "dnb", "techno", "house", "hiphop", "chill")
STYLE_NAMES = {"party": "Pop / party", "dnb": "Drum & Bass", "techno": "Techno",
               "house": "House", "hiphop": "Hip-hop", "chill": "Chill"}
SECTIONS = ("main", "breakdown", "build", "drop")


def trap(x: float, a: float, b: float, c: float, d: float) -> float:
    """Lichobežníková príslušnosť: 0 pod a, 1 medzi b a c, 0 nad d."""
    if x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    return (x - a) / (b - a) if x < b else (d - x) / (d - c)


@dataclass
class RhythmFeatures:
    bpm: float = 0.0
    four_floor: float = 0.0     # kick na každej dobe (0–1)
    syncopation: float = 0.0    # kick mimo dôb
    backbeat: float = 0.0       # snare na každej druhej dobe
    offbeat_hat: float = 0.0    # hi-hat na osminovej „a“
    hat_density: float = 0.0    # koľko šestnástin má hi-hat
    centroid: float = 0.0       # Hz, „jas“ zvuku
    sub_ratio: float = 0.0      # podiel basy v energii
    kick_rate: float = 0.0      # kicky za dobu
    hit_rate: float = 0.0       # bicie údery za sekundu (nezávislé od oktávy tempa)
    intensity: float = 0.0      # sila × hustota kickov
    energy: float = 0.0         # dlhodobá hlasitosť 0–1
    ready: bool = False

    def as_dict(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v for k, v in self.__dict__.items()}


class RhythmProfile:
    """Akumuluje flux kick/snare/hat do 8 binov (šestnástiny) 2-beatového cyklu."""

    BINS = 8

    def __init__(self, memory_s: float = 24.0):
        self.memory_s = memory_s
        self.k = np.zeros(self.BINS)
        self.s = np.zeros(self.BINS)
        self.h = np.zeros(self.BINS)
        self.centroid = 0.0
        self.sub = 0.0
        self.kick_rate = 0.0
        self.strength = 0.0
        self.energy = 0.0
        self.hit_rate = 0.0
        # miery (údery/dobu, údery/s) ako podiel tlmených súčtov – bez rozbehu od nuly
        self._kicks_n = self._beats_n = self._hits_n = self._time_n = 0.0
        self._was_hit = False
        self._last_hit = -1.0
        self.time = 0.0

    def add(self, pos2: float, kick: float, snare: float, hat: float, centroid: float,
            sub: float, level: float, dt: float, onset: bool, onset_strength: float,
            bpm: float, silent: bool) -> None:
        if silent:
            return
        d = math.exp(-dt / self.memory_s)
        self.k *= d
        self.s *= d
        self.h *= d
        i = int(pos2 * 4 + 0.5) % self.BINS   # najbližšia šestnástina
        self.k[i] += kick
        self.s[i] += snare
        self.h[i] += hat
        a = 1 - d
        self.centroid += (centroid - self.centroid) * a
        self.sub += (sub - self.sub) * a
        self.energy += (level - self.energy) * a
        r = math.exp(-dt / 10.0)
        self._kicks_n = self._kicks_n * r + (1.0 if onset else 0.0)
        self._beats_n = self._beats_n * r + dt * bpm / 60.0
        self.kick_rate = self._kicks_n / max(self._beats_n, 1e-6)
        if onset:
            self.strength += (onset_strength - self.strength) * 0.05
        # hustota úderov: nábežná hrana kick/snare/hat, refraktérne 60 ms
        hit = onset or snare > 0 or hat > 0
        counted = hit and not self._was_hit and self.time - self._last_hit > 0.06
        if counted:
            self._last_hit = self.time
        self._was_hit = hit
        self._hits_n = self._hits_n * r + (1.0 if counted else 0.0)
        self._time_n = self._time_n * r + dt
        self.hit_rate = self._hits_n / max(self._time_n, 1e-6)
        self.time += dt

    def features(self, bpm: float) -> RhythmFeatures:
        f = RhythmFeatures(bpm=bpm)
        ks, ss, hs = self.k.sum(), self.s.sum(), self.h.sum()
        if self.time < 8.0 or ks <= 1e-6:
            return f
        k, s, h = self.k / ks, self.s / max(ss, 1e-9), self.h / max(hs, 1e-9)
        # tolerancia ±1 šestnástina pri dobe (jitter fázy)
        beat_a = k[0] + 0.5 * (k[1] + k[7])
        beat_b = k[4] + 0.5 * (k[3] + k[5])
        on_beats = beat_a + beat_b
        balance = min(beat_a, beat_b) / max(beat_a, beat_b, 1e-9)
        f.four_floor = float(min(1.0, on_beats) * balance)
        f.syncopation = float(k[2] + k[6] + 0.5 * (k[1] + k[3] + k[5] + k[7]))
        sa = s[0] + 0.5 * (s[1] + s[7])
        sb = s[4] + 0.5 * (s[3] + s[5])
        f.backbeat = float(abs(sa - sb) / max(sa + sb, 1e-9) * min(1.0, sa + sb)) if ss > 1e-6 else 0.0
        f.offbeat_hat = float(h[2] + h[6]) if hs > 1e-6 else 0.0
        f.hat_density = float(np.mean(h > 0.06)) if hs > 1e-6 else 0.0
        f.centroid = float(self.centroid)
        f.sub_ratio = float(self.sub)
        f.kick_rate = float(self.kick_rate)
        f.hit_rate = float(self.hit_rate)
        f.intensity = float(min(1.0, self.kick_rate) * self.strength)
        f.energy = float(self.energy)
        f.ready = True
        return f


def style_scores(f: RhythmFeatures) -> dict[str, float]:
    """Skóre 0–1 pre každý štýl (fuzzy pravidlá)."""
    if not f.ready:
        return {s: 0.0 for s in STYLES}
    bpm = f.bpm
    half, dbl = bpm / 2, bpm * 2
    ff, nff = f.four_floor, 1 - f.four_floor
    dark = trap(f.centroid, 0, 0, 2200, 3600)
    bright = 1 - dark

    t_dnb = max(trap(bpm, 155, 164, 182, 192), trap(dbl, 155, 164, 182, 192))
    # hustota úderov za sekundu nezávisí od toho, či tempo čítame 87 alebo 174
    busy = trap(f.hit_rate, 3.8, 4.8, 40, 50)
    calm = trap(f.hit_rate, -1, 0, 2.6, 3.4)
    t_techno = trap(bpm, 120, 126, 152, 162)
    t_house = trap(bpm, 110, 117, 130, 135)
    t_hiphop = max(trap(bpm, 62, 70, 100, 108), 0.8 * trap(half, 62, 68, 78, 84))
    t_chill = trap(bpm, 55, 65, 112, 124)
    t_party = trap(bpm, 92, 100, 140, 150)

    scores = {
        # pri half-time čítaní (87) vyzerá breakbeat ako kick na 1 a 3 → four-floor neplatí
        "dnb": t_dnb * busy * (nff if bpm >= 130 else 1.0) * (0.5 + 0.5 * f.backbeat) * (0.6 + 0.4 * min(1, f.sub_ratio * 3)),
        "techno": t_techno * ff * (0.45 + 0.55 * (1 - f.offbeat_hat)) * (0.55 + 0.45 * dark),
        "house": t_house * ff * (0.3 + 0.7 * f.offbeat_hat),
        "hiphop": t_hiphop * nff * (0.35 + 0.65 * f.backbeat) * trap(f.kick_rate, 0.25, 0.4, 2.0, 3.0)
                  * (1 - 0.6 * busy),
        "chill": t_chill * calm * trap(f.kick_rate, -1, 0, 0.3, 0.6) * (0.6 + 0.4 * nff),
        "party": t_party * nff * (0.3 + 0.7 * f.backbeat) * (0.6 + 0.4 * bright) * 0.85,
    }
    return {k: float(round(v, 3)) for k, v in scores.items()}


class StyleClassifier:
    """Vyberie štýl s hysterézou, aby svetlá neskákali medzi štýlmi."""

    def __init__(self, hold_s: float = 8.0, margin: float = 0.05, min_score: float = 0.15):
        self.hold_s, self.margin, self.min_score = hold_s, margin, min_score
        self.current = "party"
        self.confidence = 0.0
        self.scores: dict[str, float] = {s: 0.0 for s in STYLES}
        self._cand: str | None = None
        self._cand_since = 0.0
        self._decided = False       # prvé rozhodnutie rýchlejšie (3 s), potom hold_s

    def update(self, t: float, f: RhythmFeatures) -> str:
        self.scores = style_scores(f)
        best = max(self.scores, key=self.scores.get)
        total = sum(self.scores.values()) or 1.0
        top = self.scores[best]
        if top < self.min_score:
            best = self.current
        elif best == self.current:
            self._decided = True
        if best != self.current and top >= self.scores[self.current] + self.margin:
            if self._cand != best:
                self._cand, self._cand_since = best, t
            elif t - self._cand_since >= (self.hold_s if self._decided else 3.0):
                self.current, self._cand, self._decided = best, None, True
        else:
            self._cand = None
        self.confidence = float(self.scores[self.current] / total) if total else 0.0
        return self.current


class SectionTracker:
    """Fáza skladby podľa energie: main / breakdown / build / drop.

    breakdown = hlasitosť a kicky výrazne pod dlhodobým priemerom
    build     = po breakdowne rastú výšky/hustota (snare roll, riser)
    drop      = návrat plnej energie s kickom; drží 8 dôb
    """

    def __init__(self):
        self.short = 0.0        # ~1 takt
        self.long = 0.0         # ~20 s
        self.high_short = 0.0
        self.high_slow = 0.0
        self.kicks = 0.0
        self.section = "main"
        self.since = 0.0
        self.drop_count = 0
        self.build_progress = 0.0
        self._drop_until_beat = -1.0
        self._last_kick_t = -1e9
        self._calm_min = 1e9    # najnižšia energia počas breakdownu (build = rast od nej)

    def update(self, t: float, dt: float, level: float, high: float, onset: bool,
               beats: float, bpm: float, silent: bool) -> str:
        a_s = 1 - math.exp(-dt / 1.5)
        a_l = 1 - math.exp(-dt / 20.0)
        self.short += (level - self.short) * a_s
        self.long += (level - self.long) * a_l
        self.high_short += (high - self.high_short) * a_s
        self.high_slow += (high - self.high_slow) * (1 - math.exp(-dt / 6.0))
        beat_dt = dt * bpm / 60.0
        self.kicks += ((1.0 / max(beat_dt, 1e-6) if onset else 0.0) - self.kicks) * (1 - math.exp(-dt / 2.0))
        if onset:
            self._last_kick_t = t
        no_kick = t - self._last_kick_t > 2.0

        prev = self.section
        calm = prev in ("breakdown", "build")
        if silent or t < 6.0:          # začiatok skladby: najprv sa naučiť úroveň
            new = "main"
        elif calm and onset and t - self.since >= 4.0:
            # kick sa vrátil po aspoň 4 s pokoja = drop (svetlá udrú hneď na prvý úder)
            new = "drop"
            self.drop_count += 1
            self._drop_until_beat = beats + 8
        elif prev == "drop" and beats < self._drop_until_beat:
            new = "drop"
        elif no_kick or self.short < self.long * 0.6:
            self._calm_min = min(self._calm_min, self.short) if calm else self.short
            rising = self.high_short > self.high_slow * 1.15 or self.short > self._calm_min * 1.5
            new = "build" if calm and (rising or prev == "build") else "breakdown"
        else:
            new = "main"
        if new != prev and not (prev in ("breakdown", "build") and new in ("breakdown", "build")):
            self.since = t
        self.section = new
        if new == "build":
            self.build_progress = min(1.0, self.build_progress + dt / 16.0)
        else:
            self.build_progress = 0.0
        return new


@dataclass
class MusicInfo:
    style: str = "party"
    style_confidence: float = 0.0
    scores: dict = field(default_factory=dict)
    section: str = "main"
    drop_count: int = 0
    build_progress: float = 0.0
    features: dict = field(default_factory=dict)


class MusicAnalyzer:
    """Spája rytmický profil, klasifikátor štýlu a fázy skladby."""

    def __init__(self):
        self.profile = RhythmProfile()
        self.classifier = StyleClassifier()
        self.sections = SectionTracker()
        self.info = MusicInfo()
        self._next_classify = 0.0

    def update(self, t: float, dt: float, *, pos2: float, beats: float, bpm: float,
               kick: float, snare: float, hat: float, centroid: float, sub: float,
               level: float, high: float, onset: bool, onset_strength: float,
               silent: bool) -> MusicInfo:
        self.profile.add(pos2, kick, snare, hat, centroid, sub, level, dt, onset,
                         onset_strength, bpm, silent)
        self.sections.update(t, dt, level, high, onset, beats, bpm, silent)
        if t >= self._next_classify:
            self._next_classify = t + 1.0
            f = self.profile.features(bpm)
            self.classifier.update(t, f)
            self.info.features = f.as_dict()
        self.info.style = self.classifier.current
        self.info.style_confidence = round(self.classifier.confidence, 3)
        self.info.scores = self.classifier.scores
        self.info.section = self.sections.section
        self.info.drop_count = self.sections.drop_count
        self.info.build_progress = round(self.sections.build_progress, 3)
        return self.info
