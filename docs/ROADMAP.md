# Roadmap

Byg lag for lag. Hvert lag skal fungere selvstændigt, før det næste startes. 🚦 = menneske-gate: stop, opsummér, vent på godkendelse.

**Rækkefølge (omlagt 2026-10-10):** 0 → 1 → 1b → 3 → 3b → 2 → 🚦A → 4 → 5 → 6 → 🚦B → 7 → 🚦C. Det billige loop (validate → render → review → decide) bygges og testes på kendte, officielle maps, før generatoren og den dyre simulering. Fasenumrene er bevaret, så referencer stadig passer.

## Fase 0 – Fundament
**Mål:** Repo, værktøjer og et kendt testmap kan compiles.

- [x] Repo-struktur, Taskfile (i stedet for Makefile), `config/pipeline.yaml`
- [x] Compilere (SDHLT, VHLT-fork) hentes pinnet og er kaldbare fra script
- [x] Et minimalt testmap (`maps/test_box/`): forseglet kasse, 1 lys, 2 spawns pr. hold
- [x] `./mf compile MAP=test_box` producerer .bsp
- [x] Eksekvering i Docker (`forge`-image); værten skal kun have Docker

**Accept:** test_box compiler uden errors fra rent checkout via én kommando – i Docker.

## Fase 1 – Deterministisk loop (compile + validering)
**Mål:** Fejl fanges og forklares automatisk.

- [x] Compile-log-parser → `compile.json` (errors, warnings, leak-koordinater)
- [x] BSP-parser (entities, planes, faces, clipnodes, lighting)
- [x] Validator: limits, off-grid, korridorbredder, spawns-tælling, bomb targets, buyzones
- [x] Bevidst ødelagte testmaps (leak, ukonveks brush, manglende spawn) → validator fanger dem alle (`tests/fixtures/maps/`, 7 stk.)
- [x] `pytest` dækker parser og validator

**Accept:** Alle fejltestmaps fanges med korrekt årsag. Claude kan rette et leak-map ud fra `compile.json` alene.
✅ Opfyldt 2026-10-10: 7/7 fixtures fanges (`tests/test_validate.py`). En frisk agent fik kun det utætte map (uden kommentarer) + `compile.json`, tilføjede den manglende væg ud fra `leak.first_point`/`leak.line`, og resultatet compilede uden leak og validerede med 0 errors.

## Fase 1b – Referencemaps og kalibrering
**Mål:** Validate (BSP-delen) er afprøvet og kalibreret på officielle maps, vi ved virker.

- [ ] Referencemaps: læses read-only fra den lokale CS 1.6-installation (sti i `config/pipeline.local.yaml`), mountes read-only i containeren og kopieres aldrig ind i repoet
- [ ] BSP-tilstand i Validate: `./mf validate MAP=de_dust2 SOURCE=reference` (ingen .map, ingen compile)
- [x] Buyzones: implicitte buyzones tæller (ingen `func_buyzone` overhovedet = CS laver dem ved spawn); fejl kun hvis kun ét hold har
- [ ] Nåbarhed: flood-fill fra spawns på walkable-grafen (hull 1); hver spawn skal nå begge bomb targets (`unreachable_site`); korridor-warnings kun i nåbart område
- [ ] Kalibrering på alle officielle de_-maps; tærskler justeres og begrundes

**Accept:** Alle officielle de_-maps i installationen validerer med 0 errors, og de resterende warnings er gennemgået og giver mening.

## Fase 3 – Render
**Mål:** Claude kan se mappet. Bygges og testes på referencemaps (fase 1b), før generatoren findes.

- [ ] newbspguy → OBJ → Blender headless, top-down ortografisk render
- [ ] Kamera-presets fra YAML → perspektiv-renders
- [ ] Lysstyrkekort fra lighting-lump → PNG + "mørke zoner"-liste
- [ ] Klient-screenshot-script (`+map`, kamera, `screenshot`) ⚠️ VERIFICÉR hvordan kamera positioneres scriptet
- [ ] Heatmap-overlay-funktion (bruges i Fase 5)
- [ ] `renders/index.json`: kamera, formål og fil pr. billede
- [ ] Review-trin (pre-sim-gate): deterministiske checks + Claude ser billederne mod tjekliste (og layout-spec, når mappet har en) → `review.json`; fail går direkte til Decide uden simulering (ARCHITECTURE.md → 5 Review)

**Accept:** `./mf render` producerer alle billeder for de_dust2 på < 5 min uden manuelle trin, og Review på dust2 består. Et bevidst ødelagt referencemap (fx med en blokeret forbindelse) fanges af Review uden at simulere. Efter fase 2 gentages testen på et genereret blockout mod dets layout-spec.

## Fase 3b – Decide (tørkørsel)
**Mål:** Decide-trinnet virker på rigtige input, før der findes en generator at anvende planen på.

- [ ] Input-kontrakt (ARCHITECTURE.md → 8 Decide) samles i `runs/<map>/<iteration>/` + `stage.json`
- [ ] `plan.json`-skema; orchestrator-validering afviser ikke-tilladte ændringstyper og låste beslutninger
- [ ] Claude Code headless (`claude -p`) får input og returnerer `plan.json` + `NOTES.md`

**Accept:** For dust2 og et bevidst ødelagt referencemap returnerer Decide en skema-gyldig plan, der adresserer de faktiske fund. Planen anvendes ikke endnu.

## Fase 2 – Generator + blockout
**Mål:** Fra YAML-layout til spilbart graybox-map.

- [ ] Layout-spec-format (YAML) dokumenteret (Review i fase 3 bruger det til egne maps)
- [ ] Generator: rum, korridorer, trapper/ramper, sites, spawns, ydre skal
- [ ] Round-trip: læs .map → ændr → skriv
- [ ] Første de_-blockout genereret og compileret uden fejl

**Accept:** Et 2-site blockout passerer Fase 1-validering, inkl. nåbarhed.

🚦 **Gate A – Layout:** Mennesket går rundt i blockout in-game. Er grundlayoutet sjovt og læsbart? Lås overordnet struktur i FITNESS.md.

## Fase 4 – Simulation
**Mål:** Bots spiller mappet, og alt logges.

- [ ] Docker: HLDS + Metamod + AMXX + YaPB starter headless
- [ ] Automatisk YaPB-graf for nyt map
- [ ] Tracker-plugin (se TRACKER_SPEC.md) skriver CSV
- [ ] Runner: start server, kør N runder, stop, hent CSV
- [ ] Smoke-kørsel (≈ 3 runder) før fuld simulering: server, graf, bots bevæger sig og når begge sites
- [ ] Batches à ~20 runder med løbende konfidensinterval og tidligt stop, når resultatet er afgjort
- [ ] Parallelle servere (mindst 2)
- [ ] Spectator-adgang: hver server eksponerer sin UDP-port (27015, 27016, …), `mp_allowspectators 1`, `sv_lan 1`, én ledig slot ud over bots; join med `connect localhost:<port>`
- [ ] Demo-optagelse pr. run, gemt i `runs/<map>/<iteration>/demos/`, afspilles med `playdemo` ⚠️ VERIFICÉR mekanisme (HLTV-proxy `record` vs. server-side plugin)

**Accept:** 50 runder på blockout kører uden indgriben, CSV valideres mod skema. Du kan joine en kørende server som spectator uden at påvirke data, og et run kan genses som demo.

## Fase 5 – Analyse
**Mål:** Data bliver til metrikker og billeder.

- [ ] Metrikker fra FITNESS.md → `metrics.json`
- [ ] Heatmaps: trafik, kills, deaths, første kontakt – oven på top-down
- [ ] Sammenligning mellem iterationer (delta-rapport)
- [ ] Sanity-check: kør på et kendt map og vurdér om tallene giver mening

**Accept:** Én rapport pr. iteration, der kan læses af både menneske og Claude.

## Fase 6 – Autonomt loop
**Mål:** Iterationer kører selv inden for rammer.

- [ ] Orchestrator med budget, stopkriterier, rollback ved forværring
- [ ] To-hastigheds-loop: hurtige iterationer (til og med Review) gentages, indtil Review består; først da simuleres
- [ ] Decide fra fase 3b kobles på generatoren: `plan.json` anvendes, og resultatet går gennem loopet
- [ ] Ændringer begrænset til tilladte parametre (ikke låste beslutninger)
- [ ] `runs/`-log med NOTES.md pr. iteration

**Accept:** Loopet forbedrer et bevidst ubalanceret map mod målintervallerne uden at bryde låste beslutninger.

🚦 **Gate B – Geometri låst:** Mennesket godkender balance. Geometri fryses før art pass.

## Fase 7 – Art pass
**Mål:** Lys og visuel identitet.

- [ ] ART_DIRECTION.md udfyldt for mappet
- [ ] Regelbaseret lysplacering + `lights.rad` texlights + zonefarver
- [ ] Tekstur-pipeline: billede → kvantisering → WAD3 (kun fri licens)
- [ ] Claude-review af klient-screenshots mod stilguide
- [ ] Lysstyrkekort uden mørke spilzoner

**Accept:** Final compile, ingen mørke zoner, stilreview uden kritiske fund.

🚦 **Gate C – Release:** Menneskelig playtest med rigtige spillere.
