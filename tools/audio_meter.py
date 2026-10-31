#!/usr/bin/env python3
"""Živý výpis BPM, beatu a pásiem v termináli (míľnik M5).

  python3 tools/audio_meter.py            # monitor predvoleného výstupu (parec)
  python3 tools/audio_meter.py --sim 140  # syntetická hudba
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dmxbox.audio import Analyzer, parec_source  # noqa: E402
from dmxbox.config import load_config  # noqa: E402
from dmxbox.sim import synth_source  # noqa: E402


def bar(v: float, n: int = 16) -> str:
    k = int(round(max(0.0, min(1.0, v)) * n))
    return "█" * k + "·" * (n - k)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", type=float, default=None, metavar="BPM")
    ap.add_argument("--source", default=None, help="parec zariadenie (predvolene z config.yaml)")
    a = ap.parse_args()
    ac = load_config()["audio"]
    src = (synth_source(bpm=a.sim, rate=ac["rate"], hop=ac["hop"]) if a.sim
           else parec_source(a.source or ac["source"], ac["rate"], ac["hop"]))
    an = Analyzer(src, rate=ac["rate"], hop=ac["hop"], fft=ac["fft"], bpm_min=ac["bpm_min"],
                  bpm_max=ac["bpm_max"], silence_seconds=ac["silence_seconds"], realtime=bool(a.sim))
    an.start()
    last_beat = -1
    try:
        while True:
            s = an.snapshot()
            beat = "●" if s.beat_count != last_beat else " "
            last_beat = s.beat_count
            print(f"\r{beat} {s.bpm:6.1f} BPM {'✓' if s.bpm_confident else '?'}  "
                  f"B {bar(s.bass)}  M {bar(s.mid)}  H {bar(s.high)}  "
                  f"kick#{s.onset_count:<5} {'TICHO' if s.silent else '     '}", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
