# Prevádzka: inštalácia, spúšťanie a zmeny prostredia

Všetko, čo treba na Pi po nasadení: parametre inštalácie, spôsoby spustenia a čo robiť pri zmene Wi-Fi, mobilu, reproduktora alebo zdroja hudby. Bežné zmeny sa robia príkazom **`dmxbox`** cez SSH, bez reinštalácie.

## 1. Inštalácia

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/pidiman/dmx-box ~/dmx-box && cd ~/dmx-box
./install.sh --hotspot-pass 'TvojeHeslo123' --spotify --wifi "DomaWiFi" "heslo"
sudo reboot
```

| Parameter | Význam | Predvolené |
| --- | --- | --- |
| `--hotspot-pass HESLO` | záložný hotspot **fajny-dmx-box**, keď nie je známa Wi-Fi (min. 8 znakov) | bez hotspotu |
| `--spotify` | Spotify Connect pod menom boxu (librespot, treba Premium a internet; s novšími účtami nemusí fungovať, pozri [Spotify Connect](#spotify-connect)) | vypnuté |
| `--wifi SSID HESLO` | pridá Wi-Fi sieť, dá sa zadať viackrát | – |
| `--hostname MENO` | iné meno len pre sieť | ako `--name` |
| `--country KÓD` | krajina Wi-Fi, bez nej nejde 5 GHz hotspot | `SK` |
| `--name MENO` | meno boxu: v sieti (`http://MENO.local`), Wi-Fi hotspot, Bluetooth aj Spotify | `fajny-dmx-box` |
| `--bt-name MENO` | iné meno len pre Bluetooth | ako `--name` |
| `--no-jack` | vypnúť 3,5 mm jack na Pi (pri UCA202 menej šumu) | jack zapnutý |

`install.sh` sa dá spustiť znova kedykoľvek, napríklad keď chceš doplniť parameter. Nič nerozbije, len nastavenia prepíše.

Príklad: iné meno boxu a dve Wi-Fi siete:

```bash
./install.sh --name party-box --hotspot-pass 'TvojeHeslo123' \
  --wifi "DomaWiFi" "heslo1" --wifi "Chata" "heslo2"
```

Premenovanie hotového boxu bez reinštalácie: `dmxbox name nove-meno` (sieť, hotspot, Bluetooth aj Spotify naraz).

## 2. Spôsoby spustenia

### Na Pi (normálna prevádzka)

Aplikácia beží ako user služba `dmxbox` a štartuje sama po zapnutí.

```bash
dmxbox status          # prehľad všetkého
dmxbox start|stop|restart
dmxbox logs            # živé logy (Ctrl+C)
dmxbox update          # git pull + reštart
```

### Ručne (ladenie)

```bash
dmxbox stop
cd ~/dmx-box && python3 -m dmxbox.main -v
```

| Prepínač `python3 -m dmxbox.main` | Význam |
| --- | --- |
| `--config SÚBOR` | iný konfiguračný súbor (predvolene `config.yaml`) |
| `--sim [BPM]` | syntetická hudba namiesto zvuku (predvolene 124 BPM) |
| `--genre mix\|house\|techno\|dnb\|hiphop\|chill\|party` | syntetický žáner; `mix` strieda žánre s breakdownom a dropom |
| `--dry` | DMX naprázdno (bez USB donglu) |
| `--input "ZARIADENIE"` | zvukový vstup cez sounddevice (Mac/PC, napr. `"BlackHole 2ch"`) |
| `--list-inputs` | vypíše zvukové vstupy a skončí |
| `--port N` | port webu (predvolene z `config.yaml`, na Pi 80) |
| `-v` | podrobné logy |

### Bez hardvéru (PC/Mac)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest httpx
python3 -m dmxbox.main --genre mix --dry --port 8080   # http://localhost:8080 + /viz.html
python3 -m pytest -q tests
```

### Mac so svetlami

```bash
brew install libusb
python3 -m dmxbox.main --list-inputs
python3 -m dmxbox.main --input "BlackHole 2ch" --port 8080
```

### Nástroje

```bash
dmxbox test dmx walk all            # = python3 tools/dmx_test.py walk all (služba sa zastaví a znova spustí)
dmxbox test dmx walk belka --log t.txt
dmxbox test dmx sweep belka strobe_uv --step 8
dmxbox test dmx raw 1 255 4 255 --hold 5
dmxbox audio meter                  # = tools/audio_meter.py; aj --sim 128, --source, --input
```

## 3. Zmeny prostredia

**Na párty bez počítača:** všetko z tejto kapitoly sa dá robiť aj z tabletu – vstupná obrazovka (`http://fajny-dmx-box.local/`) a **Nastavenia boxu** (ozubené koliesko). Popis: [OVLADANIE.md](OVLADANIE.md). Príkazy `dmxbox` nižšie sú pre SSH.

### Prehľad

| Situácia | Čo urobiť |
| --- | --- |
| Box na novom mieste s inou Wi-Fi | `dmxbox wifi add "SSID" "heslo"` (vopred doma alebo cez hotspot), potom `dmxbox wifi connect "SSID"` |
| Žiadna Wi-Fi (párty vonku, u kamaráta) | nič, hotspot **fajny-dmx-box** sa zapne sám do ~1 min. Tablet sa pripojí na fajny-dmx-box a otvorí `http://10.42.0.1` |
| Wi-Fi vypadla počas behu | nič, po 60 s bez Wi-Fi sa zapne hotspot |
| Späť doma | reštart boxu alebo `dmxbox wifi connect "DomaWiFi"` (cez hotspot) |
| Nový mobil cez Bluetooth | v mobile Bluetooth → **fajny-dmx-box**, bez PIN. Box je stále viditeľný |
| Nechcem, aby sa pripájali cudzí | `dmxbox bt hide` (spárované mobily sa pripoja ďalej), späť `dmxbox bt pair` |
| Pripája sa iný mobil, ako chcem | `dmxbox bt list`, potom `dmxbox bt forget MAC` alebo `dmxbox bt disconnect` |
| Spotify zapnúť / vypnúť | `dmxbox spotify on` / `off` (prvé zapnutie ho aj nainštaluje) |
| Hrá sa z počítača alebo DJ pultu káblom | `dmxbox audio linein on` (UCA202 IN → reproduktor + analýza), alebo prepínač v UI |
| Reproduktor káblom (AUX) | `dmxbox audio out usb` |
| BT reproduktor namiesto kábla | `dmxbox bt scan`, `dmxbox bt connect MAC`, `dmxbox audio out bluez`, `dmxbox audio delay 200` (doladiť od oka) |
| Odpojil sa DMX dongle | zapoj ho späť, aplikácia sa znova pripojí sama (`dmxbox status` → USB) |
| Svetlá „zamrzli“ | `dmxbox status`, potom `dmxbox restart`. Ak nepomôže, skontroluj wireless DMX TX/RX (napájanie, kanál) |
| Nová verzia z GitHubu | `dmxbox update` |
| Zmena hesla hotspotu | `dmxbox hotspot pass "nové-heslo"` |

### Wi-Fi a hotspot

```bash
dmxbox wifi list                       # uložené siete
dmxbox wifi scan                       # siete v dosahu
dmxbox wifi add "SSID" "heslo" 20      # vyššia priorita = prednosť, keď je v dosahu viac sietí
dmxbox wifi connect "SSID"             # prepnúť hneď (SSH cez hotspot sa preruší)
dmxbox wifi del "SSID"

dmxbox hotspot status
dmxbox hotspot on | off
dmxbox hotspot pass "nové-heslo"
dmxbox hotspot auto on | off           # strážca: hotspot, keď nie je Wi-Fi
```

Ako funguje strážca (`wifi-fallback` služba):
- **Po štarte:** ak sa do 40 s nepripojí na známu Wi-Fi, zapne hotspot.
- **Počas behu:** ak Wi-Fi vypadne na 60 s, zapne hotspot.
- **Kým beží hotspot**, box nehľadá Wi-Fi, lebo jedna anténa nevie byť hotspot a klient naraz. Na Wi-Fi sa vráti po `dmxbox wifi connect` alebo po reštarte v dosahu známej siete.

Ak sa na box nedá pripojiť ani cez Wi-Fi, ani cez hotspot: počkaj 1–2 minúty po zapnutí. Ak to nepomôže, zapoj Ethernet a pripoj sa cez `ssh pidiman@fajny-dmx-box.local`.

### Bluetooth

```bash
dmxbox bt list                 # spárované a pripojené
dmxbox bt pair | hide          # viditeľný / skrytý
dmxbox bt forget MAC | forget-all
dmxbox bt disconnect [MAC]
dmxbox bt scan                 # nájde zariadenia v okolí (napr. BT reproduktor)
dmxbox bt connect MAC          # spárovať + dôverovať + pripojiť
dmxbox bt name "MENO"
dmxbox bt on | off
```

Pozor: vstavaný Bluetooth Pi 3B+ zvláda spoľahlivo jeden smer. Buď mobil → box, alebo box → BT reproduktor. Na oboje naraz:
- hudba cez **Spotify Connect** alebo **line-in** a BT len pre reproduktor, alebo
- druhý USB Bluetooth adaptér (jeden prijíma, druhý vysiela).

### Zvuk

```bash
dmxbox audio list              # výstupy a vstupy s ID
dmxbox audio out usb           # UCA202 → AUX reproduktora (odporúčané)
dmxbox audio out bluez         # BT reproduktor
dmxbox audio out 47            # podľa ID z audio list
dmxbox audio volume 80
dmxbox audio linein on | off
dmxbox audio delay 200         # svetlá oneskoriť za BT reproduktorom (0 pri kábli)
```

Analýza počúva to, čo ide na predvolený výstup (`source: auto` v `config.yaml`). Výstup sa určí pri štarte aplikácie, preto po `dmxbox audio out …` daj `dmxbox restart`.

Test bez zvukovej karty (zvuk len na analýzu, platí do reštartu):

```bash
pactl load-module module-null-sink sink_name=tichy sink_properties=device.description=Tichy
pactl set-default-sink tichy
dmxbox restart
```

### Spotify Connect

```bash
dmxbox spotify on | off | restart | status
```

Treba Spotify Premium a internet. V režime hotspot internet nie je, preto tam ostáva Bluetooth alebo line-in.

**Známy problém:** pri niektorých účtoch (hlavne založených od decembra 2025) Spotify odmieta librespotu kľúč skladby. Na tablete svieti CONNECTING a nič nehrá, v logu (`dmxbox logs librespot`) je `error audio key 0 1`. Oprava zatiaľ neexistuje ([librespot #1649](https://github.com/librespot-org/librespot/issues/1649)); použi Bluetooth alebo iný (starší) účet.

## 4. Konfiguračné súbory

| Súbor | Čo v ňom je | Po zmene |
| --- | --- | --- |
| `config.yaml` | audio, DMX ovládač a počet kanálov, port webu, light delay | `dmxbox restart` |
| `fixtures.yaml` | svetlá, DMX adresy, kanály | `dmxbox restart` |
| `presets.json` | 50 presetov z UI | nemeniť ručne |
| `security.json` | PIN appky (hash) a či sa vyžaduje | `dmxbox pin status / off / reset` |
| `scenario.json` | posledný scenár („Ako minule“) | nemeniť ručne |
| `/etc/bluetooth/main.conf` | BT meno a viditeľnosť | `dmxbox bt name` |
| NetworkManager (`dmx-hotspot` a Wi-Fi siete) | Wi-Fi a hotspot | `dmxbox wifi …`, `dmxbox hotspot …` |

## 5. Riešenie problémov

```bash
dmxbox status
dmxbox logs                    # aplikácia
dmxbox logs bt | wifi | librespot
vcgencmd get_throttled         # 0x0 = napájanie OK (inak slabý zdroj)
lsusb                          # 16c0:05dc = DMX dongle, 08bb:29xx = UCA202
```

| Príznak | Príčina / riešenie |
| --- | --- |
| `fajny-dmx-box.local` nefunguje | použi IP z `dmxbox status`, alebo na Androide `http://10.42.0.1` v hotspote (staršie Androidy nepoznajú `.local`) |
| BPM skáče, svetlá mimo rytmu | v UI ½× / 2× alebo TAP; skontroluj `dmxbox audio meter` |
| Svetlá svietia pred zvukom | BT reproduktor má oneskorenie, nastav `dmxbox audio delay 150–250` |
| Hotspot sa nezapne | `dmxbox logs wifi`; krajina Wi-Fi (`sudo raspi-config nonint get_wifi_country` musí vrátiť SK) |
| Mobil sa nevie spárovať | `dmxbox bt forget-all`, v mobile zabudni fajny-dmx-box a spáruj znova |
| V appke je len „Dummy Output“, skúška zvuku nič neukáže | box nevidí žiadny zvukový výstup: zapoj UCA202, alebo zapni jack: `sudo sed -i 's/^dtparam=audio=off/dtparam=audio=on/' /boot/firmware/config.txt && sudo reboot` |
| `throttled` ≠ 0x0 | slabý zdroj alebo kábel; Pi 3B+ potrebuje 5 V / 2,5 A |
