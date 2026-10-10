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

- [x] Referencemaps: læses read-only fra den lokale CS 1.6-installation (`HL_DIR` i `.env`, se `.env.example`) + community-maps fra `test_maps/` (pakkes ud med `./mf refmaps`), mountes read-only i containeren og kopieres aldrig ind i repoet
- [x] BSP-tilstand i Validate: `./mf validate MAP=de_dust2 SOURCE=reference` (ingen .map, ingen compile)
- [x] Buyzones: implicitte buyzones tæller (ingen `func_buyzone` overhovedet = CS laver dem ved spawn); fejl kun hvis kun ét hold har
- [x] Nåbarhed: flood-fill fra spawns på walkable-grafen (hull 1); hver spawn skal nå begge bomb targets (`unreachable_site`); korridor-warnings kun i nåbart område
- [x] Kalibrering på alle officielle de_-maps; tærskler justeres og begrundes (`docs/CALIBRATION.md`, `./mf validate:refs`)

**Accept:** Alle officielle de_-maps i installationen validerer med 0 errors, og de resterende warnings er gennemgået og giver mening.
✅ Opfyldt 2026-10-10: 17 de_-maps (15 officielle + de_cold, de_mon) med 0 errors; alle spawns når begge sites; resterende warnings er kun headroom-politik (> 90 % planes) på 4 store officielle maps. Se `docs/CALIBRATION.md`.

## Fase 3 – Render
**Mål:** Claude kan se mappet. Bygges og testes på referencemaps (fase 1b), før generatoren findes.

- [x] Egen renderer (BSP + moderngl, Mesa/EGL headless): top-down ortografisk med teksturer og lightmaps, tage over spillerhøjde skåret væk
- [x] Kameraer → perspektiv-renders: automatiske (spawns, sites) + valgfri `config/cameras/<map>.yaml`
- [x] Lysstyrkekort fra lighting-lump → PNG + "mørke zoner"-liste (lightmap under hver gangbar celle; tærskel kalibreret, se CALIBRATION.md)
- [ ] Klient-screenshot-script (`+map`, kamera, `screenshot`) ⚠️ VERIFICÉR hvordan kamera positioneres scriptet – flyttet til fase 7 (art pass); egne renders har allerede lys
- [x] Heatmap-overlay-funktion (bruges i Fase 5) – `mapforge/render/overlay.py`, på `topdown_raw.png` via view i `index.json`
- [x] `renders/index.json`: kamera, formål og fil pr. billede (+ lysstyrke, manglende teksturer, view til overlays)
- [x] Review-trin (pre-sim-gate): deterministiske checks + Claude ser billederne mod tjekliste (og layout-spec, når mappet har en) → `review.json`; fail går direkte til Decide uden simulering (ARCHITECTURE.md → 5 Review)

**Accept:** `./mf render` producerer alle billeder for de_dust2 på < 5 min uden manuelle trin, og Review på dust2 består. Et bevidst ødelagt referencemap (fx med en blokeret forbindelse) fanges af Review uden at simulere. Efter fase 2 gentages testen på et genereret blockout mod dets layout-spec.
✅ Opfyldt 2026-10-10: `./mf render` på dust2 på ~6 s (7 billeder); Review på dust2 PASS (kun minor-fund om mørke tunneller). To ødelagte varianter (`uv run python -m mapforge.refmaps_variants`: T-spawns oven i CT-spawns; site 2 flyttet ind i CT-spawn) består validering, men fanges begge som **critical** af Review – uden simulering.

## Fase 3b – Decide (tørkørsel)
**Mål:** Decide-trinnet virker på rigtige input, før der findes en generator at anvende planen på.

- [x] Input-kontrakt (ARCHITECTURE.md → 8 Decide) samles i `runs/<map>/<iteration>/` + `stage.json` (`mapforge/runs.py`, `./mf decide MAP=… -- --emit`)
- [x] `plan.json`-skema; orchestrator-validering afviser ikke-tilladte ændringstyper og låste beslutninger (`config/fitness.yaml`, `mapforge/decide/policy.py`)
- [x] Claude (session-subagent; `claude -p` muligt) får input og returnerer `plan.json` + `NOTES.md`
- [x] Forældede reviews opdages: `review.json` gemmer hash af sine inputs; `stage.json` kræver nyt review, hvis renders/validering er ændret

**Accept:** For dust2 og et bevidst ødelagt referencemap returnerer Decide en skema-gyldig plan, der adresserer de faktiske fund. Planen anvendes ikke endnu.
✅ Opfyldt 2026-10-10: dust2 → 0 ændringer (review bestået; kun mørke zoner, som kun `lighting` kan rette, og den er først tilladt i fase 7) → næste trin simulering. de_dust2_sitemoved → eskalering: at flytte et bomb site ligger uden for værktøjskassen; subagenten afviste selv at dække over det med `move_spawn` og stillede mennesket to konkrete spørgsmål. Begge planer bestod politik-tjekket.

## Fase 2 – Generator + blockout
**Mål:** Fra YAML-layout til spilbart graybox-map.

- [x] Layout-spec-format (YAML) dokumenteret – `docs/LAYOUT_SPEC.md` (Review i fase 3 bruger det til egne maps)
- [x] Generator: rum, korridorer, trapper (ramper senere), sites, spawns, ydre skal – forseglet af konstruktion (`mapforge/generator/`)
- [x] Round-trip: læs .map → ændr → skriv (`mapforge/mapfile/writer.py`)
- [x] Første de_-blockout genereret og compileret uden fejl (`maps/de_forge01/`)

**Accept:** Et 2-site blockout passerer validering (fase 1 + 1b, inkl. nåbarhed) og Review.
✅ Opfyldt 2026-10-10: `de_forge01` (23 områder, 27 døre, 143 brushes) – validering 0 errors/0 warnings, alle 24 spawns når begge sites; Review PASS i 3. runde (runde 1: én T-indgang pr. site + mid ind i CT-spawn; runde 2: lige sigtelinje ned ad long; begge rettet i layout.yaml).

🚦 **Gate A – Layout:** Mennesket går rundt i blockout in-game. Er grundlayoutet sjovt og læsbart? Lås overordnet struktur i FITNESS.md.
✅ Godkendt 2026-10-10: de_forge01 v004. Topologi og sites låst i `config/fitness.yaml`; tema vælges før fase 7.

## Fase 4 – Simulation
**Mål:** Bots spiller mappet, og alt logges.

- [x] Docker: HLDS + Metamod + AMXX + YaPB starter headless (`docker/hlds/`: SteamCMD anonym, branch steam_legacy + ReHLDS 3.15 + ReGameDLL 5.30 + Metamod-R 1.3 + AMXX 1.10 + YaPB 4.4.957, pins i `addons.lock`)
- [x] Automatisk YaPB-graf for nyt map (YaPB's auto-analyse; caches pr. .bsp-hash i `build/<map>/yapb/`)
- [x] Tracker-plugin (se TRACKER_SPEC.md) skriver CSV (`server/plugins/mapforge_tracker.sma`, compiles i imaget)
- [x] Runner: start server, kør N runder, stop, hent CSV (`mapforge/simulate/`, Docker SDK via socket, filer ind/ud med put/get_archive)
- [x] Smoke-kørsel (≈ 3 runder) før fuld simulering: server, graf, bots bevæger sig og når begge sites (de_forge01: OK, 90 s)
- [x] Batches à ~20 runder med løbende konfidensinterval og tidligt stop, når resultatet er afgjort (Wilson 95 %; "uden for mål" stopper straks, "inden for" kræver min_rounds)
- [x] Parallelle servere (mindst 2)
- [ ] Spectator-adgang: hver server eksponerer sin UDP-port (27015, 27016, …), `mp_allowspectators 1`, `sv_lan 1`, én ledig slot ud over bots; join med `connect localhost:<port>`
- [ ] Demo-optagelse pr. run, gemt i `runs/<map>/<iteration>/demos/`, afspilles med `playdemo` ⚠️ VERIFICÉR mekanisme (HLTV-proxy `record` vs. server-side plugin)

Hurtigere end realtid: ✅ ReHLDS `sys_timescale` (målt ≈ 4× ved timescale 4, `sys_ticrate 400`). Spectators kan følge med i realtid med `-- --watch`.

**Accept:** 50 runder på blockout kører uden indgriben, CSV valideres mod skema. Du kan joine en kørende server som spectator uden at påvirke data, og et run kan genses som demo.
- ✅ 2026-10-10: de_forge01, 50 gyldige runder på 631 s (2 servere, timescale 4), 0 schema-fejl, ingen timeouts. T-winrate 0,46 [0,33–0,60], plants på A 0,63 (27 plants). 4 HLTV-demoer.
- ⏳ Spectator og `playdemo`: testes af dig i CS-klienten. Klienten skal have præcis den .bsp, serveren kører (`-- --watch --bsp <fil>`).

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
