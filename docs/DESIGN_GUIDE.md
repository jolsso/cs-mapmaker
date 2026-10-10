# Designguide – gode de_-maps (CS 1.6)

Samlet 2026-10-10 fra research (kilder nederst) og egne målinger på 9 officielle maps. Bruges af generatoren (layout-forslag), Review (tjeklisten) og Decide (ændringsplaner). Tal markeret **[målt]** er kalibreret på officielle maps med vores egne værktøjer; tal markeret **[kilde]** er fra litteraturen.

## 1. Struktur: veje, chokepoints, forbindelser
1. **2–3 hovedveje** fra T-spawn mod sites – ikke flere end 3. [kilde: WoLD] dust2 har reelt 3 (long, mid, tunnels), inferno/train/italy 3, dust 2.
2. **Ét chokepoint pr. hovedvej**, placeret *før* sitet, så angriberne skal bryde igennem det. Chokepoints er korridorer, døre, tunneller, gyder eller "kamppladser" med varieret cover. [kilde: WoLD]
3. **Højst 1–2 indgange pr. chokepoint**, og hvis der er 2, skal forsvareren kunne se begge fra samme position (fx dust: Underpass og Up the Stairs). Brede chokepoints med flere skjulte veje giver angriberne for stor fordel. [kilde: WoLD]
4. **Forbindelsesveje** mellem hovedvejene, så T kan skifte rute uden at gå tilbage til spawn – men **aldrig gennem et chokepoint**. Ikke alle hovedveje behøver én (dust2 long har ingen). [kilde: WoLD]
5. **Flere CT-veje end T-veje ind på hvert site** (fx mirage: 3 CT-sidede mod 2 T-sidede pr. strategisk punkt). Og forsvarspositioner på sitet (steder at *stå*, ikke kun veje). Retakes bliver svære, når T har flere forsvarspositioner end CT har veje ind. [kilde: Game Developer, "pathways"]
6. **Ingen rute fra mid direkte ind i et spawn**, og ingen sigtelinje spawn-til-spawn. (Egen erfaring fra de_forge01-review.)

## 2. Timing (sekunder ved 250 units/s – kniv/C4, ReGameDLL)
Officielle maps, median spawn → site **[målt]**:

| | spænd på 9 officielle maps | typisk |
|---|---|---|
| T-spawn → site | 14–25 s | 17–20 s |
| CT-spawn → nærmeste site | 1,6–8,5 s | 2–8 s |
| CT-spawn → fjerneste site | 7–19 s | 8–15 s |
| CT's forspring (T-tid − CT-tid) | −0,7 – 24 s | 7–13 s |

Regler:
- **Forsvarerne skal nå chokepointet "et par sekunder" før angriberne**, så de kan stille op – og angriberne må aldrig kunne rushe igennem, mens forsvarerne endnu er på vej. [kilde: WoLD] Mål: CT-forspring til hvert site ≥ 3 s.
- **CT-spawn ligger asymmetrisk**: tæt på det ene site, længere fra det andet (dust2 4,5/8,5 s, inferno 7,4/9,1, cbble 2,7/14,7). En CT-spawn præcis midt mellem sites er usædvanlig.
- **T → site ≥ ~14 s**; under det er mappet for kompakt til at chokepoints og rotationer betyder noget. Over ~25 s bliver runderne lange.
- FITNESS' "tid til første kontakt 15–25 s" ligger i samme størrelsesorden.
- Validatoren måler dette for hvert map (`validation.json → stats.timings`).

## 3. Spillestile og rum
- **Bland afstande**: lange sigtelinjer til snipere (dust2 long, aztec bridge) *og* close-quarters (nuke hut/squeaky, inferno apartments). Hvert map bør have begge. [kilde: WoLD]
- **Højde giver fordel**: forsvareren på det høje sted ved et chokepoint får ekstra fordel; brug det bevidst. [kilde: WoLD]
- **Risiko/belønning**: hurtige, farlige ruter (aztec: drop fra broen) giver variation. [kilde: WoLD]
- **Sites**: cover til både forsvar og efter-plant; mindst ét genkendeligt landmark pr. site (ART_DIRECTION).

## 4. Entities og mål (CS 1.6)
- **Spawns: 16 pr. hold (32 i alt)** – maks. for spillet, og servere undgår maps med færre spawns end slots. [kilde: TWHL] Vores hårde krav er ≥ 10; generatoren laver 16.
- **Spawn-afstand: ~32 units fri plads på hver side og ~8 units over gulvet**; aldrig i geometri. [kilde: TWHL] Generatoren: 64 units mellem spawns, 48 fra væggene.
- **func_buyzone** pr. hold over spawn (team 1 = T, 2 = CT), placeret så man går ind i den. Uden func_buyzone laver spillet en lille zone ved hver spawn; med én gør det ikke. [kilde: TWHL]
- **Bomb sites**: func_bomb_target (brush) eller info_bomb_target (punkt). Aldrig i vand – en bombe plantet i vand eksploderer ikke. Markér sites med decals (`{target`, `{target2` fra decals.wad). [kilde: TWHL]
- **Map-typer** efter præfiks: de_ (defuse), cs_ (hostage, 4–5 hostages), as_, es_; community: fy_, aim_, awp_, ka_, kz_, surf_. [kilde: TWHL]

## 5. Mål og dimensioner (GoldSrc)
- Grænse: ±4096 units i alle retninger. [kilde: Valve wiki]
- Trin ≤ 18; hop 45; crouch-jump 63; crouch-loft ≥ 37; stå-loft ≥ 73; mindste passage 33 bred; max hul man går over 32; øjenhøjde ~64. [kilde: Valve wiki]
- Vægge 16 tykke; lofter ≥ 96 (spiller 72). [kilde: GameBanana] Vores normer: korridorer/døre ≥ 64 brede, 96–128 høje (bevidst strengere end Valve, se CALIBRATION.md).
- Hastigheder (units/s): kniv/pistoler/C4 250, M4A1 230, AK-47 221, AWP 210 (zoom 150), Scout 260. [kilde: ReGameDLL `weapons.h`]

## 6. Lys og ydelse
- Lys-brightness typisk 15–200 (200 = meget lyst). [kilde: GameBanana] Ingen mørke spilområder (FITNESS, fase 7).
- Hold r_speeds (wpoly) < ~800 i spilområder; flader spilleren aldrig kan se → NULL-tekstur; `func_detail` (VHLT/SDHLT) mod BSP-splits, men pas på wpoly. [kilde: TWHL Total Map Optimisation, Valve wiki]

## 7. Proces
- Skitsér mange grove layouts hurtigt; tegn fra angriberens perspektiv; iterér hovedveje → chokepoints → forbindelsesveje → sites → spawns. [kilde: WoLD]
- Byg blockout tidligt og **tid hver rute** fra begge spawns til chokepoints; justér, til tiderne passer. [kilde: WoLD] (Vi gør det automatisk: `stats.timings`.)
- Spil begge sider og notér chokepoint-kontrol og win-streaks. [kilde: WoLD] (Fase 4–5: bots + metrikker.)

## 8. Stilretninger at overveje
- **Realistiske steder** (Steam-guide "RF series"): maps bygget efter virkelige bygninger/kvarterer (Skt. Petersborg, Moskva) med fototeksturer. Passer til projektets oprindelige idé om virkelige steder (fx Skjern) – en mulig retning for tema ved Gate A / art pass.

## Kilder
- TWHL: [Tutorial: Counter-Strike mapping](https://twhl.info/wiki/page/Tutorial%3A_Counter-Strike_mapping)
- GameBanana: [A beginners guide to CS 1.6 mapping](https://gamebanana.com/tuts/11020)
- Steam: [CS 1.6 – RF series maps guide](https://steamcommunity.com/sharedfiles/filedetails/?id=3552719214)
- World of Level Design: [How to create competitive Counter-Strike gameplay map layouts](https://worldofleveldesign.com/categories/csgo-tutorials/csgo-how-to-design-gameplay-map-layouts.php), [Principles of choke point level design](https://worldofleveldesign.com/categories/csgo-tutorials/csgo-principles-choke-point-level-design.php)
- Game Developer: [A CS:GO level design concept – the pathways](https://gamedeveloper.com/design/a-cs-go-level-design-concept-the-pathways)
- Valve Developer Community: [GoldSrc Dimensions](https://developer.valvesoftware.com/wiki/GoldSrc_Dimensions), [VIS optimization](https://developer.valvesoftware.com/wiki/VIS_optimization)
- TWHL: [Total Map Optimisation Part 1 (wpoly, epoly)](https://twhl.info/wiki/page/Total_Map_Optimisation_Part_1_%28wpoly%2C_epoly%29/5903)
- ReGameDLL_CS: [`regamedll/dlls/weapons.h`](https://github.com/rehlds/ReGameDLL_CS/blob/master/regamedll/dlls/weapons.h) (våbenhastigheder)
