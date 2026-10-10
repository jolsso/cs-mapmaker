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

## Åbne punkter til mennesket

- **Design-normerne er strengere end Valves egne maps.** Officielle maps har typisk passager på 40–56 units og mange lofter under 96. **Besluttet 2026-10-10: behold 64 / 96** for vores egne maps – bevidst lidt strengere end Valve (luft til bots og læsbarhed); det er warnings, så smalle steder kan stadig vælges bevidst.
- **Tid.** Validate tager 12 s på dust2 men ~5 min på store udendørsmaps (de_mon). Fint nu; kan optimeres med grovere grid til nåbarhed, hvis det bliver flaskehalsen.
