"""Svetelné štýly podľa žánru + úprava podľa fázy skladby.

Inšpirácia (rešerš):
- rekordbox Lighting: svetelné scény podľa fráz (intro / up / down / chorus) – my podobne
  podľa fázy main / breakdown / build / drop,
- MaestroDMX: farebné palety a pohyb podľa nálady/energie,
- praktické rady pre EDM light show: breakdown = pokoj, tlmené statické farby;
  build = postupne zrýchľovať (nie stroboskop na každý úder); drop = udrieť na prvý úder,
  stroboskop krátko.

Každý štýl hovorí, ktoré dvojice FX (farby, pohyb) auto mód strieda, akú paletu použiť
a čo sa smie (laser, UV, stroboskop/dym na drop).
"""

from __future__ import annotations

from dataclasses import dataclass

from .genre import STYLE_NAMES, STYLES

Pair = tuple[str, str]


@dataclass(frozen=True)
class StyleLook:
    key: str
    palette: str
    sets: list[Pair]                    # main: striedanie každých `auto_bars` taktov
    calm: Pair                          # breakdown
    build: Pair                         # build-up
    drop: Pair                          # prvých 8 dôb po drope
    fade_bias: float = 0.0              # + mäkšie / − tvrdšie prechody
    size_k: float = 1.0                 # rozsah pohybu
    pt_slow: float = 0.0                # min. pomalosť pan/tilt (0 = bez obmedzenia)
    laser: bool = True
    uv: bool = True
    derby: bool = True
    strobe_drop: bool = True            # krátke strobo na začiatku dropu
    fog_drop: bool = True               # dym na drop (ak je zapnutý auto dym)
    bars: int = 16                      # po koľkých taktoch meniť dvojicu


LOOKS: dict[str, StyleLook] = {
    # DnB: rýchle, ostré, červeno-oranžové; pohyb na takty, nie na každý úder (174 BPM)
    "dnb": StyleLook(
        "dnb", "fire",
        sets=[("kick_flash", "snap"), ("split", "tilt_bounce"), ("beat_chase", "sweep"),
              ("derby_party", "snap")],
        calm=("bass_pump", "audience"), build=("build_up", "sweep"), drop=("kick_flash", "snap"),
        fade_bias=-0.2, size_k=1.0, bars=8),
    # Techno: chladné biele/modré, minimalistické, stroboskop a laser
    "techno": StyleLook(
        "techno", "ice",
        sets=[("beat_chase", "sweep"), ("kick_flash", "tilt_bounce"), ("color_step", "jump"),
              ("build_up", "sweep")],
        calm=("bass_pump", "hold"), build=("build_up", "tilt_bounce"), drop=("kick_flash", "jump"),
        fade_bias=-0.15, size_k=0.8, derby=False, bars=16),
    # House: teplé farby, groove, derby, plynulejší pohyb
    "house": StyleLook(
        "house", "warm",
        sets=[("bass_pump", "sweep"), ("derby_party", "circle_slow"), ("color_step", "audience"),
              ("split", "tilt_bounce")],
        calm=("rainbow", "circle_slow"), build=("build_up", "sweep"), drop=("derby_party", "jump"),
        fade_bias=0.1, size_k=0.9, bars=16),
    # Hip-hop: fialová/zlatá, údery na kick (synkopy), pomalší pohyb, bez lasera
    "hiphop": StyleLook(
        "hiphop", "urban",
        sets=[("kick_flash", "gobo_beat"), ("color_step", "audience"), ("bass_pump", "jump"),
              ("split", "gobo_beat")],
        calm=("bass_pump", "audience"), build=("color_step", "sweep"), drop=("kick_flash", "jump"),
        fade_bias=0.0, size_k=0.7, pt_slow=0.3, laser=False, fog_drop=False, bars=8),
    # Chill: pomalé dúhové prechody, žiadne strobo ani dym
    "chill": StyleLook(
        "chill", "cool",
        sets=[("rainbow", "circle_slow"), ("split", "audience"), ("bass_pump", "hold")],
        calm=("rainbow", "hold"), build=("rainbow", "circle_slow"), drop=("split", "circle_slow"),
        fade_bias=0.35, size_k=0.6, pt_slow=0.6, laser=False, derby=False,
        strobe_drop=False, fog_drop=False, bars=32),
    # Pop/party: pestré, všetko povolené – pôvodný auto mód
    "party": StyleLook(
        "party", "party",
        sets=[("beat_chase", "jump"), ("split", "sweep"), ("bass_pump", "tilt_bounce"),
              ("derby_party", "snap"), ("color_step", "gobo_beat"), ("kick_flash", "jump")],
        calm=("rainbow", "circle_slow"), build=("build_up", "sweep"), drop=("derby_party", "jump"),
        bars=16),
}

assert set(LOOKS) == set(STYLES)

STYLE_CHOICES = ("auto",) + STYLES     # nastavenie `style`: auto = podľa rozpoznania


def look_for(key: str) -> StyleLook:
    return LOOKS.get(key, LOOKS["party"])


def catalog() -> list[dict]:
    return [{"key": k, "name": STYLE_NAMES[k], "palette": LOOKS[k].palette} for k in STYLES]
