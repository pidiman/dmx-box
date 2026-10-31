"""Dymostroj: ručné tlačidlo, auto výstrek na vrchole a ochrana ohrievača.

Pravidlá:
- jeden výstrek trvá najviac `max_burst_s` (aj pri držaní tlačidla),
- po výstreku je povinná pauza `cooldown_s` (ohrievač, zadymená miestnosť),
- auto výstrek (`fog_auto`) príde, keď hudba po tichšej časti nabehne naplno (drop).
"""

from __future__ import annotations

from dataclasses import dataclass

from .audio import AudioState


@dataclass
class FogStatus:
    on: bool = False
    ready: bool = True
    cooldown_left: float = 0.0
    reason: str = ""


class FogController:
    def __init__(self, max_burst_s: float = 10.0, cooldown_s: float = 30.0):
        self.max_burst_s = max_burst_s
        self.cooldown_s = cooldown_s
        self._start: float | None = None
        self._until: float = 0.0         # koniec aktuálneho výstreku
        self._ready_at: float = 0.0      # kedy je povolený ďalší výstrek
        self._energy = 0.0               # pomalá obálka hlasitosti (na detekciu dropu)
        self._was_hold = False
        self.status = FogStatus()

    def _begin(self, now: float, length: float, reason: str) -> None:
        self._start = now
        self._until = now + min(length, self.max_burst_s)
        self.status.reason = reason

    def _end(self, now: float) -> None:
        if self._start is not None:
            self._ready_at = now + self.cooldown_s
        self._start = None

    def update(self, now: float, a: AudioState, hold: bool, auto: bool,
               burst_s: float, blackout: bool) -> bool:
        """Vráti True, ak má dym práve ísť."""
        loud = 0.5 * a.level + 0.5 * a.bass
        drop = (not a.silent and loud > 0.8 and self._energy < 0.45)
        self._energy += (loud - self._energy) * 0.01   # ~2,5 s pri 40 fps

        ready = now >= self._ready_at
        if blackout:
            self._end(now)
        elif self._start is not None:
            # beží výstrek: koniec pri uplynutí času, alebo pustení tlačidla
            if now >= self._until or (self.status.reason == "hold" and not hold):
                self._end(now)
        elif ready:
            if hold and not self._was_hold:
                self._begin(now, self.max_burst_s, "hold")
            elif auto and drop:
                self._begin(now, burst_s, "auto")
        self._was_hold = hold

        on = self._start is not None
        self.status.on = on
        self.status.ready = not on and now >= self._ready_at
        self.status.cooldown_left = max(0.0, self._ready_at - now) if not on else 0.0
        return on
