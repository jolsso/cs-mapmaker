# Kalibrering af Validate (fase 1b)

Kørt 2026-10-10 med `./mf validate:refs` på alle de_-referencemaps: 16 officielle fra den lokale CS 1.6-installation + 2 community-maps (de_cold, de_mon) i `test_maps/`. Kun statistik står her; selve mapsene committes aldrig.

## Resultat

| Map | Tid (s) | Errors | Warnings | Spawns der når site 1 / 2 (T, CT) | Design-normer (info): smalle / lave clusters |
|---|---:|---:|---:|---|---|
| de_airstrip | 88 | 0 | 2 (limit-headroom) | alle / alle | 17 / 73 |
| de_aztec | 39 | 0 | 0 | alle / alle | 3 / 25 |
| de_cbble | 51 | 0 | 0 | alle / alle | 9 / 14 |
| de_chateau | 36 | 0 | 2 (limit-headroom) | alle / alle | 7 / 72 |
| de_cold | 25 | 0 | 0 | alle / alle | 1 / 5 |
| de_dust | 19 | 0 | 0 | alle / alle | 9 / 18 |
| de_dust2 | 12 | 0 | 0 | alle / alle | 6 / 17 |
| de_inferno | 31 | 0 | 0 | alle / alle | 18 / 35 |
| de_mon | 315 | 0 | 0 | alle / alle | 3 / 16 |
| de_nuke | 42 | 0 | 0 | alle / alle | 6 / 21 |
| de_piranesi | 58 | 0 | 1 (limit-headroom) | alle / alle | 5 / 40 |
| de_prodigy | 16 | 0 | 0 | alle / alle | 7 / 41 |
| de_storm | 38 | 0 | 0 | alle / alle | 12 / 14 |
| de_survivor | 38 | 0 | 0 | alle / alle | 5 / 17 |
| de_torn | 66 | 0 | 2 (limit-headroom) | alle / alle | 4 / 30 |
| de_train | 16 | 0 | 0 | alle / alle | 12 / 5 |
| de_vertigo | 60 | 0 | 0 | alle / alle | 8 / 28 |

de_queens_v1 (custom map i installationen, 0 bomb targets, 2 spawns pr. hold) er udeladt: det er ikke et de_-map i praksis.

**Accept for fase 1b opfyldt:** 0 errors på alle de_-referencemaps. De resterende warnings er FITNESS' headroom-politik (> 90 % af en limit, fx planes 97–99,5 % på airstrip/chateau) – korrekt for egne maps, kun warning for referencemaps, som vi ved virker.

## Hvad kalibreringen ændrede

| Fund på kendte maps | Ændring |
|---|---|
| de_nuke, de_cold har ingen `func_buyzone` | Ingen buyzones overhovedet = implicitte (spillet laver dem ved spawn). Kun ét hold med buyzones er en fejl. |
| de_prodigy, de_torn har 4 `func_bomb_target` | Brushes inden for 128 units er ét site. |
| de_torn: 11067 texinfo, de_chateau: 2,29 MB lightmaps – over HLSDK-limits | HLSDK `MAX_MAP_*` er compiler-limits. texinfo → 32767, models → 512, lighting → compiler-grænse. > 100 % = error, > 90 % = headroom-politik. |
| de_mon: 4 CT-spawns kan kun komme videre med et hop | Walk-grafen fik hop (duck-jump ≤ 54) og crouch (vents). |
| de_prodigy: en spawn 4 units fra en væg blev snappet ind i væggen | Seed prøver de omkringliggende grid-punkter. |
| Korridor-checket fandt 20+ "smalle passager" på alle maps – mest kanter og catwalks | En passage skal have væg på begge sider; kant mod et fald tæller ikke. Clusters < 4 celler ignoreres. På referencemaps er normerne info. |
| Tæt scanning af hele world-bounds: ~1,9 mia. opslag på de_mon | Erstattet af flood-fill fra spawns (kun nåbart område). |

## Mørke zoner (fase 3)

Lightmap-luma (0–255) af gulvet under hver gangbar celle (16×16 units), clusters ≥ 16 celler (64×64 units):

| Map | luma < 8 | < 12 | < 16 | < 20 | < 30 |
|---|---:|---:|---:|---:|---:|
| de_dust2 | 2 | 5 | 6 | 9 | 12 |
| de_nuke | 2 | 4 | 10 | 20 | 34 |
| de_inferno | 0 | 1 | 1 | 1 | 1 |
| de_aztec | 0 | 0 | 0 | 0 | 4 |
| de_cbble | 1 | 2 | 3 | 3 | 8 |
| de_train | 0 | 1 | 2 | 4 | 13 |
| de_dust | 0 | 2 | 6 | 7 | 6 |
| de_vertigo | 2 | 2 | 10 | 19 | 31 |
| de_cold | 6 | 6 | 7 | 7 | 9 |

Valgt: **luma < 10**. På dust2 giver det 4 zoner – B-tunnellerne, trappen ved B, under taget ved CT-dør og en passage på T-siden – dvs. Valves bevidst mørke steder. Officielle maps har altså 0–6 mørke zoner; FITNESS' mål om 0 gælder vores egne maps i art pass (fase 7).

## Bot-metrikker (fase 5)

Sanity-check: 50 YaPB-runder (5 mod 5, difficulty 3, timescale 4) på de_dust2 mod de_forge01:

| Metrik | de_dust2 | de_forge01 | Mål (FITNESS) |
|---|---:|---:|---|
| T-winrate | 0,48 [0,35–0,62] | 0,46 [0,33–0,60] | 0,45–0,55 |
| Andel plants på A | 0,36 (28 plants) | 0,63 (27 plants) | 0,35–0,65 |
| Første kontakt, median | 16,6 s | 16,8 s | 15–25 s |
| Rundelængde, median | 58 s | 70 s | 50–100 s |
| Kill-koncentration, største 128-celle | 3 % | 6 % | < 10 % |
| Døde zoner (64-celler, < 2 % af middel) | **15,8 %** | 15,0 % | < 5 % |
| Kills pr. runde | 5,9 | 6,2 | – |

Tallene for dust2 er plausible (T ≈ halvdelen, bots foretrækker B på dust2, kontakt efter ~17 s). **Døde zoner kan ikke nås med bot-data:** et kendt godt map ligger på ~16 %, fordi YaPB går fra node til node i sin graf og aldrig bruger hjørner og kanter. Målet < 5 % er sat ud fra menneskelig trafik. **Besluttet 2026-10-10: målet er nu ≤ 20 %** for bot-data (`config/fitness.yaml`).

dust2's bomb targets har ingen navne, og det første i entity-listen er B. Navnene står i `config/pipeline.yaml` → `analyze.site_names`.

## YaPB-grafen (fase 6)

Fundet 2026-10-10 under loop-testen på de_tilt01: med YaPB's standard `yb_graph_analyze_distance 64` stoppede den automatiske analyse ved et node-loft (graferne var ~52 KB på både de_forge01 og de_tilt01), og **et helt bomb site manglede i bots' navigation**: i 9 smoke-runder var ingen bot – heller ikke CT, der spawner ved siden af – inde på A. Med 96 units mellem noderne (24 KB-graf) bruges begge sites (A 309, B 196 samples på 3 runder).

| | distance 64 | distance 96 |
|---|---|---|
| de_tilt01 (med CT-dør til B) | A 0 / B 659 samples (9 runder) | A 309 / B 196 (3 runder) |

Konsekvenser:
- `simulate.yapb.yb_graph_analyze_distance: 96`; graf-cachen afhænger nu af analyse-indstillingerne.
- **Målingerne af de_forge01 fra fase 4/5 (T-winrate 0,46) blev lavet med en afkortet graf og er ikke retvisende.** Med rigtig graf vinder T 80 % på de_tilt01 med CT-døren genskabt, altså samme layout som de_forge01 bortset fra dørbredden. de_forge01 skal måles igen.
- de_dust2 brugte YaPB's medfølgende graf og er ikke påvirket.
- **Opfølgning samme dag:** 96 var heller ikke sikker. På iteration 003 af de_tilt01 (kun en kasse fjernet) efterlod 96 hele vestsiden umappet, mens 80 og 112 dækkede begge sites. Analysen er deterministisk pr. .bsp + afstand, men følsom over for små geometriændringer. Løsning: smoke verificerer grafen, og ved et site uden besøg laves grafen om med næste afstand (`graph_distances: [96, 80, 112, 128]`).
- Smoke: 3 runder er for få til "begge sites nået", fordi bots ofte vælger samme site flere runder i træk. Smoke spiller nu op til 6 runder mere, før et site erklæres unået (`smoke_extra_rounds`).

## Åbne punkter til mennesket

- **Design-normerne er strengere end Valves egne maps.** Officielle maps har typisk passager på 40–56 units og mange lofter under 96. **Besluttet 2026-10-10: behold 64 / 96** for vores egne maps – bevidst lidt strengere end Valve (luft til bots og læsbarhed); det er warnings, så smalle steder kan stadig vælges bevidst.
- **Døde zoner:** besluttet 2026-10-10 at hæve målet til ≤ 20 % for bot-data (dust2: 16 %).
- **Tid.** Validate tager 12 s på dust2 men ~5 min på store udendørsmaps (de_mon). Fint nu; kan optimeres med grovere grid til nåbarhed, hvis det bliver flaskehalsen.
