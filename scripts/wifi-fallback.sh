#!/usr/bin/env bash
# Po štarte počká na klientsku Wi-Fi; ak sa nepripojí, zapne hotspot dmx-hotspot.
set -u
WAIT=${WAIT:-30}

for _ in $(seq 1 "$WAIT"); do
  if nmcli -t -f TYPE,STATE,CONNECTION device | grep -q '^wifi:connected:' \
     && ! nmcli -t -f TYPE,STATE,CONNECTION device | grep -q ':dmx-hotspot$'; then
    echo "Wi-Fi klient pripojený, hotspot netreba"
    exit 0
  fi
  sleep 1
done

echo "Žiadna Wi-Fi sieť, zapínam hotspot DMX-BOX"
nmcli con up dmx-hotspot
