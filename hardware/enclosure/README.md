# Krabička DMX boxu (3D tlač)

Model je generovaný v Blenderi skriptom `dmxbox_enclosure.py` (`pip install bpy`):

```bash
python3 dmxbox_enclosure.py          # Raspberry Pi 3B+
python3 dmxbox_enclosure.py --pi4    # Raspberry Pi 4 (iné porty)
```

Výstup v `out/`: `dmxbox_case_pi3.stl` / `dmxbox_case_pi4.stl`, `dmxbox_lid.stl` (veko je už otočené na tlač),
`.blend` a náhľady.

| | |
|---|---|
| Vonkajší rozmer | 132,8 × 64,8 × 44,8 mm (s vekom) |
| Steny / dno / veko | 2,4 mm |
| Pi | 4× stĺpik 5 mm, skrutky M2.5 × 6 (samorezné do Ø2,2) |
| Veko | 4× M3 × 8 so zápustnou hlavou (samorezné do Ø2,5) |
| XLR | panelová samica D-typ (Neutrik NC3FD-L-1 a kompatibilné), otvor Ø24, 2× M3 |
| MAX485 | lôžko 14,6 mm medzi lištami, modul pozdĺž, prilepiť obojstrannou páskou |
| Displej | 2,2" TFT 240×320 ILI9341 SPI (doska 67,2 × 40,1 mm) – okno 46,7 × 35,4 mm so skosením, rámik + 4 stĺpiky M2 pod vekom (`DISP_HOLE` over na module) |
| Gombík | rotačný enkóder s tlačidlom, otvor Ø7,4 mm, matica zvonka |

Tlač: PETG alebo PLA, 0,2 mm, 3 perimetre, 15–20 % výplň, bez podpier (krabica dnom dole, veko nápisom dole).

## Zapojenie na GPIO (40-pin)

| Modul | Pin modulu | Pin Pi | GPIO |
|---|---|---|---|
| MAX485 | VCC / GND / DI / DE+RE | 2 / 6 / 8 / 4 | 5V / GND / GPIO14 TX / 5V |
| Displej ILI9341 | VCC | 1 | 3,3V |
| | GND | 20 | GND |
| | CS | 24 | GPIO8 (CE0) |
| | RESET | 22 | GPIO25 |
| | DC | 18 | GPIO24 |
| | SDI (MOSI) | 19 | GPIO10 |
| | SCK | 23 | GPIO11 |
| | LED | 12 | GPIO18 (PWM jas) |
| | SDO (MISO) | – | nezapájať |
| Enkóder | + / GND | 17 / 14 | 3,3V / GND |
| | CLK / DT / SW | 11 / 13 / 15 | GPIO17 / GPIO27 / GPIO22 |

`/boot/firmware/config.txt`: `dtparam=spi=on`. Displej má pin header na pravom konci (bližšie k Pi) –
najlepšie zahnutý (90°) alebo prispájkované kábliky, rovné Dupont konektory trčia ~20 mm dole.
