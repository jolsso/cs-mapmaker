# Roadmap

Byg lag for lag. Hvert lag skal fungere selvstændigt, før det næste startes. 🚦 = menneske-gate: stop, opsummér, vent på godkendelse.

**Rækkefølge (omlagt 2026-10-10, fase 8 tilføjet 2026-10-15):** 0 → 1 → 1b → 3 → 3b → 2 → 🚦A → 4 → 5 → 6 → 6b → 🚦B → 7 → 🚦C → 8a → 8b → 8c → 🚦M1 → 8d → 8g → 8e → 8f → 🚦M2. Stadig én fase ad gangen (arbejdsregel 1). Omlagt 2026-10-15 efter Gate B på de_forge01: ét map skal hele vejen til 🚦C, før Mapmakeren bygges. 7 (art pass) leverer også tekstur-pipelinen og modellerne, som 8e bygger på. 8g (lært graf-lag) kræver 8d's MAP-Elites-arkiv. Referencemaps i tiers (A = officielle, B = community) bruges fra 8b. De to første punkter i 8b (topologi-udtræk og Graf-siden) blev lavet i en browser-session 2026-10-15, før 6b var afsluttet, og blev integreret samme dag. Det billige loop (validate → render → review → decide) bygges og testes på kendte, officielle maps, før generatoren og den dyre simulering. Fasenumrene er bevaret, så referencer stadig passer.

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
- ✅ 2026-10-15: de_forge01 godkendt i **v006** (loopets bedste måling: score 0,16, T 0,38, A-plants 0,39; `runs/de_forge01/006/layout.yaml` = `history/de_forge01/008`). Layoutet er rullet tilbage fra 012 til 006. 4-vejskrydset ved mid accepteres (eneste validator-warning). Godkendt visuelt, ikke spilletestet med andre (det sker ved 🚦C). Geometrien er låst (`geometry_frozen: true`).

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
- [x] Afslut/genåbn en bane under Input (2026-10-15): `maps/<map>/project.json` via `/api/project/<map>`; en afsluttet bane er grå og sidst på forsiden, tager ingen nye ønsker, og loopet kører ikke på den
- [x] Skrå korridorer i vilkårlig vinkel og flere niveauer med overlap i højden (2026-10-14): konvekse polygon-områder (`poly`), `corridors:`-makro (vilkårlig grid-vinkel, rampe, døre), `bridges:` (dæk med rækværk i høje områder), rum stablet over udendørs områder får solid skal i stedet for himmel; værktøjskassen: `add_bridge`, `move_corridor` på skrå områder. Walk-grafen går nu ind i vents i plan med gulvet (CALIBRATION.md)
- [x] Testmap til vinkler og niveauer, itereret af loopet (feature-forbedringer undervejs): `de_viaduct01` (2026-10-14/15) – validering 0/0, review bestået hver gang; loopet forbedrede scoren fra 0,016 (001) til **0,0088** (005, 104 runder, T 0,60, A-plants 0,66) uden manuelle trin. Undervejs brød et knæk på B long (`bend_corridor`, 003) YaPB's graf, og 006/007 viste graf-støj (A eller B næsten ikke nået i smoke) → parkeret (se "Parkeret"). Loopet er sat på pause efter 007 (venter på decide)
- [x] Loop-robusthed (2026-10-14): budget tæller kun aktiv køretid, en afbrudt simulering genoptages (færdige batches/servere beholdes, runder reddes fra efterladte containere), Docker tjekkes før start
- [x] Skitsestreger → skrå korridorer (`./mf sketch`, 2026-10-14)
- [x] Knæk på skrå korridorer (`via:`, værktøjskassen `bend_corridor`, 2026-10-14): fundet af loopet på de_viaduct01 – en skrå korridor er stadig en lige sigtelinje langs sin egen akse. Fra 2026-10-15 må en skrå irregularity få knæk ind og ud igen; landmarks og chokes er stadig låst
- [x] Pakke 3, cover (2026-10-15): `shape: cylinder` (facetteret prisme, 8/12/16 sider på 8-gitteret: tønder, runde søjler) og presets `crate_stack` (boost), `barrels`, `pallets` (trin); værktøjskassen: `add_cover` med `preset` (uden `size`) eller `shape: cylinder`
- [x] Pakke 3, buer i døråbninger (2026-10-15): `arch: true` på en almindelig dør – halv-elliptisk bue, vederlag ≥ 80 over gulvet, så hele bredden stadig er gangbar; værktøjskassen: `set_arch`, `add_connection` med `arch`
- [x] Bevægelige elementer (pakke 3, 2026-10-15): elevator i en lem (`lift: auto|button` på `hatches`: `func_plat` + `func_button` på en sokkel på hver etage). Verificeret i YaPB's kilde (`analyze.cpp`, `navigate.cpp`): bots kan kun køre med en elevator via graf-noder med `NodeFlag::Lift`, og auto-analysen sætter aldrig det flag. Elevatoren er derfor en ekstra rute for mennesker: ikke i værktøjskassen, og validatoren (som også ignorerer `func_plat`) kræver, at begge etager nås uden den
- [x] Testmap til pakke 3: `de_cistern02` (de_cistern01 + elevator med knapper til kontoret, buer på tre døre, runde søjler, kassestabel, tønder, palletrin): validering 0/0, review bestået (kun minor), smoke OK – YaPB når begge sites (2026-10-15)

**Accept:** et genereret map med de nye features compiler, validerer uden fejl, simuleres (YaPB når begge sites) og forbedres af loopet uden manuelle trin.

✅ Opfyldt 2026-10-15: de_cistern02 (pakke 3) og de_viaduct01 (vinkler/niveauer) compiler og validerer 0/0, bots når begge sites, og loopet forbedrede de_viaduct01 fra 0,016 til 0,0088 uden manuelle trin. Kendt begrænsning: knæk og elevatorer virker ikke for YaPB (parkeret).

## Fase 7 – Art pass
**Mål:** Lys og visuel identitet.

- [x] ART_DIRECTION.md udfyldt for mappet (2026-10-15): `maps/de_forge01/ART_DIRECTION.md`. Tema: industri (et stålværk under nedlukning; A = støbepladsen, varm/orange; B = pumpehallen, kold/teal), låst i `config/fitness.yaml`; callouts knyttet til eksisterende cover, da geometrien er frosset
- [x] Gate B låser layoutet, ikke props (2026-10-15, menneskets afklaring): områder, døre/forbindelser, ruter, sites, spawns og niveauer er frosset; cover/props (også store med gameplay-betydning, som toget på de_train) og lys er frie inden for temaet og måles af loopet. `after_gate_b: true` i `config/fitness.yaml`, håndhævet i `mapforge/decide/policy.py`; FITNESS.md opdateret
- [x] Prop-bibliotek til temaet industri (2026-10-15): `container`, `rail_wagon` (slaggevogn på skinner, som toget på de_train), `ladle`, `forklift`, `ingot_stack`, `pipe_run` (vandret rør) i `mapforge/generator/props.py` sammen med de generiske presets; teksturer fra spillets WADs (tswad, cs_bdog); værktøjskassen `add_cover preset=…`. Generatoren vælger så få WADs som muligt
- [x] Dressing på de_forge01, del 1 – teksturer og zonelys (2026-10-15): fem zoner med teksturer fra `cstrike.wad` (T: asfalt/tegl, CT: lys beton, mid: grus/plettet beton, A: rust og ovnglød som texlight, B: teal metal og gitterriste), landmark-teksturer på eksisterende cover, lav eftermiddagssol. Validering 0 errors (4-vejskrydset er accepteret ved Gate B), render uden manglende teksturer og uden mørke zoner
- [ ] Dressing på de_forge01, del 2 – props efter ART_DIRECTION.md gennem loopet (simulering måler effekten), layoutet uændret
- [ ] Regelbaseret lysplacering + `lights.rad` texlights + zonefarver
- [x] Spillets standard-WADs som tekstur-kilde (2026-10-15, menneskets ønske): 5243 teksturer i 28 WADs fra `cstrike/` og `valve/` (HL_DIR, read-only). `./mf textures [-- --sheets]` → katalog + kontaktark; generatoren skriver selv de WADs, layoutets teksturer ligger i, i `wad`-nøglen (egne først); spillets WADs refereres, embeddes aldrig (test). ⚠️ VERIFICÉR i klienten, at `wad`-nøglens container-stier (`/refmaps/hl/...`) slås op på filnavnet (Hammer-praksis tyder på det)
- [ ] Tekstur-pipeline for det, spillets WADs ikke har: billede → kvantisering → WAD3 (kun egne/fri licens)
- [x] Stilreview mod art direction (2026-10-15): `./mf style MAP=…` rendrer systematiske kameraer ud fra layoutet (hvert område fra midten, begge sider af chokepoints og site-indgange, hvert landmark; de_forge01: 76 billeder på ~12 s) med tal pr. billede (luma, udbrændt, sort, kontrast) → `style_prompt.md` + skema → frisk subagent → `-- --answer` → `style.json`. Pass i koden: ingen `critical` (manglende teksturer og mørke zoner er altid critical; ≥ 25 % udbrændt er medium)
- [x] Billigere og hurtigere stilreview (2026-10-15): kontaktark (6 vinkler pr. ark efter zone, ~1/10 af token-forbruget), "læs alle ark i én tur", og kun vinkler der har ændret sig siden sidste scorede review (billed-hash; fund på uændrede vinkler bæres med). Svar på engelsk
- [x] Lokal model som løbende reviewer (2026-10-15): `./mf style MAP=… -- --local [--resume]` sender ét ark ad gangen til LM Studio (`style.local` i `config/pipeline.yaml`, qwen3.8-27b med reasoning). Kalibreret mod Claude på samme ark: fanger kontrastproblemet (critical) og gentagelser, men overser bl.a. et landmark der ikke skiller sig ud → lokal model mellem iterationer, Claude dømmer ved fase 7's accept. Tom svar (reasoning brugte budgettet) prøves igen med dobbelt budget
- [x] Stilreview på websitet (2026-10-15): map-siden har en "Style review"-sektion med alle vinkler pr. zone, noter skrevet under hvert billede undervejs og en fremdriftsbjælke (poller `style/*.json`); klik åbner en lightbox over siden (←/→ skifter, Esc eller klik ved siden af lukker) med et minimap i hjørnet, der viser kameraets position og retning
- [ ] Klient-screenshots (rigtig CS 1.6-klient: decals, modeller, spillets gamma) til stilreviewet ⚠️ VERIFICÉR kamera-scripting i klienten
- [ ] Lysstyrkekort uden mørke spilzoner
- [x] Modeller, der følger med spillet (2026-10-15): `models:` i layoutet → `env_sprite` med en `.mdl` fra `cstrike/models` eller `valve/models` (fx `conveyor1-3`, `pallet_with_bags`, `qtruck`, `forklift`, `mbarrel`, `light`); ikke solid i sig selv, `clip: [w, d, h]` lægger en CLIP-boks om. Generatoren tjekker, at filen findes (`paths.model_dirs`). Valgt efter Valve-wiki/TWHL: `env_sprite` frem for `cycler_sprite`, som er buggy og kun til test. Intet distribueres; egne `.mdl` er uden for scope. ⚠️ VERIFICÉR i klienten, at CS 1.6 viser `env_sprite` med en model (ingen kilde bekræfter netop CS 1.6). Vores renderer tegner ikke modeller
- [ ] Arkitekturdetaljer i `func_detail`: dørkarme, lister, sokler, skrå tage – må ikke ændre gangbarhed eller sigtelinjer
- [x] Lyd (2026-10-15): `ambient:` i layoutet → `ambient_generic` (loop, radius small/medium/large/everywhere, volumen 1–10) med lyde, spillet selv har (`valve/sound/ambience`, CS falder tilbage på valve); generatoren tjekker, at filen findes (`paths.sound_dirs`). de_forge01: ovnbrummen (A), pumper (B), drypvand (tunneller), vind (mid), maskiner ved spawns

**Accept:** Final compile, ingen mørke zoner, stilreview uden kritiske fund.

🚦 **Gate C – Release:** Menneskelig playtest med rigtige spillere.

## Fase 8 – Mapmaker: simpel og avanceret input (2026-10-15)
**Mål:** Fra en beskrivelse og tema-billeder (simpel) eller en tegning i lag (avanceret) til et spilbart, tema-klædt map – uden at mennesket skriver `layout.yaml`. Spec: `docs/MAPMAKER.md`. Avanceret bygges før simpel, fordi skitsen leverer indlejringen; simpel mode er derefter "agenter tegner skitsen".

### 8a – Brief v2, billeder og Interpreter
- [ ] `brief.json` v2 (skema i koden, bagudkompatibel med v1 fra dashboardet)
- [ ] `maps/<map>/brief/images.json` + upload-API med tag (`mood|landmark|material|layout`) og licens (`own|cc0|inspiration`); `inspiration` gitignored, EXIF strippes
- [ ] Interpreter-agent (prompt + skema → `intent.json`, `--answer` validerer; `must_have` dækket eller begrundet afvist)
- [ ] Dashboard: guide-trin 1–3 + "Sådan har jeg forstået dig" (intent kan rettes)

**Accept:** Tre forskellige briefs (én kun tekst, én med billeder, én med et `layout`-billede) giver skema-gyldige `intent.json`, og mennesket godkender mindst to af tre uden rettelser.

### 8b – Topologi og graf-niveau-evaluator
- [x] Topologi-udtræk fra ethvert layout: `mapforge/topology.py` (`./mf topology MAP=…` → `build/<map>/topology.yaml`), samme tal som `layout_graph()` på alle egne maps (`tests/test_topology.py`) (2026-10-15)
- [x] Topologi-siden på det lokale website (`graph.html`, "Graf" i topbaren): rum ↔ graf, inspektion som `topology.yaml`, `remove_edge` med reglerne genberegnet, korteste veje, niveau-fokus; link fra hver map-side (2026-10-15)
- [ ] Invariant-tjek (inkl. planaritet pr. niveau) og operatorerne (`split_edge`, `merge_nodes`, `add_edge`/`remove_edge`, `reroute`, `set_kind`, `set_level`, `stretch`, `graft`) med tests
- [ ] WL-hash (dubletter) og rolle-bevidst graf-edit-distance
- [ ] Round-trip-test på alle egne maps: layout → topologi → samme nøgletal som i dag
- [ ] Graf-niveau-evaluator: timings, rotation, indgange, kryds, kompleksitet C, groft sigtelinje-estimat – uden compile
- [ ] Referencemap-tiers: **A** = de 15 officielle de_-maps (navneliste i `config/pipeline.yaml` → `refmaps.tiers`, ikke ud fra mappe, da custom maps ofte ligger i `cstrike/maps`), **B** = community-maps; override pr. map
- [ ] BSP → topologi for alle referencemaps (walk-graf-segmentering; rykket frem fra 8g): `./mf refgraphs` → `build/topologies/refmap/`
- [ ] Facit: topologier annoteret i hånden på alle 15 tier A + 5–10 tier B, valgt så de spænder bredt (stablede, asymmetriske, store udendørs)
- [ ] Kalibrering af graf-evaluatoren mod BSP-walk (`design_stats`) på egne maps, loop-historikken og alle referencemaps; afvigelser i `docs/CALIBRATION.md`
- [ ] Genkalibrering af DESIGN_GUIDE-tærskler: bånd sættes på tier A, tier B bruges som kontrol (rapportér begge fordelinger)
- [ ] Bot-baseline: 50 runder på alle referencemaps; skelner bot-metrikkerne tier A fra tier B, og hvor bør sanity-båndet ligge? (diagnostik, ikke fitness)

**Accept:** Topologi-udtrækket rammer facit (site-indgange, niveauer, envejsfald) på ≥ 90 % af de annoterede maps. Median-afvigelse på spawn → site-timings ≤ 2 s mod BSP-walk på både egne maps og tier A, < 10 ms pr. evaluering, round-trip grøn på alle egne maps.

### 8c – Avanceret mode: lag-tegning, Parse og Fit
- [ ] `sketch.json` (niveauer, lagene struktur/forbindelser/detaljer/intention, lås `fixed|flexible|hint`)
- [ ] Dashboard-editor: lag-faner, niveau-vælger, værktøjer pr. lag, lås pr. element, fortryd
- [ ] Live graf-lint: topologi, timings pr. site og regelbrud vises og opdateres, mens man tegner
- [ ] Parse: sketch → `topology.yaml` + rå `layout.yaml`; tvetydige kryds i `parse_report.json`, vist før Fit
- [ ] Fit: global skala → lokal tilpasning (SA/CMA-ES på 8b-evaluatoren) → snap; faste elementer er hårde constraints; topologiændringer kun som forslag
- [ ] `fit_report.json` (hver ændring med årsag) + overlay-render (skitse oven på resultat); varianter ved fidelity 0,9 / 0,6 / 0,3

**Accept:** En håndtegnet testskitse med tre niveauer (kælder, gade, 1. sal), en lem og en rampe → tre fit-varianter, der compiler med 0 errors og består Review. Ingen `fixed`-elementer flyttet i nogen variant; ændringslisten forklarer alle afvigelser > 64 units.

🚦 **Gate M1 – Avanceret mode:** Mennesket tegner selv et map, vælger en variant og går rundt i det. Ligner det tegningen? Gav ændringerne mening?

### 8d – Simpel mode: Sketcher og kandidatgalleri
- [ ] Data-drevne arketyper: klyng referencemaps' topologier (WL-kernel/graf-edit-distance); klyngerne er arketyperne, medoiden (helst tier A) er skabelonen; `three_lane`/`asymmetric`/`stacked` er kun startnavne
- [ ] Adfærdsdimensionernes intervaller og en blød realisme-straf (afstand til tier-vægtet referencefordeling) fra referencemaps
- [ ] MAP-Elites over topologier (arketype × kompleksitet C × andel lange sigtelinjer × CT-territorium); Fit-straf tæller i fitness
- [ ] Sketcher-agent som mutationsoperator (svarer med operatorer + parametre, ikke en ny graf) og til at skrive kandidater som `sketch.json`
- [ ] Arkiv i `build/topologies/archive/` med alle labels (træningsdata til 8g)
- [ ] `./mf candidates`: alle kandidater gennem build → validate → render → review; Curator-agent skriver "hvorfor denne" + callouts; galleri på sitet
- [ ] `./mf pick` + remix ("kandidat 2 med B fra kandidat 4")

**Accept:** Fra en brief uden tegning: ≥ 5 kandidater, der består validering og Review, er indbyrdes forskellige (forskellig arketype eller topologi-afstand over tærskel), ubemandet på < 30 min.

### 8g – Lært graf-lag
- [ ] Datasæt: egne maps + loop-versioner, MAP-Elites-arkiv, referencemaps med tier, menneskelige valg (præferencepar fra Gate A/C)
- [ ] Nyhedskrav: genererede topologier har graf-edit-distance ≥ τ til alle referencemaps
- [ ] Datasæt-poster (JSONL), manifest med hash og splits efter familie; de officielle maps altid i test (`docs/GRAPH_TRAINING.md` §1)
- [ ] `train`-image (PyTorch + PyG, CPU; GPU valgfri), `config/train.yaml`, model-register med promotion og model cards (§6)
- [ ] Surrogat-GNN (GINE-ensemble): topologi → BSP-niveau-metrikker + indlejrbarhed; slår graf-evaluatoren alene; active learning via ensemble-usikkerhed; forfilter i MAP-Elites (§2–3)
- [ ] Graf-generator: kanonisk serialisering, decoder-only transformer betinget på intent, begrænset dekodning; prætræning på arkivet → finetuning på rigtige maps → expert iteration (§4)
- [ ] Retræningspolitik og "Modeller"-side på websitet (§6–7)
- [ ] Generatoren som ekstra kilde i Sketcher

**Accept:** (1) Tier A er hele vejen igennem kun test, aldrig træning. (2) Surrogaten har R² ≥ 0,8 på timings og rotation på holdout. (3) Generatoren giver ≥ 80 % gyldige topologier uden reparation, overholder nyhedskravet og leverer flere Review-godkendte kandidater pr. compute-time end MAP-Elites alene – ellers bliver den ikke slået til.

### 8e – Tema og prefabs
- [ ] Prefab-bibliotek som brush-makroer med tema-tags og wpoly-estimat. Det bygger videre på 6b's cover-presets (`crate_stack`, `barrels`, `pallets`, `shape: cylinder`) og `arch` på døre; nye er container, railing/fence, pipe_run, crane, market_stall og car_wreck
- [ ] Dresser-agent: tema → zoner, materialer, lys, prefabs, udfyldt `ART_DIRECTION.md`; samme politik-tjek som Decide, ingen geometri efter Gate B
- [ ] Palet fra billeder (k-means) → procedurelle CC0-teksturer; `own`/`cc0`-billeder → WAD3 via fase 7's pipeline, licens noteret automatisk
- [ ] Radar-overview med callouts ⚠️ VERIFICÉR format (MAPMAKER.md → Tema og assets); Dresser bruger modellerne fra fase 7

**Accept:** Et map med 6 tema-billeder får zoner, prefabs og lys; final compile uden mørke zoner, < ~800 wpoly pr. kameraview, stilreview uden kritiske fund.

### 8f – Brief-troskab og ende-til-ende
- [ ] Brief-troskab-agent: endelige renders mod brief/intent, score 1–5 pr. punkt (diagnostik, ikke i fitness-vægten)
- [ ] Ende-til-ende i begge modes uden manuelle trin mellem gates

**Accept:** Ét map pr. mode fra brief til Gate B uden manuelle trin mellem gates; brief-troskab ≥ 4 på `concept`, sites og `must_have`.

🚦 **Gate M2 – Mapmaker:** Mennesket laver ét map i hver mode og vurderer: fik jeg det map, jeg beskrev/tegnede? Ville jeg spille det?

## Parkeret
Kendte problemer og idéer, der bevidst ikke arbejdes på nu. De tages op, når de blokerer en fase, eller når mennesket beder om det.

### YaPB's auto-graf vs. vores geometri (parkeret 2026-10-15)
**Problem:** På de_viaduct01 (iteration 003–004) nåede bots ikke site B, efter at loopet havde lagt et knæk på B long (`bend_corridor`). Det skete ved alle graf-afstande (80–128), og `reachable_from_t` var 0. Validatorens walk-graf fandt B nåbar. Da korridoren blev rettet ud igen, nåede bots B. Derudover laver YaPB's auto-analyse aldrig `NodeFlag::Lift`, så bots kan ikke bruge elevatorer (verificeret i `analyze.cpp`/`navigate.cpp`). Indtil videre er `bend_corridor` i praksis ikke brugbar for loopet, og elevatorer er kun for mennesker.

- [ ] **Diagnose først:** sammenlign den cachede YaPB-graf fra iteration 003 (`build/de_viaduct01/yapb/`) med walk-grafen ved knæ-rummet. Ligger fejlen i vores geometri (trin/kant ved overgangen) → ret generatoren. Ligger den i analyzeren → vælg en af løsningerne nedenfor
- [ ] **Løsning A – patch YaPB's analyzer:** fork (MIT-licens), ret `analyze.cpp`, byg fra kilde i HLDS-imaget i stedet for den pinnede release (`docker/hlds/addons.lock`). Lille ændring, hvis fejlen er lokal; kan sendes upstream som PR. Ulempe: merge ved hver ny YaPB-version
- [ ] **Løsning B (foretrukken) – skriv grafen selv:** oversæt walk-grafen fra BSP'en til YaPB's graf-format, inkl. `Lift`-flag ved elevatorer. Bots og validator ser samme gangbarhed, og bots kan bruge elevatorer. ⚠️ VERIFICÉR graf-formatet (komprimering, version, node-/sti-flag) mod YaPB's kilde, før der bygges på det

**Accept (når den tages op):** et map med et knæk på en skrå korridor og en elevator: YaPB når begge sites i smoke-testen, og bots bruger elevatoren i mindst én runde.
