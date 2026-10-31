# Plán

## Ďalej (po príchode hardvéru)

- [ ] Nasadenie na Raspberry Pi 3B+ (`install.sh`), míľniky M0–M5 z [PROJEKT.md](PROJEKT.md)
- [ ] Overiť naživo: Belka UV (kanál 11 pri kanáli 12 = 0), parbar kanály 2–3, spot strobo/rýchlosť/program
- [ ] Doladiť efekty na skutočnej hudbe (vizualizácia `viz.html` + svetlá)

## Odložené: správa svetiel (pridať / odobrať / adresy z UI)

Cieľ: svetlá a adresy sa nastavujú z tabletu, dajú sa pridať nové modely aj viac kusov rovnakého svetla.

Dnes: adresu treba zmeniť v `fixtures.yaml` (`start:`), odobrať sa dá zmazaním bloku. Nové typy svetiel engine nepozná, lebo je naviazaný na mená `parbar`, `movinghead`, `belka`, `fog`.

1. **Knižnica profilov** `profiles/*.yaml`: jeden súbor na model (kanály, módy, rozsahy hodnôt). Prvé budú súčasné 4 svetlá.
2. **Rig** `rig.yaml`: zoznam kusov (profil, adresa, meno, poloha); rovnaký profil sa dá použiť viackrát.
3. **Engine podľa schopností:** RGB/RGBW farba, dimmer, pan/tilt, gobo, strobo, UV, laser, derby motor, dym. Efekty sa rozdelia medzi kusy, čo umožní chase medzi viacerými parmi a zrkadlový pohyb dvoch hláv.
4. **Stránka „Svetlá“ v PWA:** pridať svetlo z knižnice, adresa, meno, odobrať. Kontrola kolízií adries, mapa obsadených kanálov a tlačidlo **Test**, ktoré bliká vybraným svetlom.
5. **Editor profilu:** počet kanálov a funkcia každého kanála zo zoznamu (podľa manuálu).
6. **Vizualizácia** sa poskladá z rigu automaticky.
7. **DMX výstup** pošle len potrebný počet kanálov (zaokrúhlené na 8 kvôli uDMX).

Podmienka: súčasné nastavenie a presety ostanú funkčné; testy overia, že výstup pre súčasné 4 svetlá sa nezmení.

## Nápady

- AirPlay vstup (`shairport-sync`) pre iPhone/iPad
- Tap sync pre light delay pri Bluetooth reproduktore
- Ovládanie z Home Assistant (REST API už existuje)
