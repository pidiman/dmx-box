# DMX-BOX — myDMX GO klon na Raspberry Pi 3B+

31. 10. 2026 · Jakub

## Cieľ a princíp

DMX-BOX je samostatná krabička na Raspberry Pi 3B+, ktorá prijíma hudbu z mobilu alebo tabletu, prehráva ju do reproduktora a poduľa beatu riadi svetlá cez bezdrôtový DMX. Funkčne je to náhrada ADJ myDMX GO: tablet je ovládač a krabička generuje DMX.

Rozdiel oproti myDMX GO: krabička sama počúva hudbu a svetlá hýbe v tempe bez programovania. Ovládanie z tabletu slúži na výber efektov, presetov a režimu.

**Základné rozhodnutia**

- Zvuk sa nezachytáva mikrofónom. Box je priamo v audio reťazci, analyzuje presne ten digitálny signál, ktorý hrá.
- **Dovnútra bezdrôtovo:** Bluetooth A2DP z akéhokoľvek mobilu, Spotify Connect, voliteľne AirPlay.
- **Von káblom:** UCA202 → AUX-in reproduktora. Latencia \~10–20 ms, svetlá sú v sync bez kalibrácie.
- **DMX:** Lixada USB-DMX → XLR → wireless TX → RX pri svetlách.
- **Mozog:** vlastná Python aplikácia (beat engine + web PWA), nie QLC+. QLC+ audio triggery dali nevyhovujúce výsledky.
- **Záložný režim:** reproduktor bez AUX-in = výstup cez druhý BT adaptér a posuvník *light delay*.

**Svetlá v zostave**

| Svetlo | Mód | DMX adresa |
| --- | --- | --- |
| MAX LED Parbar 4-way 3× 4-in-1 RGBW | treba doplniť | 1 |
| Fractal Lights Mini LED Gobo Spot 30W (moving head) | 12CH | 9 |
| Light4Me BELKA Laser Strobe LED PAR Derby UV | treba doplniť | treba doplniť |

## Architektúra a tok signálu

```text
 Mobil/tablet (BT A2DP)   Spotify Connect (Wi-Fi)   DJ mixér / PC (line-in)
          │                        │                          │
┌─────────▼────────────────────────▼──────────────────────────▼─────────┐
│ DMX-BOX · Raspberry Pi 3B+                                            │
│                    ┌────────────────────────────┐                     │
│                    │ PipeWire sink (mix vstupov)│                     │
│                    └──────┬──────────────┬──────┘                     │
│                    výstup │              │ monitor                    │
│              ┌────────────▼───┐   ┌──────▼──────┐   ┌──────────────┐  │
│              │ UCA202 výstup  │   │  audio.py   │   │ api.py + PWA │◄─┼── tablet
│              └────────┬───────┘   └──────┬──────┘   └──────┬───────┘  │
│                       │           ┌──────▼──────┐  príkazy │          │
│                       │           │  engine.py  │◄─────────┘          │
│                       │           └──────┬──────┘                     │
│                       │           ┌──────▼──────┐                     │
│                       │           │ OLA (uDMX)  │                     │
└───────────────────────┼───────────┴──────┬──────┴─────────────────────┘
                        │                  │
                 Reproduktor (AUX)   USB-DMX → XLR → wireless TX
                                           ┆ bezdrôtový DMX
                                     RX → Parbar → Moving head → Derby
```

Všetky vstupy sa zmiešajú v jednom PipeWire sinku. Zvuk ide káblom do reproduktora a ten istý signál cez monitor do analýzy. Engine z neho 40× za sekundu počíta DMX a posiela ho cez OLA a wireless link ku svetlám.

## Hardvér

Dokúpiť treba približne za 50 €. Všetko ostatné už máš.

| Položka | Účel | Stav | \~Cena |
| --- | --- | --- | --- |
| Raspberry Pi 3B+ | mozog boxu, 4× USB, Wi-Fi 2,4 + 5 GHz, BT 4.2 | mám | – |
| Lixada USB-DMX interface | DMX výstup (pravdepodobne uDMX klon 16c0:05dc) | mám | – |
| DMX512 wireless TX + RX (ISM, XLR) | bezdrôtový DMX ku svetlám | mám | – |
| ESP32 | rezerva, prípadný stabilnejší DMX výstup | mám | – |
| Behringer UCA202 (alebo UCA222) | USB zvukovka, stereo RCA in + out | kúpiť | 30 € |
| microSD 16–32 GB, A1 | systém | kúpiť | 6 € |
| Oficiálny zdroj 5 V / 2,5 A micro-USB | stabilné napájanie aj pre USB zariadenia | kúpiť | 10 € |
| Kábel RCA → 3,5 mm jack | box → AUX-in reproduktora | kúpiť | 3 € |
| Kábel RCA/jack (line-in) | DJ mixér alebo PC → box, voliteľne | voliteľne | 3 € |
| XLR kábel 3-pin, krátky | USB-DMX → wireless TX (over samec/samica) | over | 4 € |
| DMX terminátor 120 Ω | na posledné svetlo za RX | voliteľne | 3 € |
| Krabička | 3D tlač na Snapmaker U1, vetranie pre Pi | vytlačiť | – |
| USB Bluetooth 5.0 dongle (RTL8761B, napr. TP-Link UB500) | len pre záložný režim BT → BT reproduktor | voliteľne | 10 € |

Pi Zero nie je potrebná. 3B+ má dosť USB portov, 5 GHz Wi-Fi a lepšiu anténu.

## Nákupný zoznam

Povinné položky vyjdú približne na 50–60 €. Všetko je zo slovenských e-shopov, okrem terminátora z Thomannu ako alternatívy. Ceny sú z vyhľadávania a porovnávača, pred objednávkou ich over v košíku.

| Položka | Obchod | Cena | Priorita |
| --- | --- | --- | --- |
| [Behringer UCA 202 U-CONTROL](https://www.heureka.sk/?h%5Bfraze%5D=behringer+uca+202+u-control) | Muziker.sk, BaSys SK | 27–28 € | povinné |
| [Raspberry Pi 12,5 W / 2,5 A biely (RPi 3), micro-USB](https://www.alza.sk/komponenty/raspberry/18852654-v3978.htm) | Alza.sk | 11,90 € | povinné |
| [SanDisk Ultra microSDHC 32 GB A1](https://pamatove-karty.heureka.sk/f:q:sandisk%2032gb/) | Heureka.sk, 30+ obchodov | 5,30–14,70 € | povinné |
| [AlzaPower AluCore 3,5 mm jack (M) → 2× RCA (M), 1 m](https://www.alza.sk/alzapower-alucore-35-mm-jack-m-to-2-rca-m-1-m-cierny-d7269393.htm) | Alza.sk | 5,20 € | povinné |
| [RASPBERRY Pi RB-Heatsink](https://www.alza.sk/komponenty/raspberry/18852654-v3978.htm) | Alza.sk | cena na webe | odporúčané |
| [Accu Cable AC-DMX3/0,5, DMX kábel 0,5 m](https://www.profi-dj.sk/hudobne-nastroje/kable/dmx-kable/?orderer%5Bproduct_venality%5D=de) | Profi-DJ.sk | 4,77 € | ak TX nejde zapojiť priamo |
| [Accu Cable DMX Terminator 3pin, 2 ks](https://danel.sk/kable-dmx-1611283347/) alebo [Stairville DMX Terminator XLR 3-Pol](https://www.thomannmusic.com/stairville_dmx_endstecker_xlr_3pol.htm) | Danel.sk / Thomann | \~4 € | voliteľné |
| [TP-Link UB500](https://datacomp.sk/tp-link-ub500_d427310.html) | Datacomp.sk | 8,91 € | len záložný režim BT → BT |

- Zdroj musí byť **micro-USB**. Pre Pi 3B+ neber USB-C verziu pre Pi 4.
- Pri DMX kábli najprv pozri, či sa Lixada a TX dajú spojiť priamo (samec/samica). Ak áno, kábel netreba.
- Line-in kábel z mixéra (RCA–RCA alebo jack–RCA) kúpiš až vtedy, keď ho budeš naozaj potrebovať.
- Muziker má dopravu zdarma od 149 €, preto sa oplatí spojiť Alza objednávku (zdroj, kábel, chladič, prípadne microSD) a UCA202 objednať zvlášť z Muzikera alebo BaSys SK.

## Fyzické zapojenie

Všetko sa zapája priamo do Pi 3B+, bez hubu.

1. **Napájanie:** oficiálny 5 V / 2,5 A zdroj do micro-USB na Pi.
2. **USB port 1:** Lixada USB-DMX.
3. **USB port 2:** Behringer UCA202.
4. **UCA202 OUTPUT (RCA)** → kábel RCA → 3,5 mm → AUX-in reproduktora.
5. **UCA202 INPUT (RCA)** ← line-out DJ mixéra alebo PC (voliteľne).
6. **Lixada XLR výstup** → krátky XLR kábel → vstup wireless DMX TX. TX má vlastné napájanie.
7. **Pri svetlách:** wireless RX → XLR → Parbar (DMX in) → Parbar (DMX out) → moving head → Derby → terminátor 120 Ω.
8. **Ethernet** (voliteľne) počas vývoja a prvého nastavenia.

Wireless TX aj RX nastav na rovnaký kanál. Wi-Fi boxu pobeží na 5 GHz, takže v 2,4 GHz zostane len Bluetooth z mobilu a DMX link.

## OS a príprava Pi 3B+

Systém je Raspberry Pi OS Lite 64-bit, headless, s hostname `dmx-box`.

1. Raspberry Pi Imager → Raspberry Pi 3 → Raspberry Pi OS Lite (64-bit). V nastaveniach zapni SSH, nastav používateľa, hostname `dmx-box`, domácu Wi-Fi a krajinu SK.
2. Prvé prihlásenie a základ:

```bash
ssh <user>@dmx-box.local
sudo apt update && sudo apt full-upgrade -y
sudo raspi-config nonint do_wifi_country SK
vcgencmd get_throttled        # musí byť throttled=0x0
lsusb                         # over Lixada (16c0:05dc = uDMX) a UCA202 (08bb:2902)
```

3. Vypni onboard analógový jack (PWM, šumí) v `/boot/firmware/config.txt`:

```ini
dtparam=audio=off
```

4. Balíky pre celý projekt:

```bash
sudo apt install -y git avahi-daemon \
  pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth bluez pulseaudio-utils \
  ola python3-ola python3-aubio python3-numpy python3-yaml python3-pip
pip install --break-system-packages fastapi "uvicorn[standard]"
loginctl enable-linger $USER   # PipeWire beží aj bez prihlásenia
sudo reboot
```

## Audio subsystém

Všetky vstupy idú do jedného PipeWire sinku (UCA202 výstup). Analyzátor číta jeho `.monitor`, takže nezáleží, odkiaľ hudba ide.

| Vstup | Pre koho | Poznámka |
| --- | --- | --- |
| Bluetooth A2DP | akýkoľvek mobil/tablet, akákoľvek appka | onboard BT, box sa označí ako „DMX-BOX“ |
| Spotify Connect | Spotify na Android aj iOS | `raspotify`, hrá cez Wi-Fi, lepší dosah aj kvalita |
| AirPlay | iPhone/iPad, všetky appky | `shairport-sync`, len ak bude treba |
| Line-in | DJ mixér, PC | UCA202 INPUT + PipeWire loopback, prepínač v UI |

**Výstup:** UCA202 OUTPUT → AUX-in reproduktora. Predvolený sink nastav na UCA202:

```bash
wpctl status
wpctl set-default <ID alsa_output.usb-BurrBrown_from_Texas_Instruments_USB_AUDIO_CODEC-00.analog-stereo>
```

**Bluetooth vstup** (`/etc/bluetooth/main.conf`):

```ini
[General]
Name = DMX-BOX
DiscoverableTimeout = 0
AlwaysPairable = true
JustWorksRepairing = always
```

```bash
bluetoothctl <<EOF
power on
agent NoInputNoOutput
default-agent
discoverable on
pairable on
EOF
```

WirePlumber s `libspa-0.2-bluetooth` vytvorí A2DP sink automaticky. Stream z mobilu sa napojí na predvolený výstup, teda UCA202. Agent bude v produkcii bežať ako malá systemd služba (`bt-agent.service`).

**Spotify Connect:**

```bash
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
# /etc/raspotify/conf: LIBRESPOT_NAME="DMX-BOX", LIBRESPOT_BACKEND="pulseaudio", LIBRESPOT_BITRATE="320"
```

**Line-in loopback** (zapína a vypína ho appka):

```bash
pactl load-module module-loopback \
  source=alsa_input.usb-BurrBrown_from_Texas_Instruments_USB_AUDIO_CODEC-00.analog-stereo \
  sink=alsa_output.usb-BurrBrown_from_Texas_Instruments_USB_AUDIO_CODEC-00.analog-stereo \
  latency_msec=20
```

**Analyzátor** číta monitor výstupu ako mono float32:

```bash
parec -d alsa_output.usb-BurrBrown_from_Texas_Instruments_USB_AUDIO_CODEC-00.analog-stereo.monitor \
      --format=float32le --rate=44100 --channels=1 --latency-msec=10
```

Presné názvy zariadení sa overia cez `pactl list short sinks` a `pactl list short sources` po zapojení UCA202.

## DMX výstup

DMX posiela OLA (`olad`) cez uDMX plugin do univerza 1. Aplikácia mu posiela 512-bajtový buffer 40× za sekundu.

1. udev pravidlo pre uDMX klon:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="16c0", ATTR{idProduct}=="05dc", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/50-udmx.rules
sudo udevadm control --reload && sudo udevadm trigger
```

2. OLA: v `/etc/ola/` nastav `enabled = false` všetkým USB pluginom okrem `ola-udmx.conf` a `ola-artnet.conf`. Potom:

```bash
sudo systemctl enable --now olad
ola_dev_info                      # musí ukázať uDMX zariadenie
ola_patch -d <device_id> -p 0 -u 1
ola_set_dmx -u 1 -d 255,0,0,0     # test: prvé kanály parbaru
```

Web OLA beží na `http://dmx-box.local:9090`, hodí sa na kontrolu kanálov.

3. **Art-Net vstup** ostane zapnutý. ENTTEC EMU z Macu alebo QLC+ z PC môže poslať Art-Net do toho istého boxu a obísť vlastný engine.
4. **Ak by `lsusb` ukázalo `0403:6001`** (FTDI), použije sa plugin `ftdidmx` namiesto uDMX. Zvyšok sa nemení.

**Záloha s ESP32:** ak lacný uDMX klon spôsobí blikanie moving headu (nepresné časovanie), ESP32 + MAX485 s knižnicou `esp_dmx` bude DMX výstup a Pi mu pošle Art-Net cez Ethernet alebo Wi-Fi. Zatiaľ to netreba.

## Aplikácia dmxbox

Jeden Python proces s tromi súbežnými časťami: audio analýza, engine (40 Hz) a web API. Zdieľajú stav v pamäti, nepotrebujú databázu.

**Moduly**

| Modul | Úloha |
| --- | --- |
| `audio.py` | číta `parec` stream, počíta BPM, fázu beatu, onsety a pásma |
| `fixtures.py` + `fixtures.yaml` | kanálové mapy svetiel, preklad „farba / pan / tilt / dimmer“ na DMX kanály |
| `effects/` | jednotlivé FX ako malé funkcie: vstup = audio stav + čas, výstup = hodnoty pre svetlá |
| `engine.py` | 40 Hz slučka, skladá vrstvy FX, aplikuje master a light delay, posiela do OLA |
| `api.py` | FastAPI: REST príkazy, WebSocket so stavom, servuje PWA |
| `state.py` | aktuálny režim, vybrané FX, presety v `presets.json` |
| `config.yaml` | výstup (cable/bluetooth), light delay, názvy audio zariadení, OLA univerz |

**Audio analýza** (`audio.py`)

- 44,1 kHz mono, hop 512 vzoriek (\~11,6 ms na blok).
- `aubio.tempo("default", 1024, 512, 44100)` dáva beaty a BPM. Z nich sa počíta plynulá fáza beatu 0–1 a číslo taktu.
- `aubio.onset("hfc", …)` zachytí kick a snare pre okamžité záblesky.
- FFT do pásiem: bass 20–150 Hz, mid 150–2 000 Hz, high 2–16 kHz. Každé pásmo má obálku (attack/decay) a AGC, takže hlasitosť z mobilu nevadí.
- Ticho (pod prahom N sekúnd) prepne engine do pomalého idle efektu.

Výstup je `AudioState`:

```python
@dataclass
class AudioState:
    bpm: float          # napr. 124.0
    beat_phase: float   # 0.0–1.0 v rámci beatu
    beat_count: int     # rastie s každým beatom
    onset: bool         # kick/snare v tomto bloku
    bass: float         # 0.0–1.0 po AGC
    mid: float
    high: float
    level: float
    silent: bool
```

**fixtures.yaml** (návrh, kanály sa doplňia z manuálov):

```yaml
fixtures:
  parbar:
    start: 1
    type: rgbw_segments
    segments: 4            # 4 hlavy
    channels: {}           # doplniť: dimmer, strobe, R,G,B,W na segment
  movinghead:
    start: 9
    type: moving_head
    mode: 12ch
    channels: {}           # doplniť: pan, pan_fine, tilt, tilt_fine, speed, dimmer, strobe, color, gobo...
    limits: {pan: [0, 255], tilt: [40, 200]}   # aby nesvietil do očí / do stropu
  derby:
    start: null            # doplniť adresu
    type: effect
    channels: {}
```

**Engine a vrstvy** (`engine.py`)

Každý frame (25 ms) sa skladá v tomto poradí. Vyššia vrstva prepíše nižšiu:

1. Blackout
2. Strobe hold (tlačidlo držíš v UI)
3. Manuálne prepísanie (farba z color pickera, pozícia moving headu)
4. FX koleso 1: farby (parbar, derby)
5. FX koleso 2: pohyb (moving head)
6. Master dimmer a light delay (oneskorenie celého výstupu o N ms cez ring buffer)

**FX koleso 1: farby** (8 efektov, prvý návrh)

| FX | Správanie |
| --- | --- |
| Beat chase | každý beat sa rozsvieti ďalšia hlava parbaru |
| Bass pump | jas celého parbaru poduľa bass obálky |
| Color step | každý takt nová farba z palety |
| Rainbow drift | pomalý prechod farieb, rýchlosť z BPM |
| Split L/R | ľavá a pravá polovica striedavo na beat |
| Kick flash | biely záblesk na onset, inak tlmená farba |
| Build-up | stupňujúce sa blikanie pri rástúcom high, drop = strobe |
| Derby sync | derby motor a farby zapínané na refrénoch (vysoký level) |

**FX koleso 2: pohyb** (moving head)

| FX | Správanie |
| --- | --- |
| Circle | kruh, jedna otáčka za 1, 2 alebo 4 takty |
| Figure 8 | osmička v tempe |
| Sweep | pan zo strany na stranu na beat |
| Tilt bounce | tilt hore-dole na beat |
| Snap | skáče na náhodné pozície na každý 2. beat |
| Audience | pomalý pohyb nad hlavami, gobo rotácia |
| Gobo beat | statická pozícia, gobo a farba sa menia na beat |
| Hold | moving head stojí na uloženej pozícii |

**Modifikátory** spoločné pre obe kolesá: speed (½× / 1× / 2× BPM), size (amplitúda pohybu alebo rozsah jasu), fade (mäkkosť prechodov), paleta farieb, fan (fázový posun medzi hlavami).

**Auto mód:** každých N taktov (8/16/32) vyberie inú dvojicu FX z povoleného zoznamu. Na párty bez obsluhy je to hlavný režim.

**Presety:** 50 slotov, preset = kompletný stav (oba FX, modifikátory, paleta, master). Uložené v `presets.json`.

## Web UI (PWA) a API

Tablet alebo mobil otvorí `http://dmx-box.local` a pridá si stránku na plochu ako appku. UI je jedna obrazovka s veľkými tlačidlami pre ovládanie palcom.

**Obrazovka**

- Horný pruh: BPM, VU metre bass/mid/high, indikátor beatu, aktívny zdroj (BT / Spotify / line-in).
- **FX koleso 1** (farby) a **FX koleso 2** (pohyb): 8 segmentov ako v myDMX GO.
- Posuvníky: master, speed, size, fade.
- Paleta farieb a color picker.
- Tlačidlá: Auto, Blackout, Strobe (držíš), Tap tempo.
- Presety 1–50 v mriežke, dlhý stlak = uložiť.
- Nastavenia: light delay, line-in on/off, prah ticha, fixtures (adresy).

**API** (FastAPI, port 80 cez `CAP_NET_BIND_SERVICE` alebo 8080 + presmerovanie)

| Metóda | Cesta | Telo / význam |
| --- | --- | --- |
| GET | `/api/state` | kompletný stav |
| POST | `/api/fx` | `{"wheel": 1, "fx": "beat_chase"}` |
| POST | `/api/mod` | `{"speed": 1, "size": 0.7, "fade": 0.3}` |
| POST | `/api/master` | `{"value": 0.8}` |
| POST | `/api/blackout` | `{"on": true}` |
| POST | `/api/strobe` | `{"on": true}` (kým držíš) |
| POST | `/api/auto` | `{"on": true, "bars": 16}` |
| POST | `/api/preset/{n}` | načítať preset |
| PUT | `/api/preset/{n}` | uložiť aktuálny stav |
| POST | `/api/settings` | light delay, line-in, ticho |
| WS | `/ws` | 20×/s: BPM, beat, VU, aktívne FX |

Frontend je čistý HTML + CSS + vanilla JS (bez buildu), s `manifest.json` a service workerom pre ikonu na ploche a offline shell. REST umožní aj ovládanie z Home Assistant (napr. tlačidlo „Párty“ = preset + auto).

## Sieť

Doma sa box pripája do domácej Wi-Fi na 5 GHz. Mimo domu, keď tú sieť nenájde, spustí vlastný hotspot DMX-BOX. Tablet sa pripojí tam a ovláda box cez rovnakú PWA.

**Domáca Wi-Fi na 5 GHz:**

```bash
nmcli -f SSID,CHAN,FREQ dev wifi
sudo nmcli con modify "<tvoja-wifi>" 802-11-wireless.band a
```

**Hotspot (5 GHz, kanál 36):**

```bash
sudo nmcli con add type wifi ifname wlan0 con-name dmx-hotspot ssid DMX-BOX \
  802-11-wireless.mode ap 802-11-wireless.band a 802-11-wireless.channel 36 \
  ipv4.method shared ipv4.addresses 10.42.0.1/24 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<heslo>" connection.autoconnect no
```

**Fallback logika:** malá služba `wifi-fallback.service` po štarte čaká 30 s. Ak nie je pripojená žiadna klientská sieť, spustí `nmcli con up dmx-hotspot`.

**mDNS:** `avahi-daemon` publikuje `dmx-box.local` v domácej sieti. V hotspote je box aj na `10.42.0.1`.

**Poznámka k hotspotu:** bez internetu Spotify Connect nefunguje, Bluetooth áno. Mimo domu je teda hlavný vstup Bluetooth, prípadne line-in.

## Repo, služby a nasadenie

Kód bude v repe `pidiman/dmx-box` na GitHube. Na Pi sa klonuje do `/opt/dmx-box` a inštaluje jedným skriptom.

```text
dmx-box/
├── install.sh              # balíky, udev, OLA config, BT config, systemd, hotspot
├── config.yaml             # výstup, light delay, audio zariadenia, univerz
├── fixtures.yaml           # kanálové mapy svetiel
├── dmxbox/
│   ├── main.py             # štart: audio vlákno, engine vlákno, uvicorn
│   ├── audio.py
│   ├── engine.py
│   ├── fixtures.py
│   ├── state.py
│   ├── api.py
│   └── effects/
│       ├── color.py        # FX koleso 1
│       └── movement.py     # FX koleso 2
├── web/                    # index.html, app.js, style.css, manifest.json, sw.js
├── systemd/
│   ├── dmxbox.service
│   ├── bt-agent.service
│   └── wifi-fallback.service
└── tools/
    ├── dmx_test.py         # rozsvieti jednotlivé kanály, test fixtures.yaml
    └── audio_meter.py      # vypíše BPM a VU v termináli
```

**dmxbox.service** (user služba, aby videla PipeWire):

```ini
[Unit]
Description=DMX-BOX engine
After=pipewire.service wireplumber.service

[Service]
WorkingDirectory=/opt/dmx-box
ExecStart=/usr/bin/python3 -m dmxbox.main
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
```

```bash
mkdir -p ~/.config/systemd/user
cp systemd/dmxbox.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dmxbox
journalctl --user -u dmxbox -f
```

**Aktualizácia:** `cd /opt/dmx-box && git pull && systemctl --user restart dmxbox`. Vývoj môžeš robiť v Claude Code na PC, push na GitHub a pull na Pi, rovnako ako pri ostatných projektoch.

## Míľniky

Každý míľnik má jasný test. Ďalší sa začína, až keď predošlý prejde.

- [ ] **M0 – Pi a OS:** `ssh dmx-box.local` funguje, `vcgencmd get_throttled` = `0x0`, `lsusb` vidí Lixada aj UCA202.
- [ ] **M1 – DMX káblom:** `ola_set_dmx -u 1 -d 255,0,0,0` rozsvieti parbar pri priamom XLR kábli.
- [ ] **M2 – Wireless DMX:** to isté cez TX/RX, 5 minút bez výpadku pri zapnutej Wi-Fi aj BT.
- [ ] **M3 – Fixtures:** `tools/dmx_test.py` ovláda každý kanál všetkých troch svetiel podľa `fixtures.yaml`.
- [ ] **M4 – Audio prehrávanie:** mobil cez BT hrá do boxu a zvuk ide z reproduktora cez AUX. Spotify Connect vidí „DMX-BOX“.
- [ ] **M5 – Analýza:** `tools/audio_meter.py` ukazuje BPM, ktoré sedí so skladbou (±2 BPM), a VU reaguje na bass.
- [ ] **M6 – Engine v1:** jeden farebný FX (Beat chase) a jeden pohybový (Circle) bežia v tempe.
- [ ] **M7 – Web UI:** z tabletu sa prepínajú FX, master, blackout a strobe s odozvou pod 100 ms.
- [ ] **M8 – Všetky FX a presety:** 8 + 8 FX, modifikátory, auto mód, 50 presetov.
- [ ] **M9 – Produkcia:** systemd služby, hotspot fallback, line-in prepínač, box nabehne sám po zapnutí do 60 s.
- [ ] **M10 – Krabička:** 3D tlačená krabička s vetraním, káble upevnené.

## Riziká a riešenia

| Riziko | Príznak | Riešenie |
| --- | --- | --- |
| Rušenie v 2,4 GHz | svetlá zamrzú, BT audio vypadáva | Wi-Fi na 5 GHz, DMX TX na vzdialený kanál, box bližšie k mobilu |
| Slabý zdroj | USB zariadenia odpadávajú, `throttled` ≠ 0x0 | oficiálny zdroj 2,5 A, krátky kvalitný kábel |
| uDMX klon má nepresné časovanie | moving head trhá alebo bliká | nižší refresh (30 Hz); inak ESP32 + MAX485 ako Art-Net node |
| Reproduktor nemá AUX-in | – | USB BT dongle ako druhý adaptér, výstup cez BT a light delay \~200 ms |
| BPM detekcia sa zmýli (half/double tempo) | pohyb je 2× rýchly alebo pomalý | obmedzenie BPM na 80–170, tlačidlá ½× / 2× a Tap tempo v UI |
| Ticho alebo hovorené slovo | svetlá náhodne blikajú | prah ticha a idle efekt |
| Moving head svieti do očí | – | limity pan/tilt vo `fixtures.yaml`, pohyb „Audience“ nad hlavami |
| Pi sa prehrieva v krabičke | throttling, oneskorenie | vetracie otvory, malý chladič na SoC |
| Spotify Connect bez internetu | box nie je vidno v Spotify | mimo domu používať Bluetooth |

## Otvorené otázky

Tieto údaje treba doplniť pred písaním `fixtures.yaml` a efektov.

- [ ] Výstup `lsusb` s Lixada: uDMX (`16c0:05dc`) alebo FTDI (`0403:6001`)?
- [ ] MAX Parbar: DMX mód (počet kanálov) a kanálová tabuľka.
- [ ] Fractal Mini LED Gobo Spot 30W: tabuľka 12CH módu (pan, tilt, fine, speed, dimmer, strobe, color, gobo, reset…).
- [ ] Light4Me BELKA Derby: DMX mód, adresa a kanálová tabuľka.
- [ ] Model reproduktora: má AUX-in?
- [ ] Zariadenia, z ktorých sa bude hrať: iOS, Android alebo oboje (treba AirPlay?).
- [ ] Kúpiť UCA202, microSD a zdroj.
