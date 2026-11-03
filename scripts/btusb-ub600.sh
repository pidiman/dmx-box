#!/bin/bash
# DMX-BOX: upravený ovládač btusb pre TP-Link UB600 (USB 37ad:0600, čip Realtek RTL8761B).
#
# Jadro tento dongle nepozná ako Realtek, preto doň nenahrá firmvér (rtl8761bu_fw.bin) a rádio
# nič nenájde. Skript stiahne zdroják btusb pre bežiace jadro Raspberry Pi, pridá doň 37ad:0600
# s príznakom BTUSB_REALTEK, skompiluje ho a nainštaluje do /lib/modules/<jadro>/updates/.
#
# Po aktualizácii jadra (apt upgrade) treba skript spustiť znova – inak sa použije pôvodný btusb.
#   bash ~/dmx-box/scripts/btusb-ub600.sh
#   bash ~/dmx-box/scripts/btusb-ub600.sh --remove     # späť na pôvodný ovládač
set -euo pipefail

KVER=$(uname -r)
DEST=/lib/modules/$KVER/updates/btusb.ko
say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

if [[ ${1:-} == --remove ]]; then
  sudo rm -f "$DEST" && sudo depmod -a && echo "Pôvodný btusb obnovený – reštartuj box."
  exit 0
fi

if modinfo btusb 2>/dev/null | grep -qi "v37ADp0600"; then
  echo "Ovládač btusb v tomto jadre ($KVER) už UB600 pozná – nič netreba, len znova zasuň dongle."
  exit 0
fi

say "Hlavičky jadra $KVER a kompilátor"
if [[ ! -d /lib/modules/$KVER/build ]]; then
  sudo apt-get update
  sudo apt-get install -y build-essential "linux-headers-$KVER" || sudo apt-get install -y build-essential linux-headers-rpi-v8
fi
[[ -d /lib/modules/$KVER/build ]] || { echo "Chýbajú hlavičky pre bežiace jadro $KVER. Spusti: sudo apt full-upgrade && sudo reboot, potom skript znova."; exit 1; }
command -v make >/dev/null || sudo apt-get install -y build-essential

W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
cd "$W"
BR="rpi-$(echo "$KVER" | cut -d. -f1-2).y"
BASE="https://raw.githubusercontent.com/raspberrypi/linux/$BR/drivers/bluetooth"

say "Zdroják btusb z raspberrypi/linux ($BR)"
curl -fsSLO "$BASE/btusb.c"
for h in $(grep -oE '#include "[^"]+"' btusb.c | cut -d'"' -f2); do
  curl -fsSLO "$BASE/$h"
done

if grep -qi "0x37ad, 0x0600" btusb.c; then
  echo "Novší btusb z $BR už UB600 obsahuje (príde aj s aktualizáciou jadra) – kompilujem ho pre $KVER."
fi

say "Pridávam TP-Link UB600 (37ad:0600) ako Realtek"
if ! grep -qi "0x37ad, 0x0600" btusb.c; then
  anchor=$(grep -n "USB_DEVICE(0x2357, 0x0604)" btusb.c | head -1 | cut -d: -f1)
  [[ -n $anchor ]] || anchor=$(grep -n "Realtek 8761BU" btusb.c | head -1 | cut -d: -f1)
  [[ -n $anchor ]] || { echo "Nenašiel som v btusb.c miesto pre Realtek zariadenia – zdroják sa zmenil."; exit 1; }
  sed -i "${anchor}i\\	{ USB_DEVICE(0x37ad, 0x0600), .driver_info = BTUSB_REALTEK |\\
						     BTUSB_WIDEBAND_SPEECH },  /* DMX-BOX: TP-Link UB600 */" btusb.c
fi
grep -n "0x37ad" btusb.c

say "Kompilácia (na Pi 3 asi 1–3 min)"
echo 'obj-m := btusb.o' > Makefile
make -C "/lib/modules/$KVER/build" M="$W" modules

say "Inštalácia do $DEST"
sudo install -D -m 644 btusb.ko "$DEST"
sudo depmod -a
modinfo btusb | grep -E "^filename|37AD" | head -3

say "Hotovo"
echo "Vytiahni a znova zasuň UB600 (alebo reštartuj box) a over:"
echo "  sudo dmesg | grep -i rtl      → RTL: loading rtl_bt/rtl8761bu_fw.bin"
