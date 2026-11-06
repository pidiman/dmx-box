"""Spustenie DMX-BOX: audio vlákno, engine, DMX výstup, web server.

python3 -m dmxbox.main              # produkcia na Pi
python3 -m dmxbox.main --sim --dry  # simulovaná hudba, DMX naprázdno
"""

from __future__ import annotations

import argparse
import logging
import time
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import uvicorn

from .airplay_keep import AirplayKeep
from .api import create_app
from .auth import Auth
from .audio import Analyzer, device_source, list_inputs, parec_source
from .audio_ctl import LineIn
from .btspeaker import SpeakerWatch
from .config import load_config, resolve
from .dmx_out import DMXOut
from .engine import Engine
from .fixtures import RigStore
from .nowplaying import NowPlaying
from .player import Player
from .scenario import ScenarioStore
from .sessionlog import LogHandler, SessionLog
from .sim import GENRES, mix_source, synth_source
from .state import Settings, Store


@dataclass
class Box:
    store: Store
    analyzer: Analyzer
    engine: Engine
    out: DMXOut
    line_in: LineIn
    sources: dict[str, Callable] = field(default_factory=dict)   # "live" / "demo" → nový generátor
    scenarios: ScenarioStore | None = None
    auth: Auth | None = None
    nowplaying: NowPlaying | None = None
    rig_store: RigStore | None = None
    speaker: SpeakerWatch | None = None
    airkeep: AirplayKeep | None = None
    player: Player | None = None
    slog: SessionLog | None = None
    sysstats: object | None = None


def build(cfg: dict, sim_bpm: float | None = None, dry: bool = False,
          input_device: str | None = None, genre: str | None = None) -> Box:
    ac, dc = cfg["audio"], cfg["dmx"]
    rig_store = RigStore(cfg.get("rig_file", "rig.yaml"))
    rig = rig_store.build()
    simulated = bool(sim_bpm or genre)

    def live():
        if genre == "mix":
            return mix_source(rate=ac["rate"], hop=ac["hop"])
        if genre:
            return synth_source(bpm=sim_bpm, rate=ac["rate"], hop=ac["hop"], genre=genre,
                                breakdown=None)
        if sim_bpm:
            return synth_source(bpm=sim_bpm, rate=ac["rate"], hop=ac["hop"], silence_every=60)
        if input_device:
            return device_source(input_device, ac["rate"], ac["hop"])
        return parec_source(ac["source"], ac["rate"], ac["hop"])

    sources = {"live": live, "live_realtime": simulated,
               "demo": lambda: mix_source(rate=ac["rate"], hop=ac["hop"])}
    source = live()
    analyzer = Analyzer(source, rate=ac["rate"], hop=ac["hop"], fft=ac["fft"],
                        bpm_min=ac["bpm_min"], bpm_max=ac["bpm_max"],
                        silence_seconds=ac["silence_seconds"], realtime=simulated)
    out = DMXOut(driver="dry" if dry else dc["driver"], fps=dc["fps"],
                 channels=rig.universe_channels,          # podľa svetiel, nie pevné číslo
                 chunk=dc["chunk"], delay_ms=cfg["output"]["light_delay_ms"])
    store = Store(resolve(cfg["presets_file"]),
                  Settings(light_delay_ms=cfg["output"]["light_delay_ms"]))
    engine = Engine(rig, analyzer, store, out, fps=dc["fps"])
    return Box(store, analyzer, engine, out, LineIn(), sources,
               ScenarioStore(resolve(cfg.get("scenario_file", "scenario.json"))),
               Auth(resolve(cfg.get("security_file", "security.json"))), NowPlaying(), rig_store,
               SpeakerWatch(resolve(cfg.get("speaker_file", "speaker.json"))),
               AirplayKeep(resolve(cfg.get("airplay_file", "airplay.json"))))


def _track_watch(box) -> None:
    """Zmena skladby → analýza intenzity sa učí rozsah novej skladby (každá má inú hlasitosť)."""
    last = None
    while True:
        try:
            tr = box.nowplaying.track
            key = (tr.artist, tr.title) if tr and tr.title else None
            if key and key != last:
                if last is not None:
                    box.analyzer.new_track()
                last = key
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)


def main() -> None:
    ap = argparse.ArgumentParser(description="DMX-BOX")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--sim", type=float, nargs="?", const=124.0, default=None,
                    metavar="BPM", help="simulovaná hudba (predvolene 124 BPM)")
    ap.add_argument("--genre", choices=("mix",) + GENRES, default=None,
                    help="simulovaný žáner; mix = striedanie žánrov s breakdown/drop (test auto štýlu)")
    ap.add_argument("--dry", action="store_true", help="DMX naprázdno (bez USB)")
    ap.add_argument("--input", default=None, metavar="ZARIADENIE",
                    help="zvukový vstup cez sounddevice (Mac/PC), napr. 'BlackHole 2ch'")
    ap.add_argument("--list-inputs", action="store_true", help="vypíše zvukové vstupy a skončí")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.list_inputs:
        print("\n".join(list_inputs()))
        return

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    box = build(cfg, sim_bpm=args.sim, dry=args.dry, input_device=args.input, genre=args.genre)
    box.player = Player(box)
    box.slog = SessionLog(resolve(cfg.get("log_dir", "logs")), box)
    logging.getLogger("dmxbox").addHandler(LogHandler(box.slog))
    box.out.start()
    box.analyzer.start()
    box.engine.start()
    if box.nowplaying:
        box.nowplaying.start()
        threading.Thread(target=_track_watch, args=(box,), daemon=True, name="track-watch").start()
    if box.speaker:
        box.speaker.start()
    if box.airkeep:
        box.airkeep.start()
    box.player.start()
    box.slog.start()
    try:
        uvicorn.run(create_app(box), host=cfg["web"]["host"],
                    port=args.port or cfg["web"]["port"], log_level="warning")
    finally:
        box.slog.stop()
        box.slog.join(timeout=3)
        box.engine.stop()
        box.analyzer.stop()
        box.out.stop(blackout=True)
        box.line_in.set(False)


if __name__ == "__main__":
    main()
