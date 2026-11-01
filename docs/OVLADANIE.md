# Ovládanie svetiel (web appka)

Návod na každý prvok ovládacej stránky `http://dmx-box.local` (v hotspote `http://10.42.0.1`). Stránku si na tablete pridaj na plochu, potom sa otvára ako appka na celú obrazovku.

Zmeny platia okamžite a vidia ich všetky pripojené tablety a mobily naraz. Nastavenia sa po reštarte boxu vrátia na predvolené; trvalo ich uložíš do **presetu**.

Svetlá v texte: **lišta** = MAX PartyBar4, **hlava** = moving head Fractal Gobo Spot, **Belka** = Light4Me BELKA (PAR, derby, laser, strobo/UV), **dym** = U'King fog machine.

---

## 1. Horný pruh

| Prvok | Význam |
| --- | --- |
| **● bodka** | bliká na každú dobu (beat). Ak bliká mimo hudby, oprav tempo (½× / 2× / TAP). |
| **BPM** | odhadnuté tempo. `---` = ticho. |
| **B / M / H** | úroveň basov, stredov a výšok (automaticky prispôsobená hlasitosti). |
| **👁 Viz** | otvorí virtuálne svetlá (`viz.html`) – kreslí presne to, čo ide do svetiel. Na testy bez svetiel. |
| **online / offline** | spojenie tabletu s boxom. Pri offline sa appka pripája znova sama. |
| **DMX / DMX dry** | zelené = DMX dongle pripojený, červené = nenájdený. `DMX dry` = beží naprázdno (bez donglu, na test). |

---

## 2. FX kolesá

Dve kolesá ako v myDMX GO. **Ťuknutie na efekt ho zapne a vypne AUTO** (ďalej svieti len zvolená kombinácia). Aktívny efekt je zvýraznený a jeho meno je pri nadpise; pri tichu je tam „ticho“.

### Koleso 1 – Farby (lišta, Belka PAR, derby, laser, farba hlavy)

| Efekt | Čo robí | Kedy sa hodí |
| --- | --- | --- |
| **Beat chase** | každú dobu nová farba z palety; lišta, PAR, derby a hlava majú posunuté farby, takže farby „bežia“ po svetlách. Jas pulzuje na dobu, laser každú 4. dobu. | univerzálny, pop, house |
| **Bass pump** | jas všetkých svetiel podľa sily basov; farba sa mení každý takt (4 doby). | hudba s výraznou basou, pomalšie časti |
| **Color step** | stála plná farba, mení sa každý takt; derby sa točí pomaly. | pokojnejšie skladby, „čistý“ vzhľad |
| **Dúha** | plynulý dúhový prechod, jedna otočka za 16 dôb; lišta, PAR, derby a hlava majú farby posunuté o tretinu kruhu. Ak je povolené UV, svieti jemný UV podklad. | chill, úvod, breakdown |
| **Split** | lišta a Belka PAR sa striedajú na dobu (jedna svieti, druhá zhasne); derby svieti na nepárne doby, laser každú 2. dobu. | rytmické skladby, rock, pop |
| **Kick flash** | biely záblesk na každý úder basového bubna (kick), inak tlmená farba; derby a laser (zelený) sa zapnú na silný úder. | DnB, techno, hip-hop – všade, kde je výrazný kick |
| **Build-up** | rýchlosť blikania rastie s energiou hudby (výšky + hlasitosť); keď je hudba naplno, zapne strobo Belky. | nástupy pred dropom, stúpajúce časti |
| **Derby party** | v hlasných častiach (refrén) derby naplno, laser na každú dobu; v tichších častiach derby tlmene a UV podklad. | refrény, párty vrcholy |

### Koleso 2 – Pohyb (moving head)

Motor hlavy nestíha plynulé rýchle pohyby, preto rýchle efekty **skáču medzi pozíciami** na dobu a plynulé pohyby sú pomalé (cez viac taktov). Tilt je obmedzený (v `fixtures.yaml`), aby hlava nesvietila do očí ani do stropu.

| Efekt | Čo robí |
| --- | --- |
| **Skoky** | skok na ďalšiu z 10 pozícií v miestnosti na každú dobu; gobo sa mení každý takt. Hlavný režim. |
| **Kruh** | pomalý kruh cez 8 dôb, otvorené svetlo bez gobo. Na pomalú hudbu. |
| **Sweep** | pan zľava doprava a späť na každú dobu. |
| **Tilt** | hore-dole na každú dobu, pan sa posunie každý takt. |
| **Snap** | náhodná pozícia a gobo každé 2 doby; na kick sa rozsvieti naplno. |
| **Nad hlavy** | pomalý plynulý pohyb nad hlavami ľudí (16 dôb), rotujúce gobo. |
| **Gobo beat** | hlava stojí, na každú dobu iné gobo; na silný kick gobo zatrasie. |
| **Stoj** | hlava stojí v strede a svieti. |

---

## 3. Tempo a AUTO

| Tlačidlo | Význam |
| --- | --- |
| **AUTO** | zapnuté (ružové) = box sám strieda dvojice efektov podľa **štýlu hudby** a reaguje na časti skladby (breakdown, build, drop). Vypnuté = svieti len efekt zvolený na kolesách. Ťuknutie na koleso AUTO vypne, výber štýlu ho zapne. |
| **8 / 16 / 32 taktov** | ako často AUTO mení dvojicu efektov. 16 = predvolené tempo štýlu; 8 = 2× častejšie, 32 = 2× zriedkavejšie. (DnB a hip-hop menia dvojice samy častejšie, chill zriedkavejšie.) |
| **½×** | odhadnuté BPM je dvojnásobné (napr. ukazuje 174 namiesto 87) – vydelí ho dvomi. |
| **2×** | odhadnuté BPM je polovičné (napr. 87 pri DnB 174) – vynásobí ho dvomi. |
| **TAP** | ťukaj do rytmu: každé ťuknutie nastaví začiatok doby, po 3 ťuknutiach sa vypočíta BPM. Pauza > 2 s začne počítať odznova. |
| **A** | vráti automatické BPM. |

Pozor: **½×, 2× a TAP tempo zamknú** – box ho prestane meniť, aj keď príde iná skladba. Pri ďalšej skladbe ťukni **A**.

---

## 4. Štýl hudby

| Prvok | Význam |
| --- | --- |
| **AUTO** | box sám rozpozná žáner (po 10–15 s skladby) a podľa neho svieti. Štýl mení až keď iný vyhráva aspoň 8 s, aby svetlá neskákali. |
| **Pop / DnB / Techno / House / Hip-hop / Chill** | pevne zvolený štýl, rozpoznávanie sa ignoruje. Pri nadpise je „(pevne)“. Ťuknutie zapne aj AUTO efekty. |
| **rozpoznané: … %** | čo by box zvolil sám a ako si je istý. Zobrazuje sa aj pri pevnom štýle. |
| **štítok vpravo** | časť skladby: **hrá** (normálne), **breakdown** (modrý – tichšia časť bez bicích), **build-up XX %** (oranžový – rastie napätie), **DROP** (ružový – skladba nabehla naplno). |

### Čo robia štýly

| Štýl | Paleta | Efekty, ktoré strieda | Laser | Derby | Strobo / dym na drop |
| --- | --- | --- | --- | --- | --- |
| **DnB** | fire (červená, oranžová) | Kick flash + Snap, Split + Tilt, Beat chase + Sweep, Derby party + Snap; mení každých 8 taktov, tvrdšie prechody | áno | áno | áno / áno |
| **Techno** | ice (biela, modrá) | Beat chase + Sweep, Kick flash + Tilt, Color step + Skoky, Build-up + Sweep; menší pohyb | áno | nie | áno / áno |
| **House** | warm (teplé) | Bass pump + Sweep, Derby party + Kruh, Color step + Nad hlavy, Split + Tilt; mäkšie prechody | áno | áno | áno / áno |
| **Hip-hop** | urban (fialová, zlatá) | Kick flash + Gobo beat, Color step + Nad hlavy, Bass pump + Skoky, Split + Gobo beat; pomalší a menší pohyb, mení každých 8 taktov | nie | áno | áno / nie |
| **Chill** | cool (modrá, tyrkysová) | Dúha + Kruh, Split + Nad hlavy, Bass pump + Stoj; veľmi mäkké prechody, pomalý pohyb, mení každých 32 taktov | nie | nie | nie / nie |
| **Pop** | party (pestrá) | všetky kombinácie (Beat chase + Skoky, Split + Sweep, …) | áno | áno | áno / áno |

### Časti skladby (len pri zapnutom AUTO)

| Časť | Čo robia svetlá |
| --- | --- |
| **breakdown** | tlmené farby, pomalý pohyb, bez lasera, derby a stroboskopu; Belka svieti UV podkladom (ak je UV povolené). |
| **build-up** | jas lišty rastie, Belka strobo postupne zrýchľuje (od 25 % buildu, ak štýl dovoľuje strobo). |
| **DROP** | prvý úder po tichšej časti: plný jas, strobo na 1 dobu a výstrek dymu (ak je zapnutý **Auto dym**). Potom 8 dôb efekt štýlu pre drop. |

---

## 5. Veľké tlačidlá

| Tlačidlo | Ako funguje |
| --- | --- |
| **STROBO** | **drž** – kým držíš, bliká všetko: lišta (strobo makro), Belka strobo naplno, hlava strobo a plný jas. Pustíš = späť na efekt. Funguje aj pri tichu. |
| **DYM** | **drž** – kým držíš, ide dym, najviac 10 s. Po každom výstreku je **30 s pauza** (ochrana ohrievača a miestnosti) – tlačidlo zošedne a ukazuje odpočet `⏳ 25 s`. Po pauze treba tlačidlo pustiť a stlačiť znova. Pod nápisom: `pripravený` / `ide` / odpočet. Ak dymostroj nie je v `fixtures.yaml`, tlačidlo sa skryje. |
| **BLACKOUT** | **prepínač** – všetko zhasne a dym sa zastaví. Hlava sa postaví do stredu. Druhé ťuknutie vráti svetlá. Má prednosť pred všetkým (aj pred STROBO). |

---

## 6. Posuvníky

| Posuvník | Význam |
| --- | --- |
| **Master** | celkový jas všetkých svetiel (0–100 %). Nemení farby ani pohyb. |
| **Veľkosť** | rozsah pohybu hlavy: vľavo = malé pohyby okolo stredu, vpravo = celá miestnosť. V AUTO ho štýl ešte prispôsobí (chill, hip-hop menšie). |
| **Mäkkosť** | ako rýchlo jas po údere dozneje: vľavo = ostré krátke záblesky, vpravo = mäkké dlhé prechody. V AUTO ho štýl posunie (DnB tvrdšie, chill mäkšie). |
| **Rýchlosť ½× / 1× / 2×** | efekty bežia polovičnou, normálnou alebo dvojnásobnou rýchlosťou voči tempu. BPM to nemení (na to sú ½× / 2× pri tempe). Napr. pri pomalom hip-hope 2× = živšie svetlá. |

---

## 7. Paleta a vlastná farba

| Prvok | Význam |
| --- | --- |
| **podľa štýlu** | farby vyberá štýl hudby (len pri AUTO). Predvolené. |
| **party** | červená, ružová, modrá, tyrkysová, zelená, oranžová |
| **cool** | modrá, tyrkysová, fialová, svetlomodrá |
| **warm** | červená, oranžová, ružovočervená, zlatá |
| **ice** | biela, svetlomodrá, modrá, tyrkysová |
| **fire** | červená, oranžová, žltooranžová |
| **urban** | fialová, zlatá, purpurová, tmavomodrá |
| **Vlastná farba** | výber farby – **všetky svetlá** (lišta, PAR, derby, hlava) svietia touto farbou, efekty riadia už len jas a pohyb. Lišta svieti aspoň na 80 %. |
| **Zrušiť** | vráti farby z palety. |

Ťuknutie na konkrétnu paletu vypne „podľa štýlu“ (paleta ostane pevná aj pri zmene štýlu).

---

## 8. Presety

Mriežka 1–50. Preset = uložený „vzhľad“.

| Akcia | Výsledok |
| --- | --- |
| **ťuk** | načíta preset (prázdny ohlási „podrž pre uloženie“) |
| **podrž ~0,7 s** | uloží aktuálny stav do slotu (prepíše starý) |
| zvýraznené číslo | slot je obsadený |

Preset ukladá: oba FX, AUTO a počet taktov, štýl hudby, paletu (aj „podľa štýlu“), Master, Veľkosť, Mäkkosť, Rýchlosť, Laser, UV a Auto dym. **Neukladá**: Blackout, Strobo, vlastnú farbu, light delay, line-in a dĺžku výstreku.

Tip: preset 1 = „Párty AUTO“ (AUTO, štýl AUTO, paleta podľa štýlu), preset 2 = „Večera“ (Chill, Master 40 %), preset 3 = „Len farby“ (bez AUTO, Color step + Stoj).

---

## 9. Nastavenia (rozbaľovacie dole)

| Nastavenie | Význam |
| --- | --- |
| **Light delay 0–500 ms** | oneskorí svetlá voči zvuku. Pri reproduktore na kábli = 0. Pri **Bluetooth reproduktore** zvuk mešká ~150–250 ms – nastav tak, aby záblesky sedeli s basou. |
| **Laser** | povolí laser Belky. Vypnuté = laser nikdy (má prednosť pred efektmi aj štýlom). |
| **UV podklad (Belka)** | povolí stály UV, keď nebliká strobo (Belka má strobo a UV v jednom module). |
| **Line-in (UCA202 IN)** | hudba z kábla (DJ pult, PC) do vstupu UCA202 ide do reproduktora a box ju analyzuje. Vypni, keď hrá BT alebo Spotify. |
| **Auto dym na drop** | výstrek dymu pri drope (ak ho štýl dovoľuje; nie pri chill a hip-hope). Platí aj 30 s pauza. |
| **Dĺžka auto výstreku 1–8 s** | ako dlho trvá auto výstrek. |

---

## 10. Ticho

Keď hudba 4 s nehrá, box prejde do kľudového režimu: lišta pomaly „dýcha“ tlmenou farbou z palety, ostatné svetlá zhasnú, hlava sa postaví do stredu. Pri ďalšej skladbe sa efekty spustia samy. STROBO funguje aj počas ticha.

---

## Poradie priorít

Keď sa nastavenia „bijú“, platí (vyššie vyhráva):

1. **BLACKOUT**
2. **STROBO** (držané)
3. **Vlastná farba**
4. vypínače **Laser / UV / Auto dym** v nastaveniach
5. **časť skladby** (breakdown / build / drop – len AUTO)
6. **štýl hudby** (len AUTO)
7. **FX kolesá** + Veľkosť, Mäkkosť, Rýchlosť
8. **Master** (jas všetkého)
