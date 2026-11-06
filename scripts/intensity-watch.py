#!/usr/bin/env python3
"""Test intenzity: každú sekundu vypíše, čo box „počuje“, a uloží to do súboru.

Spustenie na boxe:   python3 ~/dmx-box/scripts/intensity-watch.py
Počas hrania napíš poznámku a stlač Enter (napr. „drop“, „build“, „tichá časť“) –
uloží sa s časom vedľa údajov boxu. Koniec: Ctrl+C. Súbor: ~/intensita-RRRRMMDD-HHMM.log
"""

import json
import select
import sys
import time
import urllib.request
from pathlib import Path

URL = "http://localhost/api/state"
NAMES = {0: "ticho", 1: "POKOJ", 2: "groove", 3: "ROZOHR", 4: "VRCHOL"}
out = Path.home() / time.strftime("intensita-%Y%m%d-%H%M.log")
t0 = time.time()
last_track = None

with out.open("w", encoding="utf-8") as f:
    print(f"Zapisujem do {out} · poznámka = napíš text + Enter · koniec = Ctrl+C")
    f.write("čas\túroveň\tskóre\theat\tvrcholy\tbpm\tštýl\tfáza(pôvodná)\tpoznámka\n")
    try:
        while True:
            el = time.time() - t0
            stamp = f"{int(el // 60)}:{int(el % 60):02d}"
            try:
                d = json.load(urllib.request.urlopen(URL, timeout=3))
                m, a = d.get("music", {}), d.get("audio", {})
                tr = d.get("track") or {}
                title = " – ".join(x for x in (tr.get("artist"), tr.get("title")) if x)
                if title and title != last_track:
                    last_track = title
                    print(f"\n♪ {title}")
                    f.write(f"{stamp}\t\t\t\t\t\t\t\t♪ {title}\n")
                lvl = 0 if a.get("silent") else m.get("intensity", 0)
                row = (f"{stamp}\t{lvl} {NAMES.get(lvl, '?')}\t{m.get('score', 0):.2f}\t{m.get('heat', 0):.2f}"
                       f"\t{m.get('peaks', 0)}\t{a.get('bpm', 0):.0f}\t{m.get('style', '')}\t{m.get('section', '')}")
            except Exception as e:  # noqa: BLE001
                row = f"{stamp}\tchyba: {e}"
            note = ""
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                note = sys.stdin.readline().strip()
            print(row.replace("\t", "  ") + (f"   ← {note}" if note else ""))
            f.write(row + (f"\t\t{note}" if note else "") + "\n")
            f.flush()
            time.sleep(max(0.0, 1.0 - (time.time() - t0 - el)))
    except KeyboardInterrupt:
        print(f"\nHotovo – pošli mi súbor {out}")
