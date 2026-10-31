"""Spustenie DMX-BOX: audio vlákno, engine, DMX výstup, web server.

python3 -m dmxbox.main              # produkcia na Pi
python3 -m dmxbox.main --sim --dry  # simulovaná hudba, DMX naprázdno
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

import uvicorn

from .api import create_app
from .audio import Analyzer, parec_source
from .audio_ctl import LineIn
from .config import load_config, resolve
from .dmx_out import DMXOut
from .engine import Engine
from .fixtures import load_rig
from .sim import synth_source
from .state import Settings, Store


@dataclass
class Box:
    store: Store
    analyzer: Analyzer
    engine: Engine
    out: DMXOut
    line_in: LineIn


def build(cfg: dict, sim_bpm: float | None = None, dry: bool = False) -> Box:
    ac, dc = cfg["audio"], cfg["dmx"]
    rig = load_rig(cfg["fixtures_file"])
    if sim_bpm:
        source = synth_source(bpm=sim_bpm, rate=ac["rate"], hop=ac["hop"], silence_every=60)
    else:
        source = parec_source(ac["source"], ac["rate"], ac["hop"])
    analyzer = Analyzer(source, rate=ac["rate"], hop=ac["hop"], fft=ac["fft"],
                        bpm_min=ac["bpm_min"], bpm_max=ac["bpm_max"],
                        silence_seconds=ac["silence_seconds"], realtime=bool(sim_bpm))
    out = DMXOut(driver="dry" if dry else dc["driver"], fps=dc["fps"],
                 channels=min(dc["channels"], rig.universe_channels) or dc["channels"],
                 chunk=dc["chunk"], delay_ms=cfg["output"]["light_delay_ms"])
    store = Store(resolve(cfg["presets_file"]),
                  Settings(light_delay_ms=cfg["output"]["light_delay_ms"]))
    engine = Engine(rig, analyzer, store, out, fps=dc["fps"])
    return Box(store, analyzer, engine, out, LineIn())


def main() -> None:
    ap = argparse.ArgumentParser(description="DMX-BOX")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--sim", type=float, nargs="?", const=124.0, default=None,
                    metavar="BPM", help="simulovaná hudba (predvolene 124 BPM)")
    ap.add_argument("--dry", action="store_true", help="DMX naprázdno (bez USB)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    box = build(cfg, sim_bpm=args.sim, dry=args.dry)
    box.out.start()
    box.analyzer.start()
    box.engine.start()
    try:
        uvicorn.run(create_app(box), host=cfg["web"]["host"],
                    port=args.port or cfg["web"]["port"], log_level="warning")
    finally:
        box.engine.stop()
        box.analyzer.stop()
        box.out.stop(blackout=True)
        box.line_in.set(False)


if __name__ == "__main__":
    main()
