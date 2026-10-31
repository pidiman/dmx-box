#!/usr/bin/env python3
"""Test DMX kanálov podľa fixtures.yaml (míľniky M1–M3).

  python3 tools/dmx_test.py raw 1 255 4 255 5 255     # kanál/hodnota páry, drží 10 s
  python3 tools/dmx_test.py walk belka                # prejde kanály svetla po jednom
  python3 tools/dmx_test.py sweep belka strobe_uv     # jeden kanál 0→255 po krokoch
  python3 tools/dmx_test.py walk all --log test.txt   # všetky svetlá, odpovede do súboru

Pri walk/sweep napíš krátko, čo vidíš, a stlač Enter (prázdne = nič).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dmxbox.config import load_config  # noqa: E402
from dmxbox.dmx_out import DMXOut  # noqa: E402
from dmxbox.fixtures import load_rig  # noqa: E402

# aby svetlo pri teste vôbec svietilo
BASE = {
    "parbar": {"dimmer": 255},
    "movinghead": {"dimmer": 255, "pan": 128, "tilt": 128},
    "belka": {},
}


def make_out(dry: bool) -> DMXOut:
    cfg = load_config()
    out = DMXOut(driver="dry" if dry else cfg["dmx"]["driver"], fps=30,
                 channels=cfg["dmx"]["channels"], chunk=cfg["dmx"]["chunk"])
    out.start()
    return out


def ask(prompt: str, log: list[str]) -> None:
    try:
        ans = input(prompt).strip()
    except EOFError:
        ans = ""
    log.append(f"{prompt.strip()} {ans or 'nic'}")


def walk(rig, out, keys, log):
    for key in keys:
        fx = rig[key]
        print(f"\n== {fx.name} (adresa {fx.start}) ==")
        for ch in sorted(fx.channels, key=fx.channels.get):
            for v in (255, 128):
                f = rig.new_frame()
                for bch, bv in BASE.get(key, {}).items():
                    fx.set(f, bch, bv)
                fx.set(f, ch, v)
                out.submit(f)
                ask(f"  {key}.{ch:<13} DMX {fx.addr(ch):>3} = {v:3d} → čo vidíš? ", log)


def sweep(rig, out, key, ch, step, log):
    fx = rig[key]
    print(f"{fx.name}: {ch} (DMX {fx.addr(ch)}) 0→255 po {step}")
    for v in range(0, 256, step):
        f = rig.new_frame()
        for bch, bv in BASE.get(key, {}).items():
            fx.set(f, bch, bv)
        fx.set(f, ch, v)
        out.submit(f)
        ask(f"  {ch} = {v:3d} → ", log)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["raw", "walk", "sweep"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--step", type=int, default=16)
    ap.add_argument("--hold", type=float, default=10.0, help="raw: ako dlho držať (s)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--log", default=None)
    a = ap.parse_args()

    rig = load_rig()
    out = make_out(a.dry)
    log: list[str] = []
    try:
        if a.mode == "raw":
            vals = list(map(int, a.args))
            f = rig.new_frame()
            for ch, v in zip(vals[::2], vals[1::2]):
                f[ch - 1] = v
            out.submit(f)
            print(f"posielam {dict(zip(vals[::2], vals[1::2]))} po dobu {a.hold} s")
            time.sleep(a.hold)
        elif a.mode == "walk":
            keys = list(rig.fx) if not a.args or a.args[0] == "all" else a.args
            walk(rig, out, keys, log)
        else:
            sweep(rig, out, a.args[0], a.args[1], a.step, log)
    except KeyboardInterrupt:
        print("\nprerušené")
    finally:
        out.stop(blackout=True)
        time.sleep(0.2)
        if a.log and log:
            Path(a.log).write_text("\n".join(log) + "\n", encoding="utf-8")
            print(f"uložené do {a.log}")


if __name__ == "__main__":
    main()
