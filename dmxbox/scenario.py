"""Scenáre: ako sa dnes púšťa hudba. Jedno ťuknutie nastaví vstup, výstup zvuku a svetlá.

Posledný použitý scenár sa ukladá do scenario.json, vstupná obrazovka ho ponúkne
ako „Ako minule“.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import system
from .genre import STYLES
from .system import CmdError

log = logging.getLogger("dmxbox.scenario")

SCENARIOS = [
    {"id": "bt", "name": "Bluetooth z mobilu",
     "desc": "Pustíš z akejkoľvek appky (Spotify, YouTube…). Box hrá do reproduktora a svetlá idú do rytmu.",
     "tags": ["Bez internetu", "Akákoľvek appka"]},
    {"id": "airplay", "name": "AirPlay z iPhonu / iPadu",
     "desc": "Z akejkoľvek appky cez Wi-Fi: v Ovládacom centre vyber AirPlay → box. Bez sekania Bluetooth, s názvom skladby.",
     "tags": ["Wi-Fi", "Apple", "Bezstratovo"]},
    {"id": "spotify", "name": "Spotify Connect",
     "desc": "Box si hudbu sťahuje sám, mobil je len ovládač. Hovory ani notifikácie hudbu neprerušia.",
     "tags": ["Wi-Fi s internetom", "Premium"],
     "warn": "S novšími Spotify účtami zatiaľ nefunguje."},
    {"id": "linein", "name": "Kábel z DJ pultu alebo PC",
     "desc": "Hudba ide káblom do vstupu zvukovej karty UCA202. Najmenšie oneskorenie.",
     "tags": ["Line-in", "Bez oneskorenia"]},
    {"id": "btspeaker", "name": "Bluetooth reproduktor",
     "desc": "Hudba cez Spotify alebo kábel, zvuk ide do BT reproduktora. Svetlá sa oneskoria, aby sedeli.",
     "tags": ["Light delay"]},
    {"id": "ambient", "name": "Svetlá bez hudby",
     "desc": "Pokojné farebné scény na večeru alebo ako dekorácia. Bez stroboskopu, lasera a dymu.",
     "tags": ["Ambient", "Ticho"]},
    {"id": "demo", "name": "Demo",
     "desc": "Simulovaný DJ set so striedaním žánrov, breakdownom a dropom. Na vyskúšanie svetiel.",
     "tags": ["Bez hudby", "Test"]},
]
IDS = {s["id"] for s in SCENARIOS}


class ScenarioStore:
    def __init__(self, path: Path):
        self.path = path
        self.current: dict | None = None
        try:
            self.last: dict | None = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.last = None

    def save(self, data: dict) -> None:
        self.current = self.last = data
        try:
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning("scenario.json: %s", e)


def summary(data: dict | None) -> str:
    """Krátky popis pre tlačidlo „Ako minule“."""
    if not data:
        return ""
    name = next((s["name"] for s in SCENARIOS if s["id"] == data.get("id")), data.get("id", ""))
    style = data.get("style", "auto")
    return f"{name} · svetlá {'AUTO' if style == 'auto' else style}"


def apply(box, data: dict) -> dict:
    """Nastaví box podľa scenára. Chyby jednotlivých krokov vráti ako varovania."""
    sid = data.get("id")
    if sid not in IDS:
        raise CmdError("neznámy scenár")
    style = data.get("style", "auto")
    if style not in ("auto",) + STYLES:
        raise CmdError("neznámy štýl")
    warnings: list[str] = []

    def step(label: str, fn, *args) -> None:
        try:
            fn(*args)
        except CmdError as e:
            warnings.append(f"{label}: {e}")

    source = data.get("source") or ("linein" if sid == "linein" else "spotify")
    line_in = sid == "linein" or (sid == "btspeaker" and source == "linein")
    want_spotify = sid == "spotify" or (sid == "btspeaker" and source == "spotify")

    if sid == "btspeaker" and not data.get("output"):
        try:
            bt = [x["name"] for x in system.audio_status()["sinks"] if x["kind"] == "bluetooth"]
        except CmdError:
            bt = []
        if bt:
            data = {**data, "output": bt[0]}
        else:
            warnings.append("BT reproduktor nie je pripojený – zvuk ide na doterajší výstup")
    if data.get("output"):
        step("Výstup zvuku", system.audio_output, data["output"])
    if want_spotify:
        step("Spotify", system.spotify_set, True)
    if sid == "bt":
        step("Bluetooth", system.bt_discoverable, True)
    if sid == "airplay":
        step("AirPlay", system.airplay_set, True)
    if data.get("volume") is not None:
        step("Hlasitosť", system.audio_volume, int(data["volume"]))

    delay = int(data.get("delay_ms", 200 if sid == "btspeaker" else 0))
    box.line_in.set(False)          # loopback na nový výstup
    if line_in and not box.line_in.set(True):
        warnings.append("Line-in: vstup UCA202 nenájdený")

    upd = {"auto": True, "style": style, "ambient": sid == "ambient", "line_in": line_in,
           "light_delay_ms": max(0, min(500, delay)), "blackout": False, "manual_color": None}
    for k in ("laser", "fog_auto"):
        if k in data:
            upd[k] = bool(data[k])
    box.store.update(**upd)

    # zdroj zvuku: demo = simulácia, inak monitor predvoleného výstupu (znova ho vyhľadá)
    if box.sources:
        if sid == "demo":
            box.analyzer.switch_source(box.sources["demo"](), realtime=True)
        else:
            box.analyzer.switch_source(box.sources["live"](), realtime=box.sources.get("live_realtime", False))

    saved = {k: data[k] for k in ("id", "style", "output", "source", "laser", "fog_auto",
                                  "delay_ms", "volume") if k in data}
    box.scenarios.save(saved)
    log.info("scenár %s (%s), varovania: %s", sid, style, warnings or "žiadne")
    return {"ok": True, "warnings": warnings, "scenario": saved}
