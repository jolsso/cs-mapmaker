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
- [x] Spectator-adgang: hver server eksponerer sin UDP-port (27015, 27016, …), `mp_allowspectators 1`, `sv_lan 1`, én ledig slot ud over bots; join med `connect localhost:<port>`
- [x] Demo-optagelse pr. run, gemt i `<out>/<gruppe>/<run>/demos/` (loopet: `runs/<map>/<iteration>/sim/`), afspilles med `playdemo` – mekanisme: HLTV-proxy i servercontaineren (`+delay 0 +record`)

Hurtigere end realtid: ✅ ReHLDS `sys_timescale` (målt ≈ 4× ved timescale 4, `sys_ticrate 400`). Spectators kan følge med i realtid med `-- --watch`.

**Accept:** 50 runder på blockout kører uden indgriben, CSV valideres mod skema. Du kan joine en kørende server som spectator uden at påvirke data, og et run kan genses som demo.
- ✅ 2026-10-10: de_forge01, 50 gyldige runder på 631 s (2 servere, timescale 4), 0 schema-fejl, ingen timeouts. T-winrate 0,46 [0,33–0,60], plants på A 0,63 (27 plants). 4 HLTV-demoer.
- Spectator: serveren svarer på `127.0.0.1:27015` fra værten (UDP-forespørgsel testet). Din test i klienten blev fravalgt af dig 2026-10-10. Forudsætninger: klienten skal køre Counter-Strike (`-game cstrike`), ikke Condition Zero, og have præcis den .bsp, serveren kører (`-- --watch --bsp <fil>`).
- Demo: HLTV-demoer optages og hentes ud. `playdemo` er ikke testet i klienten.
- Fundet under testen: når YaPB analyserer et nyt map, joiner kun quota − 1 bots. Grafen laves derfor nu i en separat kørsel på 1 runde, der ikke tæller med.
- ✅ Fase 4 afsluttet 2026-10-10.

## Fase 5 – Analyse
**Mål:** Data bliver til metrikker og billeder.

- [x] Metrikker fra FITNESS.md → `metrics.json` (`mapforge/analyze/`; intervaller: Wilson for andele, bootstrap for medianer; score = vægtet afstand til målintervaller)
- [x] Heatmaps: trafik T/CT, kills, deaths, første kontakt, døde zoner – oven på top-down
- [x] Sammenligning mellem iterationer (delta-rapport; ændringer inden for støjen tæller ikke)
- [x] Sanity-check: kør på et kendt map og vurdér om tallene giver mening (de_dust2, se CALIBRATION.md – døde zoner-målet passer ikke til bot-data)

**Accept:** Én rapport pr. iteration, der kan læses af både menneske og Claude.
- ✅ 2026-10-10: `build/<map>/analysis/report.md` + `metrics.json` + heatmaps, på websitet og i historikken. Kørt på de_forge01 og de_dust2.

## Fase 6 – Autonomt loop
**Mål:** Iterationer kører selv inden for rammer.

- [x] Orchestrator med budget, stopkriterier, rollback ved forværring (`mapforge/loop/run.py`, tilstand i `runs/<map>/loop.json`, oversigt i `runs/<map>/LOOP.md`)
- [x] To-hastigheds-loop: hurtige iterationer (til og med Review) gentages, indtil Review består; først da simuleres
- [x] Decide fra fase 3b kobles på generatoren: `plan.json` anvendes (`mapforge/loop/apply.py`), og resultatet går gennem loopet
- [x] Ændringer begrænset til tilladte parametre (ikke låste beslutninger): politik-tjek + låste roller/`protected` i apply
- [x] `runs/`-log med NOTES.md pr. iteration

**Accept:** Loopet forbedrer et bevidst ubalanceret map mod målintervallerne uden at bryde låste beslutninger.
- ✅ 2026-10-10 på de_tilt01 (de_forge01 uden CT's direkte vej til B). Score 2,11 → 1,21 → **0,04** i to iterationer: Decide genskabte CT-døren til B (review-major + timing) og fjernede en kasse, hvor CT-bots klumpede sig (heatmap + kill-celle). 100 runder i iteration 003: T 0,56 [0,46–0,65], A-plants 0,56, første kontakt 16 s, runde 63 s, døde zoner 18 %. Ingen låste beslutninger rørt. `runs/de_tilt01/LOOP.md`.
- Fundet undervejs: YaPB's automatiske graf kan efterlade hele områder umappede → graf-retry (CALIBRATION.md). Live-visning af kørende simuleringer på websitet (`docker compose up -d live`).
- ✅ 2026-10-11: de_forge01 kørt til plateau (11 iterationer, bedste 006: score 0,16, T 0,38, A-plants 0,39). Gate B-opsummering givet; mennesket har sat de_forge01 på pause ("fint for nu") for at prioritere motoren.

🚦 **Gate B – Geometri låst:** Mennesket godkender balance. Geometri fryses før art pass.
- de_forge01: afventer (006 vs. 012, 4-vejskrydset ved mid).

## Fase 6b – Motor-udvidelse (2026-10-11, menneskets prioritet: motoren før mappet)
**Mål:** Generatoren og loopets værktøjskasse kan mere end akse-rettede kasser.

- [x] Ramper (≤ 45°), kiler (skrå vægge / diagonale korridorer), hævet cover (platforme, broer, boost-spots)
- [x] Vinduer og vents (`kind`, `sill`), glas (`func_breakable`), døre der kan åbnes (`func_door`, `func_door_rotating` med ORIGIN)
- [x] Stiger (`func_ladder` + synlig stige), player clip på trapper, rum der rører hinanden (L-rum, split-level)
- [x] Zoner (tekstur pr. vendt flade + lysfarve), landmark-materialer og tool-teksturer i dev-WAD'en, våben (`armoury_entity`), `info_map_parameters`, `func_detail` (⚠️ mørk efter fast-RAD, standard fra)
- [x] Decide-værktøjskasse: `add_window`, `set_gate`, `add_ramp`, `add_wedge`, `add_ladder`, `remove_element`, hævet `add_cover`, vent-forbindelser; låste beslutninger pr. map (`locked_maps`)
- [x] Layout-graf: vinduer er ikke indgange; rum der rører hinanden er ét rum
- [x] Nyt testmap `de_vault01` med alle features: validering 0 errors/0 warnings; gangbarhedsgrafen klatrer op ad stigen
- [x] Loopet itererer på de_vault01: review-fund (mid ind i CT-spawn, tunnel-sigtelinje) rettet i iteration 001; alle mål ramt 2 målinger i træk (score 0,0; T 0,46 / 0,59, A-plants 0,49 / 0,48) → Gate B. Review genbruges ved byte-identisk .map
- [x] Pakke 2: ottekantede søjler, knusbart cover (`func_breakable`), lys pr. område, spotlys (`light_spot`), teksturlys (`<map>.rad` → hlrad `-lights`), rumklang (`env_sound` efter størrelse), lemme mellem stablede etager med stige, vand (`!WATER`), diagonal-korridor som makro; værktøjskassen: `set_breakable`, `add_hatch`, `add_water`
- [x] Nyt testmap til pakke 2: `de_cistern01` (B under jorden med ramper, kontor over B via lem og stige, vand, ottekantede søjler, knusbare kasser, spot-/teksturlys, rumklang); review bestået (3,6)
- [x] Dashboard: "+ Nyt map" – start et map med en beskrivelse og en skitse (brief.json + annotations på et tomt gitter); Claude laver layoutet ud fra dem
- [x] Skrå korridorer i vilkårlig vinkel og flere niveauer med overlap i højden (2026-10-14): konvekse polygon-områder (`poly`), `corridors:`-makro (vilkårlig grid-vinkel, rampe, døre), `bridges:` (dæk med rækværk i høje områder), rum stablet over udendørs områder får solid skal i stedet for himmel; værktøjskassen: `add_bridge`, `move_corridor` på skrå områder. Walk-grafen går nu ind i vents i plan med gulvet (CALIBRATION.md)
- [ ] Testmap til vinkler og niveauer, itereret af loopet (feature-forbedringer undervejs)

**Accept:** et genereret map med de nye features compiler, validerer uden fejl, simuleres (YaPB når begge sites) og forbedres af loopet uden manuelle trin.

## Fase 7 – Art pass
**Mål:** Lys og visuel identitet.

- [ ] ART_DIRECTION.md udfyldt for mappet
- [ ] Regelbaseret lysplacering + `lights.rad` texlights + zonefarver
- [ ] Tekstur-pipeline: billede → kvantisering → WAD3 (kun fri licens)
- [ ] Claude-review af klient-screenshots mod stilguide
- [ ] Lysstyrkekort uden mørke spilzoner

**Accept:** Final compile, ingen mørke zoner, stilreview uden kritiske fund.

🚦 **Gate C – Release:** Menneskelig playtest med rigtige spillere.
