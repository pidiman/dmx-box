# DMX-BOX

Samostatná krabička na **Raspberry Pi 3B+** inšpirovaná ADJ myDMX GO. Prijíma hudbu z mobilu alebo tabletu (Bluetooth, Spotify Connect, line-in), prehráva ju do reproduktora a podľa beatu riadi DMX svetlá cez bezdrôtový DMX link. Ovláda sa z tabletu cez web PWA.

## Princíp

- **Bez mikrofónu:** box je v audio reťazci a analyzuje presne ten signál, ktorý hrá.
- **Vstupy:** Bluetooth A2DP, Spotify Connect, voliteľne AirPlay a line-in (UCA202).
- **Výstup zvuku:** UCA202 → AUX-in reproduktora (latencia ~10–20 ms, sync bez kalibrácie).
- **DMX:** priamy uDMX výstup cez pyusb (32 kanálov po 8) → Lixada USB-DMX → XLR → wireless TX → RX pri svetlách.
- **Mozog:** Python aplikácia `dmxbox` (numpy beat engine, FX kolesá, FastAPI + PWA).

## Svetlá

| Svetlo | Mód | DMX adresa |
| --- | --- | --- |
| MAX PartyBar4 (LED Parbar 4-way 3× 4-in-1 RGBW) | 8CH | 1 (1–8) |
| Fractal Lights Mini LED Gobo Spot 30W (moving head) | 12CH, `SL 1` | 9 (9–20) |
| Light4Me BELKA Laser Strobe LED PAR Derby UV | 12CH | 21 (21–32) |

Kanálové mapy: [`fixtures.yaml`](fixtures.yaml).

## Dokumentácia

Kompletný popis projektu je v [docs/PROJEKT.md](docs/PROJEKT.md):

- architektúra a tok signálu
- hardvér a nákupný zoznam (slovenské e-shopy)
- fyzické zapojenie
- príprava OS, audio subsystém (PipeWire, BT, Spotify Connect, line-in)
- DMX výstup (OLA, uDMX, wireless)
- aplikácia `dmxbox`: moduly, audio analýza, engine, FX kolesá
- web UI a API, sieť (5 GHz, hotspot fallback)
- míľniky, riziká, otvorené otázky

## Rýchly štart

Na Raspberry Pi 3B+ (Raspberry Pi OS Lite 64-bit):

```bash
git clone https://github.com/pidiman/dmx-box ~/dmx-box && cd ~/dmx-box
./install.sh --hotspot-pass 'tajne-heslo' --spotify
sudo reboot
```

Ovládanie z tabletu: `http://dmx-box.local` (pridaj na plochu ako appku).

Bez hardvéru (vývoj na PC/Mac):

```bash
python3 -m venv .venv && source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt pytest httpx
python3 -m dmxbox.main --sim 128 --dry --port 8080   # simulovaná hudba, DMX naprázdno → http://localhost:8080
python3 -m pytest -q tests
```

Nástroje: `tools/dmx_test.py` (test kanálov), `tools/audio_meter.py` (BPM a pásma v termináli).

## Stav

Kód v0.1: audio analýza, engine s 8 + 8 FX, auto mód, presety, PWA, systemd a inštalácia. Otestované bez hardvéru (simulácia, 12 testov). Ďalší krok: M0–M3 na Pi so svetlami.
