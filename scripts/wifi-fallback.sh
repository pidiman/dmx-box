#!/usr/bin/env bash
# Strážca Wi-Fi: keď box nie je pripojený na žiadnu známu Wi-Fi, zapne hotspot DMX-BOX.
# Beží stále (nie len pri štarte), takže reaguje aj na stratu Wi-Fi počas behu
# (presun na inú adresu, vypnutý router). Späť na Wi-Fi: dmxbox wifi connect "SSID"
# alebo reštart boxu v dosahu známej siete.
set -u
HOTSPOT=dmx-hotspot
BOOT_WAIT=${BOOT_WAIT:-40}     # po štarte: koľko s dať NetworkManageru na pripojenie
LOST_WAIT=${LOST_WAIT:-60}     # počas behu: koľko s bez Wi-Fi, kým zapne hotspot
STEP=5

state() {  # client | hotspot | none
  local line; line=$(nmcli -t -f TYPE,STATE,CONNECTION device | grep '^wifi:' | head -1)
  case "$line" in
    "wifi:connected:$HOTSPOT") echo hotspot ;;
    wifi:connected:*) echo client ;;
    *) echo none ;;
  esac
}

down=0
limit=$BOOT_WAIT
while true; do
  case "$(state)" in
    client)  down=0; limit=$LOST_WAIT ;;
    hotspot) down=0 ;;
    none)
      down=$((down + STEP))
      if (( down >= limit )); then
        echo "Žiadna Wi-Fi ${down} s → zapínam hotspot DMX-BOX"
        nmcli con up "$HOTSPOT" || echo "hotspot sa nepodarilo zapnúť"
        down=0
      fi ;;
  esac
  sleep "$STEP"
done
