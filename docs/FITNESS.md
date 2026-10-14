# Fitness – hvad betyder "bedre"?

Loopet optimerer kun efter det, der står her. Tærsklerne spejles maskinlæsbart i `config/fitness.yaml`. Tallene er startværdier – justér efter erfaring.

## Hårde krav (skal være opfyldt, ellers er iterationen ugyldig)
| Krav | Kilde |
|---|---|
| Compile uden errors og uden leak | compile.json |
| Ingen engine-limit over 90 % | validation.json |
| Ingen off-grid vertices, alle brushes konvekse | validation.json |
| Korrekte entities: spawns pr. hold ≥ 10, bomb targets = 2 (de_), buyzones pr. hold ≥ 1 – eller ingen `func_buyzone` overhovedet (så laver spillet dem ved spawn); kun ét hold med buyzones er en fejl | validation.json |
| Alle spawns kan nå begge sites (graf-sti findes) | walkable-graf fra BSP (hull 1) i Validate/Review – før simulering; YaPB-grafen tjekkes igen i smoke-kørslen |
| Review bestået (ingen `critical`/`major` visuelle fund) | review.json – før simulering |

## Gameplay-mål (bot-data, ≥ 100 runder pr. måling)
| Metrik | Mål | Note |
|---|---|---|
| T-winrate | 45–55 % | Primær balance-metrik |
| Site-fordeling A/B (bomb plants) | 35–65 % | Begge sites skal bruges |
| Tid til første kontakt | 15–25 s | Fra rundestart |
| Døde zoner | < 20 % af gangbart areal med ~0 trafik | Ubrugt plads. Hævet fra 5 % 2026-10-10: bots følger deres navigationsgraf, og selv de_dust2 har 16 % (CALIBRATION.md) |
| Kill-koncentration | Ingen enkelt celle > 10 % af alle kills | Fanger "death traps" |
| Rundelængde (median) | 50–100 s | Afhænger af mp_roundtime |

**Statistik:** Rapportér altid konfidensinterval. Ændringer under støjniveauet tæller ikke som forbedring.

## Visuelle mål (Fase 7)
| Metrik | Mål |
|---|---|
| Mørke zoner (lysstyrke < tærskel i spilområde) | 0 |
| r_speeds wpoly pr. kameraview | < ~800 |
| Stilreview (Claude mod ART_DIRECTION.md) | Ingen "kritiske" fund |

## Samlet score
Kun gyldige iterationer scores. Vægtet afstand til målintervaller (0 = alle mål ramt). Vægte i `config/fitness.yaml`, start: balance 0.4, site-fordeling 0.2, kontakttid 0.15, døde zoner 0.15, kill-koncentration 0.1.

## Stopkriterier
Loopet stopper ved første af:
- Alle mål ramt i 2 på hinanden følgende målinger
- Ingen forbedring i score i 5 iterationer (plateau)
- Budget opbrugt: max iterationer (start: 20) eller max wall-clock
- Hårde krav fejler 3 gange i træk → stop og eskalér til menneske
- Review fejler 5 hurtige iterationer i træk → stop og eskalér til menneske
- En gate er nået (se ROADMAP.md)

## Rollback
Hvis en iteration forværrer scoren ud over støjniveau: gå tilbage til bedste version, og prøv en anden ændring.

## Låste beslutninger
Må **ikke** ændres af loopet uden menneskelig godkendelse. Udfyldes ved Gate A/B.

**Gate A godkendt 2026-10-10** for de_forge01 (layout v004): topologi og site-placeringer er låst i `config/fitness.yaml`. Tema vælges før art pass (fase 7).

```yaml
locked:
  theme: ""              # fx "industriel havn"
  map_type: "de"         # de / cs / aim / fy
  topology: ""           # fx "3 lanes, mid forbinder, sites i hver ende"
  site_locations: []     # grove koordinater/zoner
  landmarks: []          # navngivne landmarks der skal bestå
  geometry_frozen: false # true efter Gate B
```

## Tilladte ændringer (loopets værktøjskasse)
Låste beslutninger er pr. map: `locked_maps.<map>` i `config/fitness.yaml` gælder for det map, ellers `locked` (godkendt for de_forge01 ved Gate A).

Maskinlæsbart i `config/fitness.yaml` → `allowed_changes` (typer, påkrævede parametre, grænser). En plan med andre typer, for store ændringer eller ændringer der nævner låste landmarks/sites afvises af `mapforge/decide/policy.py`. Kræver en rettelse noget uden for værktøjskassen, skal planen eskalere (`escalate: true`).

- Flytte/forlænge/forkorte korridorer inden for ±256 units
- Tilføje/fjerne cover (kasser, vægge) inden for en zone
- Justere døråbninger og bredder
- Flytte spawns inden for spawn-zone
- Tilføje/fjerne en sekundær forbindelse (kun før Gate B, max 1 pr. iteration)
- Tilføje/fjerne område (kun på et menneskes annotation, før Gate B)
- Hævet cover (`z`): platforme, broer, stablede kasser / boost-spots (2026-10-11)
- Vindue mellem to områder (`add_window`, sill ≥ 64, evt. glas; max 1 pr. iteration), vent som forbindelse (`kind: vent`)
- Rampe (≤ 45°, ikke i spawn-områder), skrå væg / kile i et hjørne, stige (kun før Gate B)
- Dørblad i en åbning (`set_gate`: sliding / rotating / none); fjerne et element ved navn (`remove_element`)
- Pakke 2: ottekantet / knusbart cover (`add_cover shape/breakable`, `set_breakable`), lem mellem stablede etager (`add_hatch`, max 1 pr. iteration), vand (`add_water`), begge kun før Gate B
- Vinkler og niveauer (2026-10-14): bro tværs over et højt område (`add_bridge`, max 1 pr. iteration, kun før Gate B); `move_corridor` flytter også polygon-områder og skrå korridorer
- Lys: intensitet, farve, placering (Fase 7)

## Goodhart-advarsel
Bot-metrikker måler hvordan **bots** spiller. Hvis loopet forbedrer tallene ved at forenkle mappet (færre ruter, lige korridorer), er det et rødt flag – noter det i NOTES.md og eskalér.
