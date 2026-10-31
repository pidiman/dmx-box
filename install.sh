#!/usr/bin/env bash
# DMX-BOX inštalácia na Raspberry Pi OS Lite 64-bit (Bookworm).
# Spúšťaj ako bežný používateľ (nie root) z klonu repa:
#   git clone https://github.com/pidiman/dmx-box ~/dmx-box && cd ~/dmx-box
#   ./install.sh --hotspot-pass 'tajne-heslo' [--spotify]
set -euo pipefail

HOTSPOT_PASS=""
SPOTIFY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hotspot-pass) HOTSPOT_PASS="$2"; shift 2 ;;
    --spotify) SPOTIFY=1; shift ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "neznámy parameter: $1"; exit 1 ;;
  esac
done

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

say "Vypnúť onboard analógový zvuk (PWM)"
CFG=/boot/firmware/config.txt
[[ -f $CFG ]] || CFG=/boot/config.txt
if grep -q '^dtparam=audio=on' "$CFG"; then
  sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CFG"
elif ! grep -q '^dtparam=audio=off' "$CFG"; then
  echo 'dtparam=audio=off' | sudo tee -a "$CFG" >/dev/null
fi

say "Bluetooth: DMX-BOX ako reproduktor"
sudo python3 - <<'PY'
import re
p = "/etc/bluetooth/main.conf"
s = open(p).read()
want = {"Name": "DMX-BOX", "Class": "0x200414", "DiscoverableTimeout": "0",
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
sudo hostnamectl set-hostname dmx-box
sudo raspi-config nonint do_wifi_country SK || true

if [[ -n "$HOTSPOT_PASS" ]]; then
  say "Fallback hotspot DMX-BOX (5 GHz, kanál 36)"
  nmcli -t -f NAME con show | grep -qx dmx-hotspot && sudo nmcli con delete dmx-hotspot
  sudo nmcli con add type wifi ifname wlan0 con-name dmx-hotspot ssid DMX-BOX \
    802-11-wireless.mode ap 802-11-wireless.band a 802-11-wireless.channel 36 \
    ipv4.method shared ipv4.addresses 10.42.0.1/24 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$HOTSPOT_PASS" connection.autoconnect no
  sudo install -m 755 "$REPO/scripts/wifi-fallback.sh" /usr/local/bin/dmxbox-wifi-fallback
  sudo install -m 644 "$REPO/systemd/wifi-fallback.service" /etc/systemd/system/
  sudo systemctl daemon-reload && sudo systemctl enable wifi-fallback
else
  echo "Hotspot preskočený (pridaj --hotspot-pass 'heslo')."
fi

say "User služby (PipeWire beží aj bez prihlásenia)"
sudo loginctl enable-linger "$USER"
mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$REPO/systemd/dmxbox.service" "$HOME/.config/systemd/user/"

if [[ $SPOTIFY -eq 1 ]]; then
  say "Spotify Connect (librespot)"
  curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
  sudo systemctl disable --now raspotify || true   # systémová verzia nevidí user PipeWire
  install -m 644 "$REPO/systemd/librespot.service" "$HOME/.config/systemd/user/"
fi

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable --now pipewire pipewire-pulse wireplumber
systemctl --user enable dmxbox
[[ $SPOTIFY -eq 1 ]] && systemctl --user enable --now librespot

say "Hotovo"
cat <<EOF
Ďalej:
  1. sudo reboot
  2. Zapoj UCA202 a Lixada, potom:  lsusb
  3. Výstup zvuku na UCA202:        wpctl status && wpctl set-default <ID>
  4. Test DMX:                      python3 tools/dmx_test.py walk all
  5. Test audia:                    python3 tools/audio_meter.py
  6. Spustenie:                     systemctl --user start dmxbox && journalctl --user -u dmxbox -f
  7. Ovládanie:                     http://dmx-box.local
EOF
