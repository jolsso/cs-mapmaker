# MapForge – CS 1.6-maps fra spec til spilbart map

MapForge er et automatiseret pipeline, der designer, compiler, tester og forbedrer Counter-Strike 1.6-maps (GoldSrc, `de_`). Et map beskrives som en YAML-spec over tomt rum. Generatoren bygger en forseglet Valve 220-`.map` ud fra den, og SDHLT compiler den. Bagefter validerer, renderer og vurderer pipelinen mappet, simulerer det med bots og retter layoutet i et loop, indtil målene er ramt. Mennesket sidder ved gates, ikke i hver iteration.

```
layout.yaml → generate → compile → validate → render → review ─┬─► simulate → analyze ─┐
     ▲                                                        └─► (review fejler) ─────┤
     └──────────────────────── apply ◄── decide ◄───────────────────────────────────────┘
```

## Kom i gang
Værten skal kun have **Docker**. Alt andet (Python, SDHLT-compilere, renderer, HLDS + YaPB-bots) kører i containere.

```bash
./mf test                          # pytest i forge-containeren (PowerShell: .\mf test)
./mf generate MAP=de_viaduct01     # layout.yaml → maps/de_viaduct01/src/de_viaduct01.map
./mf validate MAP=de_viaduct01     # compile + validering → build/de_viaduct01/validation.json
./mf render MAP=de_viaduct01       # top-down og kamera-renders → build/de_viaduct01/renders/
./mf simulate MAP=de_viaduct01     # bots på HLDS-servere → simulation.json
./mf loop MAP=de_viaduct01 -- --init   # det autonome forbedrings-loop
docker compose up -d site          # dashboard på http://localhost:8080
```

- `.map`-filerne genereres og er ikke versioneret. Kør `./mf generate` efter et frisk clone.
- Referencemaps (officielle maps fra din egen Half-Life-installation, `HL_DIR` i `.env`) bruges kun lokalt til kalibrering og committes aldrig.
- Første simulering bygger HLDS-imaget (SteamCMD henter ca. 1 GB anonymt).

Alle kommandoer står i [`CLAUDE.md`](CLAUDE.md) under "Kommandoer".

## Sådan ser et map ud
```yaml
name: de_viaduct01
areas:
  - {name: t_spawn, rect: [-768, -2560, 512, -1984], height: 256, outdoor: true, role: t_spawn}
  - {name: canal, rect: [-384, -1216, 384, 640], height: 384, outdoor: true, role: mid}
  - name: a_site                              # konveks polygon: skrå vægge i vilkårlig grid-vinkel
    poly: [[1184, 400], [1904, 400], [2304, 784], [2304, 1424], [1888, 1680], [1184, 1680]]
corridors:                                    # skrå korridor med rampe og døre i begge ender
  - {name: t_climb, from: [-560, -1968], to: [-1072, -496], width: 128, between: [t_spawn, b_gallery]}
bridges:                                      # dæk med rækværk tværs over kanalen
  - {name: canal_bridge, area: canal, axis: x, pos: -352, z: 176, width: 128}
doors:
  - {name: d_t_mid, between: [t_spawn, mid_s], width: 192}
sites: {A: a_site, B: b_site}
spawns: {T: {area: t_spawn}, CT: {area: ct_spawn}}
```

Specen beskriver kun tomt rum, og alt andet bliver solidt. Derfor kan et genereret map ikke lække, og alle vertices ligger på grid'et. Generatoren kan desuden lave døre, vinduer, vents, stiger, lemme mellem etager, ramper, trapper, kiler, broer, vand, knusbart cover, zoner med teksturer og lys, spot- og teksturlys og rumklang. Hele formatet står i [`docs/LAYOUT_SPEC.md`](docs/LAYOUT_SPEC.md).

## Pipelinen
| Trin | Modul | Hvad |
|---|---|---|
| Generate | `mapforge/generator/` | layout.yaml → Valve 220-.map, forseglet af konstruktion |
| Compile | `mapforge/compile/` | SDHLT 1.3.0 (CSG → BSP → VIS → RAD), leak-tjek |
| Validate | `mapforge/validate/` | engine-limits, spawns, gangbarhedsgraf på BSP'en (hop, crouch, stiger), timings, sigtelinjer, layout-graf |
| Render | `mapforge/render/` | egen moderngl-renderer med lightmaps: top-down og kameravinkler |
| Review | `mapforge/review/` | Claude vurderer renders mod en rubrik; pass-reglen ligger i koden |
| Simulate | `mapforge/simulate/` | HLDS + ReHLDS + YaPB-bots i Docker, AMXX-tracker logger runder, kills og positioner. Afbrudte kørsler genoptages |
| Analyze | `mapforge/analyze/` | T-winrate, site-fordeling, heatmaps, første kontakt, døde zoner |
| Decide | `mapforge/decide/` | Claude foreslår ændringer fra en værktøjskasse; tjekkes mod `config/fitness.yaml` |
| Apply / Loop | `mapforge/loop/` | ændringer på layout.yaml, rollback, stopkriterier, budget |
| Dashboard | `mapforge/site/`, `mapforge/live/` | statisk site, live-visning af simuleringer, ønsker tegnet på kortet, "+ Nyt map" fra skitse |

Review og Decide besvares af en frisk Claude-subagent i en Claude Code-session. Loopet skriver en prompt, stopper med exit 3 og samler svaret op ved næste kørsel.

## Status
Faserne 0–6 er færdige. Motor-udvidelsen (fase 6b) afsluttes på testmappet `de_viaduct01`, og art pass (fase 7) er næste fase. Mennesket godkender ved tre gates: layout (A), balance (B) og playtest med rigtige spillere (C). Se [`docs/ROADMAP.md`](docs/ROADMAP.md) eller oversigtssiden på dashboardet.

| Map | Formål |
|---|---|
| `de_forge01` | første genererede map; ved Gate B |
| `de_tilt01` | bevidst ubalanceret variant, som loopet rettede |
| `de_vault01` | testmap for vinduer, døre, stiger, ramper og zoner |
| `de_cistern01` | testmap for etager, lemme, vand, lys og lyd |
| `de_viaduct01` | testmap for polygon-rum, skrå korridorer og broer |
| `test_box` | håndskrevet minimalt map til compile-tests |

## Dokumentation
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): pipeline, komponenter, repo-struktur
- [`docs/ROADMAP.md`](docs/ROADMAP.md): faser, acceptkriterier, gates
- [`docs/FITNESS.md`](docs/FITNESS.md): hvad "bedre" betyder, stopkriterier, låste beslutninger
- [`docs/DESIGN_GUIDE.md`](docs/DESIGN_GUIDE.md): designprincipper for de_-maps, kalibreret på officielle maps
- [`docs/LAYOUT_SPEC.md`](docs/LAYOUT_SPEC.md): YAML-formatet
- [`docs/CALIBRATION.md`](docs/CALIBRATION.md): tærskler målt på referencemaps
- [`docs/TRACKER_SPEC.md`](docs/TRACKER_SPEC.md): AMXX-tracker og CSV-skema
- [`CLAUDE.md`](CLAUDE.md): arbejdsregler og kommandoer

## Licenser
Repoet indeholder kun egne eller fri-licens-assets. Dev-teksturerne genereres proceduralt (CC0); se [`assets/LICENSES.md`](assets/LICENSES.md). Spillet, referencemaps og tredjepartsværktøjer (SDHLT, HLDS, YaPB, AMX Mod X) hentes pinnet ved build og distribueres ikke herfra.
