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
| Vonkajší rozmer | 132,8 × 64,8 × 38,8 mm (s vekom) |
| Steny / dno / veko | 2,4 mm |
| Pi | 4× stĺpik 5 mm, skrutky M2.5 × 6 (samorezné do Ø2,2) |
| Veko | 4× M3 × 8 so zápustnou hlavou (samorezné do Ø2,5) |
| XLR | panelová samica D-typ (Neutrik NC3FD-L-1 a kompatibilné), otvor Ø24, 2× M3 |
| MAX485 | lôžko 14,6 mm medzi lištami, modul pozdĺž, prilepiť obojstrannou páskou |

Tlač: PETG alebo PLA, 0,2 mm, 3 perimetre, 15–20 % výplň, bez podpier (krabica dnom dole, veko nápisom dole).
