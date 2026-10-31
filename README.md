# DMX-BOX

Samostatná krabička na **Raspberry Pi 3B+** inšpirovaná ADJ myDMX GO. Prijíma hudbu z mobilu alebo tabletu (Bluetooth, Spotify Connect, line-in), prehráva ju do reproduktora a podľa beatu riadi DMX svetlá cez bezdrôtový DMX link. Ovláda sa z tabletu cez web PWA.

## Princíp

- **Bez mikrofónu:** box je v audio reťazci a analyzuje presne ten signál, ktorý hrá.
- **Vstupy:** Bluetooth A2DP, Spotify Connect, voliteľne AirPlay a line-in (UCA202).
- **Výstup zvuku:** UCA202 → AUX-in reproduktora (latencia ~10–20 ms, sync bez kalibrácie).
- **DMX:** priamy uDMX výstup cez pyusb (36 kanálov po 8) → Lixada USB-DMX → XLR → wireless TX → RX pri svetlách.
- **Mozog:** Python aplikácia `dmxbox` (numpy beat engine, FX kolesá, FastAPI + PWA).

## Svetlá

| Svetlo | Mód | DMX adresa |
| --- | --- | --- |
| MAX PartyBar4 (LED Parbar 4-way 3× 4-in-1 RGBW) | 8CH | 1 (1–8) |
| Fractal Lights Mini LED Gobo Spot 30W (moving head) | 12CH, `SL 1` | 9 (9–20) |
| Light4Me BELKA Laser Strobe LED PAR Derby UV | 12CH | 21 (21–32) |
| U'King 1200W Fog Machine (6 LED) | 4CH (dym + RGB) | 33 (33–36) |

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

**Štýl hudby:** v auto móde box sám rozpozná žáner (DnB, techno, house, hip-hop, chill, pop) a fázu skladby (breakdown, build, drop) a podľa toho mení farby, pohyb, laser, strobo aj dym. V UI sa dá štýl aj pevne zvoliť. Test bez hudby: `python3 -m dmxbox.main --genre mix --dry --port 8080` (žánre sa striedajú po 60 s). Popis: [PROJEKT.md → Štýl hudby](docs/PROJEKT.md#štýl-hudby-auto-rozpoznanie-alebo-pevne).

**Virtuálne svetlá:** `http://localhost:8080/viz.html` (alebo 👁 Viz v ovládaní) kreslí PartyBar4, moving head aj Belku priamo z DMX rámca, ktorý by išiel do svetiel. Dole je panel všetkých 36 kanálov, vrátane dymostroja. Funguje aj s `--dry`, takže efekty sa dajú ladiť bez svetiel.

### Test so svetlami na Macu (pred nasadením na Pi)

Rovnaký kód beží aj na Macu: hudba z Macu ide cez **BlackHole 2ch**, DMX cez Lixada dongle.

```bash
brew install libusb                      # pre pyusb (uDMX)
source .venv/bin/activate && git pull && pip install -r requirements.txt
python3 -m dmxbox.main --list-inputs     # nájdi "BlackHole 2ch"
python3 tools/dmx_test.py walk all       # test kanálov (Enter = ďalší)
python3 -m dmxbox.main --input "BlackHole 2ch" --port 8080
```

- V **Audio MIDI Setup** vytvor *Multi-Output Device* (reproduktory + BlackHole 2ch) a nastav ho ako výstup Macu, aby si hudbu počul a zároveň ju box analyzoval.
- Ovládanie: `http://localhost:8080`, z mobilu `http://<ip-macu>:8080` (rovnaká Wi-Fi).
- Svetlá: PartyBar4 `d001` 8CH, spot `A009` 12CH + `SL 1`, Belka `d021` 12CH, dymostroj `d033` 4CH.

## Stav

Kód v0.2: audio analýza, rozpoznanie štýlu hudby a fázy skladby, engine s 8 + 8 FX a 6 štýlmi, dym, presety, PWA, virtuálne svetlá, systemd a inštalácia. Otestované bez hardvéru (simulácia, 26 testov). Ďalší krok: M0–M3 na Pi so svetlami.

Plán a odložené funkcie (správa svetiel z UI): [docs/ROADMAP.md](docs/ROADMAP.md).
