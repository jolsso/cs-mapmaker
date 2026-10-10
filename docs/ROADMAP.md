# Roadmap

Byg lag for lag. Hvert lag skal fungere selvstændigt, før det næste startes. 🚦 = menneske-gate: stop, opsummér, vent på godkendelse.

## Fase 0 – Fundament
**Mål:** Repo, værktøjer og et kendt testmap kan compiles.

- [ ] Repo-struktur, Makefile, `config/pipeline.yaml`
- [ ] VHLT installeret og kaldbar fra script
- [ ] Et minimalt håndskrevet testmap (`maps/test_box/`): forseglet kasse, 1 lys, 2 spawns pr. hold
- [ ] `make compile MAP=test_box` producerer .bsp

**Accept:** test_box compiler uden errors fra rent checkout via én kommando.

## Fase 1 – Deterministisk loop (compile + validering)
**Mål:** Fejl fanges og forklares automatisk.

- [ ] Compile-log-parser → `compile.json` (errors, warnings, leak-koordinater)
- [ ] BSP-parser (entities, planes, faces, clipnodes, lighting)
- [ ] Validator: limits, off-grid, korridorbredder, spawns-tælling, bomb targets, buyzones
- [ ] Bevidst ødelagte testmaps (leak, ukonveks brush, manglende spawn) → validator fanger dem alle
- [ ] `pytest` dækker parser og validator

**Accept:** Alle fejltestmaps fanges med korrekt årsag. Claude kan rette et leak-map ud fra `compile.json` alene.

## Fase 2 – Generator + blockout
**Mål:** Fra YAML-layout til spilbart graybox-map.

- [ ] Layout-spec-format (YAML) dokumenteret
- [ ] Generator: rum, korridorer, trapper/ramper, sites, spawns, ydre skal
- [ ] Round-trip: læs .map → ændr → skriv
- [ ] Første de_-blockout genereret og compileret uden fejl

**Accept:** Et 2-site blockout passerer Fase 1-validering.

🚦 **Gate A – Layout:** Mennesket går rundt i blockout in-game. Er grundlayoutet sjovt og læsbart? Lås overordnet struktur i FITNESS.md.

## Fase 3 – Render
**Mål:** Claude kan se mappet.

- [ ] newbspguy → OBJ → Blender headless, top-down ortografisk render
- [ ] Kamera-presets fra YAML → perspektiv-renders
- [ ] Lysstyrkekort fra lighting-lump → PNG + "mørke zoner"-liste
- [ ] Klient-screenshot-script (`+map`, kamera, `screenshot`) ⚠️ VERIFICÉR hvordan kamera positioneres scriptet
- [ ] Heatmap-overlay-funktion (bruges i Fase 5)

**Accept:** `make render` producerer alle billeder for blockout på < 5 min uden manuelle trin.

## Fase 4 – Simulation
**Mål:** Bots spiller mappet, og alt logges.

- [ ] Docker: HLDS + Metamod + AMXX + YaPB starter headless
- [ ] Automatisk YaPB-graf for nyt map
- [ ] Tracker-plugin (se TRACKER_SPEC.md) skriver CSV
- [ ] Runner: start server, kør N runder, stop, hent CSV
- [ ] Parallelle servere (mindst 2)

**Accept:** 50 runder på blockout kører uden indgriben, CSV valideres mod skema.

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
- [ ] Claude Code headless får metrics + billeder + FITNESS.md, returnerer ændringsplan
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
