#!/usr/bin/env bash
# DMX-BOX inštalácia na Raspberry Pi OS Lite 64-bit (Bookworm).
# Spúšťaj ako bežný používateľ (nie root) z klonu repa:
#   sudo apt-get install -y git
#   git clone https://github.com/pidiman/dmx-box ~/dmx-box && cd ~/dmx-box
#   ./install.sh --hotspot-pass 'tajne-heslo' [--spotify]
#
# Parametre (všetky voliteľné, skript sa dá spustiť znova – nič nerozbije):
#   --name MENO              meno boxu: v sieti (http://MENO.local), Wi-Fi hotspot, Bluetooth
#                            aj Spotify (predvolene fajny-dmx-box; malé písmená, číslice, pomlčky)
#   --hotspot-pass HESLO     záložný hotspot MENO, keď nie je známa Wi-Fi (min. 8 znakov)
#   --spotify                Spotify Connect MENO (librespot; treba Premium)
#   --no-airplay             bez AirPlay prijímača (predvolene je AirPlay zapnutý)
#   --wifi SSID HESLO        pridať Wi-Fi sieť (dá sa zopakovať pre viac sietí)
#   --country KÓD            krajina Wi-Fi, potrebná pre 5 GHz (predvolene SK)
#   --hostname / --bt-name   iné meno len pre sieť / len pre Bluetooth
#   --no-jack                vypnúť 3,5 mm jack na Pi (pri UCA202 menej šumu); predvolene ostáva zapnutý
# Neskoršie zmeny bez reinštalácie: príkaz `dmxbox help` (docs/PREVADZKA.md).
set -euo pipefail

HOTSPOT_PASS=""
SPOTIFY=0
AIRPLAY=1
NAME="fajny-dmx-box"
HOSTNAME_NEW=""
COUNTRY="SK"
BT_NAME=""
NO_JACK=0
WIFI=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hotspot-pass) HOTSPOT_PASS="$2"; shift 2 ;;
    --spotify) SPOTIFY=1; shift ;;
    --no-airplay) AIRPLAY=0; shift ;;
    --wifi) WIFI+=("$2" "$3"); shift 3 ;;
    --name) NAME="$2"; shift 2 ;;
    --hostname) HOSTNAME_NEW="$2"; shift 2 ;;
    --country) COUNTRY="$2"; shift 2 ;;
    --bt-name) BT_NAME="$2"; shift 2 ;;
    --no-jack) NO_JACK=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "neznámy parameter: $1 (./install.sh --help)"; exit 1 ;;
  esac
done
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$ ]] || { echo "Meno: malé písmená, číslice a pomlčky (napr. fajny-dmx-box)."; exit 1; }
HOSTNAME_NEW="${HOSTNAME_NEW:-$NAME}"
BT_NAME="${BT_NAME:-$NAME}"
[[ -z "$HOTSPOT_PASS" || ${#HOTSPOT_PASS} -ge 8 ]] || { echo "Heslo hotspotu musí mať aspoň 8 znakov."; exit 1; }

[[ $EUID -eq 0 ]] && { echo "Nespúšťaj ako root, sudo si skript pýta sám."; exit 1; }
REPO="$(cd "$(dirname "$0")" && pwd)"
[[ "$REPO" == "$HOME/dmx-box" ]] || echo "Pozor: repo nie je v ~/dmx-box, uprav WorkingDirectory v systemd/dmxbox.service."
say() { printf '\n\033[1;35m== %s\033[0m\n' "$*"; }

say "Balíky"
sudo apt-get update
sudo apt-get install -y git avahi-daemon \
  pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth \
  bluez bluez-tools pulseaudio-utils \
  python3-numpy python3-yaml python3-usb python3-pip
pip install --break-system-packages --user fastapi "uvicorn[standard]"

say "uDMX (Lixada, 16c0:05dc) – prístup bez roota"
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="16c0", ATTR{idProduct}=="05dc", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/50-udmx.rules >/dev/null
sudo udevadm control --reload && sudo udevadm trigger

CFG=/boot/firmware/config.txt
[[ -f $CFG ]] || CFG=/boot/config.txt
if [[ $NO_JACK -eq 1 ]]; then
  say "Vypnúť 3,5 mm jack na Pi (zvuk len cez UCA202)"
  if grep -q '^dtparam=audio=on' "$CFG"; then
    sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CFG"
  elif ! grep -q '^dtparam=audio=off' "$CFG"; then
    echo 'dtparam=audio=off' | sudo tee -a "$CFG" >/dev/null
  fi
else
  say "3,5 mm jack na Pi zapnutý (reproduktor sa dá zapojiť aj bez UCA202)"
  if grep -q '^dtparam=audio=off' "$CFG"; then
    sudo sed -i 's/^dtparam=audio=off/dtparam=audio=on/' "$CFG"
  elif ! grep -q '^dtparam=audio=on' "$CFG"; then
    echo 'dtparam=audio=on' | sudo tee -a "$CFG" >/dev/null
  fi
fi

say "Bluetooth: $BT_NAME ako reproduktor"
sudo BT_NAME="$BT_NAME" python3 - <<'PY'
import os, re
p = "/etc/bluetooth/main.conf"
s = open(p).read()
want = {"Name": os.environ["BT_NAME"], "Class": "0x200414", "DiscoverableTimeout": "0",
        "AlwaysPairable": "true", "JustWorksRepairing": "always"}
for k, v in want.items():
    pat = re.compile(rf"^#?\s*{k}\s*=.*$", re.M)
    line = f"{k} = {v}"
    s = pat.sub(line, s, count=1) if pat.search(s) else s.replace("[General]", f"[General]\n{line}", 1)
open(p, "w").write(s)
PY
sudo install -m 644 "$REPO/systemd/bt-agent.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bluetooth bt-agent

say "Web na porte 80 bez roota"
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-dmxbox.conf >/dev/null
sudo sysctl -p /etc/sysctl.d/99-dmxbox.conf

say "Hostname a Wi-Fi krajina"
sudo hostnamectl set-hostname "$HOSTNAME_NEW"
sudo sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME_NEW/" /etc/hosts
sudo raspi-config nonint do_wifi_country "$COUNTRY" || true

for ((i = 0; i < ${#WIFI[@]}; i += 2)); do
  say "Wi-Fi: ${WIFI[i]}"
  sudo nmcli con delete "${WIFI[i]}" &>/dev/null || true
  sudo nmcli con add type wifi ifname wlan0 con-name "${WIFI[i]}" ssid "${WIFI[i]}" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "${WIFI[i+1]}" connection.autoconnect yes >/dev/null
done

say "Ovládanie systému z webu (Wi-Fi, hotspot, reštart) bez hesla"
# čítanie správ jadra bez sudo (strážca BT reproduktora rozpozná zamrznuté spojenie)
sudo usermod -aG systemd-journal "$USER" || true

SUDOERS=/etc/sudoers.d/dmxbox
sudo tee "$SUDOERS" >/dev/null <<EOF
# DMX-BOX web: len tieto príkazy bez hesla (install.sh)
$USER ALL=(root) NOPASSWD: /usr/bin/nmcli, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, \\
  /usr/bin/systemctl enable --now wifi-fallback, /usr/bin/systemctl disable --now wifi-fallback, \\
  /usr/bin/install -m 755 $REPO/scripts/dmxbox /usr/local/bin/dmxbox
EOF
sudo chmod 440 "$SUDOERS"
sudo visudo -cf "$SUDOERS" >/dev/null || { echo "Chyba v $SUDOERS, mažem"; sudo rm -f "$SUDOERS"; }

say "Captive portal: v hotspote sa appka otvorí sama po pripojení"
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
echo 'address=/#/10.42.0.1' | sudo tee /etc/NetworkManager/dnsmasq-shared.d/dmxbox-captive.conf >/dev/null

say "Príkaz dmxbox (správa Wi-Fi, BT, Spotify, audio)"
sudo install -m 755 "$REPO/scripts/dmxbox" /usr/local/bin/dmxbox

if [[ -n "$HOTSPOT_PASS" ]]; then
  say "Fallback hotspot $NAME (5 GHz, kanál 36)"
  nmcli -t -f NAME con show | grep -qx dmx-hotspot && sudo nmcli con delete dmx-hotspot
  sudo nmcli con add type wifi ifname wlan0 con-name dmx-hotspot ssid "$NAME" \
    802-11-wireless.mode ap 802-11-wireless.band a 802-11-wireless.channel 36 \
    ipv4.method shared ipv4.addresses 10.42.0.1/24 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$HOTSPOT_PASS" connection.autoconnect no
  sudo install -m 755 "$REPO/scripts/wifi-fallback.sh" /usr/local/bin/dmxbox-wifi-fallback
  sudo install -m 644 "$REPO/systemd/wifi-fallback.service" /etc/systemd/system/
  sudo systemctl daemon-reload && sudo systemctl enable wifi-fallback
  sudo systemctl restart wifi-fallback
else
  echo "Hotspot preskočený (pridaj --hotspot-pass 'heslo')."
fi

say "User služby (PipeWire beží aj bez prihlásenia)"
sudo loginctl enable-linger "$USER"
mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$REPO/systemd/dmxbox.service" "$HOME/.config/systemd/user/"

if [[ $AIRPLAY -eq 1 ]]; then
  say "AirPlay prijímač (shairport-sync) – v iPhone/iPade vyber $NAME"
  sudo apt-get install -y shairport-sync
  sudo systemctl disable --now shairport-sync || true   # systémová verzia nevidí user PipeWire
  mkdir -p "$HOME/.config"
  install -m 644 "$REPO/config/shairport-sync.conf" "$HOME/.config/shairport-sync.conf"
  install -m 644 "$REPO/systemd/airplay.service" "$HOME/.config/systemd/user/"
fi

if [[ $SPOTIFY -eq 1 ]]; then
  say "Spotify Connect (librespot)"
  curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
  sudo systemctl disable --now raspotify || true   # systémová verzia nevidí user PipeWire
  install -m 644 "$REPO/systemd/librespot.service" "$HOME/.config/systemd/user/"
fi

XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
systemctl --user daemon-reload
systemctl --user enable --now pipewire pipewire-pulse wireplumber
systemctl --user enable dmxbox
[[ $SPOTIFY -eq 1 ]] && systemctl --user enable --now librespot
[[ $AIRPLAY -eq 1 ]] && systemctl --user enable --now airplay

say "Hotovo"
cat <<EOF
Ďalej:
  1. sudo reboot   (potom: ssh $USER@$HOSTNAME_NEW.local)
  2. Zapoj UCA202 a Lixada:         dmxbox status
  3. Výstup zvuku na UCA202:        dmxbox audio out usb
  4. Test DMX:                      dmxbox test dmx walk all
  5. Test audia:                    dmxbox audio meter
  6. Spustenie a logy:              dmxbox start && dmxbox logs
  7. Ovládanie:                     http://$HOSTNAME_NEW.local
  Všetky príkazy: dmxbox help   |   návod: docs/PREVADZKA.md
EOF
