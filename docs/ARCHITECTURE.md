# Arkitektur

## Pipeline: to loops med forskellig hastighed

Simulering koster timer; alt hvad der kan ses eller beregnes uden bots skal fanges før. Derfor to loops:

- **Hurtigt loop (sekunder–minutter, ingen bots):** Generate → Compile → Validate → Render → **Review**. Fejler et trin, går iterationen direkte til Decide med fejlen som input og kører aldrig simulering.
- **Langsomt loop (timer):** kun et map, der har bestået Review, simuleres. Simulate starter med en kort smoke-kørsel og stopper tidligt, når resultatet er statistisk afgjort.

```
 hurtigt loop ─────────────────────────────────────────────────────┐   langsomt loop ──────────────┐
 ┌──────────┐  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐ │  ┌──────────┐  ┌──────────┐   │
 │1 Generate│─▶│2 Compile│─▶│3 Validate│─▶│4 Render│─▶│ 5 Review │─┼─▶│6 Simulate│─▶│7 Analyze │   │
 └──────────┘  └─────────┘  └────┬─────┘  └────────┘  └────┬─────┘ │  └────┬─────┘  └────┬─────┘   │
      ▲                          │ fejl                    │ fejl  │       │ smoke fejler │         │
      │                          ▼                         ▼       │       ▼              ▼         │
      └───────────────────────────────── 8 Decide (Claude) ◀──────────────────────────────┘
```

| Trin | Input | Output | Værktøj | Tid |
|---|---|---|---|---|
| 1 Generate | layout-spec (YAML) / forrige .map + ændringsplan | `.map` (Valve 220) | Python-generator | sek. |
| 2 Compile | `.map`, WADs | `.bsp`, `compile.json` | SDHLT: hlcsg → hlbsp → hlvis → hlrad | sek. (fast) |
| 3 Validate | `.map`, `.bsp`, `compile.json` | `validation.json` | Python (`mapforge.validate`) | sek. |
| 4 Render | `.bsp`, WADs | `renders/*.png` + `renders/index.json` | Egen renderer: BSP-parser + moderngl (Mesa/EGL headless) med teksturer og kompilerede lightmaps | < 5 min |
| 5 Review | renders, `validation.json`, layout-spec, review-tjekliste | `review.json` (pass/fail + fund) | Deterministiske pre-sim-checks + Claude (`claude -p`) ser billederne | ~1 min |
| 6 Simulate | `.bsp`, YaPB-graf | CSV (TRACKER_SPEC.md), `simulation.json` | ReHLDS + Metamod-R + AMXX + YaPB i Docker | min.–timer |
| 7 Analyze | CSV, renders | `metrics.json`, `report.md`, heatmaps | Python (numpy, Pillow) | sek. |
| 8 Decide | se input-kontrakt nedenfor | `plan.json` + `NOTES.md` | Claude Code headless (`claude -p`) | ~1 min |

### 5 Review – pre-sim-gate
Formål: fange alt hvad der kan ses på et billede eller beregnes fra geometrien, før der bruges bot-tid.
- **Deterministisk (først, gratis):** alle hårde krav fra Validate; nåbarhed spawn → begge sites på walkable-grafen fra hull 1 (samme celler som korridor-checket) – flytter FITNESS-kravet "alle spawns kan nå begge sites" fra YaPB-grafen til før simulering; topologi matcher layout-spec (rum/forbindelser findes).
- **Visuelt (Claude):** top-down og kameraviews holdes op mod layout-spec og en fast tjekliste: svarer formen til spec'en, flydende/manglende geometri, sites og spawns hvor de skal være, åbenlyse sigtelinjer tværs over mappet, mørke spilområder. Svar som `review.json`: `{ "pass": bool, "findings": [{ "severity": "critical|major|minor", "where": "...", "what": "...", "image": "renders/…png" }] }`. `critical` eller `major` = fail.
- **Budget:** max 5 hurtige iterationer i træk uden at bestå Review → stop og eskalér til mennesket.
- **Implementering** (`mapforge/review/run.py`): har `validation.json` errors, fejler Review uden model-kald. Ellers bygges en prompt af `config/review/prompt.md` + `checklist.md` + validerings-digest + billedstier (relative til repoet), og et JSON-skema.
- **Executor (besluttet 2026-10-10): i sessionen som standard.** `./mf review` skriver prompten; Claude Code-sessionen lader en subagent (frisk kontekst) læse prompt og billeder og skrive `review_answer.json`; `./mf review -- --answer` validerer og afgør pass. Alternativ til ubemandede kørsler: `--headless` = `claude -p --output-format json --json-schema … --allowedTools Read` på værten (`review.auth: login` fjerner en evt. `ANTHROPIC_API_KEY` for kaldet). Samme prompt, skema og pass-regel (ingen `critical`/`major`, beregnet af koden). En MCP-server er fravalgt indtil der er behov for en anden klient end Claude Code.

### 6 Simulate – trinvis
1. **Smoke (≈ 3 runder):** serveren starter, YaPB-grafen loader, bots bevæger sig og når begge sites, ingen crash. Fejl → Decide uden at køre resten.
2. **Batches à ~20 runder** med løbende konfidensinterval. Stop tidligt, når en gameplay-metrik ligger klart uden for målintervallet (så er iterationen afgjort) eller alle ligger sikkert inden for; ellers fortsæt til max (FITNESS: ≥ 100 runder for en fuld måling).

### 8 Decide – input-kontrakt
Claude får pr. iteration en mappe `runs/<map>/<iteration>/` og en prompt, der peger på filerne (Claude læser selv PNG'erne):

| Fil | Altid | Indhold |
|---|---|---|
| `layout.yaml` | ✓ | nuværende layout-spec |
| `map.diff` | ✓ | ændring i .map ift. forrige iteration |
| `compile.json`, `validation.json` | ✓ | fejl og fund med positioner |
| `renders/index.json` + `renders/*.png` | når Render kørte | top-down, kameraviews, lysstyrkekort; index beskriver kamera og formål pr. billede |
| `review.json` | når Review kørte | visuelle fund |
| `metrics.json`, `heatmaps/*.png` | når Simulate kørte | metrikker med konfidensinterval + delta ift. bedste version |
| `stage.json` | ✓ | hvor iterationen stoppede (validate / review / smoke / simulate) og hvorfor |
| FITNESS.md, seneste 3 × `NOTES.md` | ✓ | mål, låste beslutninger, tilladte ændringer, historik |

Output: `plan.json` = `{ "changes": [{ "type": <tilladt ændring fra FITNESS.md>, "target": …, "params": …, "rationale": … }], "expected_effect": …, "risk": … }` + `NOTES.md`. Orchestratoren afviser planer, der rører låste beslutninger eller bruger en ikke-tilladt ændringstype, før generatoren kører.

## Eksekvering
Værten skal kun have Docker. Alt deterministisk kører i containere, der deler repoet som én mount (`/work`) og kun taler sammen gennem filer:
- **forge** (bygget, fase 0): Python, uv, go-task, SDHLT, Mesa/EGL. Generate, compile, validate, render, analyze, orchestrator.
- **hlds ×N** (fase 4): HLDS + ReHLDS + Metamod-R + AMXX + YaPB (`docker/hlds/`). Startes af `simulate` i forge gennem værtens Docker-socket (Docker SDK); filer ind og ud med put/get_archive, ingen bind mounts.
- **Referencemaps:** din Half-Life-installation mountes read-only på `/refmaps/hl` (`HL_DIR` i `.env`); `test_maps/*.rar` pakkes ud i `build/refmaps/` med `unar` i forge-imaget. Bruges kun til test/kalibrering og committes aldrig.
- **Undtagelse:** CS 1.6-klienten til screenshots med rigtige lightmaps kører på værten (GPU).

## Lokalt website (`mapforge/site/`)
`build/site/` genereres fra repoets data og viser alt ét sted (mørkt dashboard-tema; grafer er inline SVG lavet i Python, `mapforge/site/charts.py` – intet JavaScript, ingen eksterne fonte eller biblioteker): forside med projekter (ét pr. map, grupperet i egne maps og referencemaps, med status pr. fase), arkitektur og roadmap (docs/overview.html), og én side pr. map med nøgletal, fase-bjælke, compile, validering (fund, nåbarhed, løbetider og limits som grafer), alle renders, review, simulering, analyse (metrikker mod mål som bullet-charts, løbende T-winrate, rundeudfald, histogrammer, heatmaps, delta), historik med score-trend og iterationer (plan, politik-tjek, NOTES.md). Genbygges automatisk efter validate/render/review/decide (`site.auto_refresh`) og med `./mf site`. Serveres lokalt med `docker compose up -d site` på `http://localhost:8080` (kun 127.0.0.1) – billeder af Valve-/community-maps forlader aldrig maskinen.

## Historik (`mapforge/history.py`)
`history/<map>/<NNN>/` (gitignored) gemmer hver version af et map: renders, `validation.json`, `review.json`, `compile.json`, `layout.yaml` og `meta.json` (dato, commit, review-status, timings, noter). En ny version oprettes, når .bsp'en ændrer sig (sha256); render/review af samme .bsp opdaterer versionen. Websitet viser versionerne som thumbnail-liste pr. map (nyeste først) med en side pr. version med alle billeder og data.

## Komponenter

### Generator (`mapforge/generator/`) – bygget
- Layout-spec i YAML (`docs/LAYOUT_SPEC.md`): områder (rum/korridorer/udendørs), døre, trapper, cover, sites, spawns, lys.
- Spec'en beskriver kun tomt rum; alt andet inden for en ydre skal er solidt (komprimeret grid + grådig sammenfletning til kasse-brushes). Derfor ingen leaks, og alle vertices på grid.
- Entities: spawns (gitter, vendt mod midten), `func_bomb_target`, `func_buyzone`, `light_environment` for udendørs, punktlys indendørs.
- Round-trip: `mapforge/mapfile/writer.py` skriver Valve 220; parseren læser.

### Compile (`mapforge/compile/`) – bygget
- Profiler: `fast` (hurtig iteration, lav rad-kvalitet) og `final` (`-extra`, flere bounces).
- Skriver altid `build/<map>/compile.log` og `compile.json` – også når compile fejler.
- `compile.json`: `ok`, `failure`, `failed_step`, `steps` (exit code, tid), `errors`, `warnings`, `leak` (hull, entity + origin, `first_point` = hvor leak-linjen forlader spilområdet, `line` = polylinjen fra `.lin`), `limits` (compilerens egen tabel), `textures_referenced`, `wads_required`.

### .map-parser (`mapforge/mapfile/`) – bygget
- Valve 220-parser (entities, brushes, faces med tekstur-akser og linjenumre).
- Brush-geometri fra face-planer: vertices, polygon pr. face, åben/tom/redundant-detektion.

### BSP-parser (`mapforge/bsp/`) – bygget
- BSP v30, alle 15 lumps; struct-layouts fra HLSDK `bspfile.h`.
- Vektoriseret `point_contents` i hull 0–3 (hull 1 = stående spiller 32×32×72), face-polygoner, lightmaps pr. face.

### Validate (`mapforge/validate/`) – bygget
`./mf validate MAP=<navn>` compiler og skriver `build/<map>/validation.json`: `ok`, `summary` (errors/warnings), `findings` (rule, severity, message, source, location, .map-linje, details) og `stats` (limits, walkable, entities).

| Rule | Severity | Kilde | Tjek |
|---|---|---|---|
| `leak`, `compile_failed` | error | compile.json | FITNESS hårdt krav |
| `invalid_brush`, `redundant_face`, `degenerate_face` | error | .map | brushes skal være lukkede og konvekse |
| `off_grid`, `out_of_bounds` | error | .map | vertices på 8-grid, inden for ±4096 |
| `limit_exceeded` | error | .bsp | over engine-limit (100 %) |
| `limit` | error > 90 % (egne maps) / warning (referencemaps), warning > 75 % | .bsp | FITNESS headroom-politik. Limits: HLSDK `MAX_MAP_*`, korrigeret efter officielle maps (se `config/pipeline.yaml`) + AllocBlock fra compileren |
| `spawn_count`, `bomb_targets`, `buyzone_count` | error | .bsp (.map hvis compile fejlede) | FITNESS; ingen `func_buyzone` = implicitte buyzones (OK); per-map override i `maps/<map>/validate.yaml` |
| `spawn_stuck` | error | .bsp | stående hull passer ikke ved spawn-origin |
| `unreachable_site`, `site_not_standable` | error | .bsp | FITNESS: hver spawn skal kunne gå til begge bomb targets (walkable-graf) |
| `spawn_unplaced` | warning | .bsp | ingen jord under spawn inden for max fald |
| `timing_t_fast`, `timing_t_slow`, `timing_ct_late` | warning (egne maps) / info (referencemaps) | .bsp | løbetid spawn → site ved 250 units/s (korteste gåsti, string-pulled): T 14–26 s, CT ≥ 3 s før T – kalibreret på 9 officielle maps (DESIGN_GUIDE.md §2) |
| `narrow_passage`, `low_ceiling` | warning (egne maps) / info (referencemaps) | .bsp | design-norm: nåbare passager med væg på begge sider og fri bredde < 64, eller loft < 96; clusters < 4 celler ignoreres |

**Walkable-graf** (`mapforge/validate/walk.py`): flood-fill fra alle spawns på et 8-units grid, i to stillinger: stående (hull 1) og crouch (hull 3). Træk til hver nabo, i rækkefølge: gå (trin op ≤ 18), hop op på noget (duck-jump ≤ 54), crouch ind under noget, duck-jump ind i en crouch-åbning (vents). Fald (envejs) ≤ 1024, stiger (`func_ladder`) fra bund til top; crouch-celler rejser sig, så snart der er plads. `func_wall` er solid; døre og breakables er passable. **Sites:** `func_bomb_target`-brushes inden for 128 units af hinanden er ét site (prodigy/torn bygger et site af flere). Nåbarhed: omvendt søgning fra hvert site, så envejsfald tæller rigtigt.

Begrænsninger:
- Hop på tværs af huller, at svømme opad og bunny-hop-tricks modelleres ikke – grafen er konservativ (kan underestimere, ikke overestimere nåbarhed).
- Tid: dust2 ~12 s, store udendørsmaps (de_mon) ~5 min. Kan optimeres (grovere grid til nåbarhed), hvis det bliver flaskehalsen i det hurtige loop.
- Korridorbredde måles langs x- og y-aksen, så diagonale gange vurderes for bredt (lempeligt, aldrig falsk alarm).
- Lysstyrkekort (mørke zoner) bygger på `Bsp.face_lightmap` og kommer i fase 3.

### Render (`render/`)
- **Egen renderer** (besluttet 2026-10-10 i stedet for newbspguy → OBJ → Blender): faces fra BSP-parseren trianguleres; teksturer fra BSP'en (indlejrede) eller WADs (egne, HL-installationens, community-mappets); lightmaps (style 0) pakkes i et atlas. moderngl tegner offscreen via Mesa/EGL i forge-containeren – ingen GPU eller skærm. Begrundelse: lightmaps kommer med (OBJ-eksport har dem ikke), newbspguy findes kun som natlige builds med `exportobj` [WIP], og Blender er et stort ekstra image.
- **Top-down:** ortografisk; geometri over spillernes højde (pr. område, fra walk-grafen) skæres væk, så tage ikke skjuler det nåbare område. Spawns og sites tegnes ovenpå.
- **Mangler i første omgang:** .mdl-modeller, sprites, sky og vand-effekter.
- **Klient-screenshots** (fase 7, art pass): start klient med `+map <navn>`, sæt kamera, tag `screenshot` ⚠️ VERIFICÉR – det eneste billede med modeller og alle effekter.
- Kamera-presets i `config/cameras/<map>.yaml` (spawns, sites, mid, key angles).

### Simulate (`mapforge/simulate/`, `docker/hlds/`, `server/plugins/`) – bygget (fase 4)
- **Image** (`docker/hlds/Dockerfile`): HLDS app 90 / cstrike fra SteamCMD (anonym login virker; branch `steam_legacy`, da ReHLDS ikke kan bruge 2024-anniversary-buildens Steam-API) + ReHLDS 3.15 + ReGameDLL 5.30 + Metamod-R 1.3 (kræver ReHLDS) + AMX Mod X 1.10 + YaPB 4.4.957. Add-ons pinnet med URL + SHA256 i `docker/hlds/addons.lock`; HLDS-buildid gemmes i `BUILD_INFO`. Tracker-pluginet compiles med `amxxpc` under build. Image-tag = hash af build-konteksten, så det kun genbygges ved ændringer. Intet af spillet committes.
- **YaPB-graf:** auto-analyse ved første start på et nyt map (`yb_graph_analyze_auto_start/_save`). Analysen kan efterlade hele områder umappede (CALIBRATION.md), så den verificeres af smoke-kørslen: når ingen bot når et site, laves grafen om med næste nodeafstand fra `graph_distances` (96, 80, 112, 128). Grafen caches pr. .bsp-sha256 i `build/<map>/yapb/` med afstand og "verified" i en .json ved siden af. Download/upload af grafer er slået fra.
- **Hurtigere end realtid:** ReHLDS skalerer spiltiden med `sys_timescale`; med `sys_ticrate 400` holdes ~100 server-frames pr. spilsekund. Målt ≈ 4× (de_forge01). `--watch` kører i realtid til spectators.
- **Runner** (`mapforge/simulate/run.py`): smoke (3 runder, 1 server, + op til 6 runder hvis et site ikke er nået endnu: gyldige runder, bots bevæger sig, begge sites nået, CSV-skema) → batches à 20 runder fordelt på 2 parallelle servere → stop ved `max_rounds` eller tidligt (`stats.py`): et resultat klart *uden for* målet (hele Wilson-intervallet) afgøres straks; *inden for* kræver `min_rounds`. Gyldig runde = vinder, ingen mennesker på hold, fulde hold.
- **Spectator:** hver server udgiver UDP `127.0.0.1:27015+i`; `connect localhost:27015`. `yb_autovacate 0`, så en spectator ikke sparker en bot ud.
- **Demo:** HLTV-proxy i samme container (`+delay 0 +record`), som standard på første server pr. batch; `.dem` hentes til `<out>/<gruppe>/<run>/demos/`.
- **Live:** med `docker compose up -d live` sender tracker-pluginet positioner (hvert 0,5 spilsekund), kills, plants og rundeudfald som UDP-datagrammer over netværket `mapforge-sim` til `mapforge.live.collector`, der holder tilstanden i hukommelsen og streamer den som Server-Sent Events (localhost:8090). Websitets Live-side tegner alle kørende servere på top-down-kortet med stilling, runde-strip, kill-feed og samlet T-winrate/plant-fordeling pr. map. Intet skrives til disk; uden collectoren kører simuleringen uændret.
- Output: `build/<map>/sim/` (CSV, server.log, demoer) og `build/<map>/simulation.json`; loopet (fase 6) bruger `--out runs/<map>/<NNN>/sim`.

### Analyze (`mapforge/analyze/`) – bygget (fase 5)
- Input: `build/<map>/sim/` (kun batches; graf- og smoke-runder tæller ikke) + top-down fra Render. Gyldige runder: vinder, ingen mennesker, fulde hold.
- Metrikker (FITNESS): T-winrate og site-fordeling med Wilson-interval; første kontakt og rundelængde som median med bootstrap-interval (fast seed); døde zoner = andel gangbare 64-celler (≥ halvt dækket af walk-noder) med < 2 % af middeltrafikken; kill-koncentration = største andel kills (offerets position) i én 128-celle. Score = vægtet afstand til målintervallerne (`config/fitness.yaml` → weights).
- Heatmaps (`render/overlay.py`): trafik T og CT, kills, deaths, første kontakt, døde zoner.
- Delta mod forrige analyserede version (historikken) eller `--baseline`: en ændring tæller kun, når intervallerne ikke overlapper; vurderingen ser på afstanden til målet.
- Output: `build/<map>/analysis/{metrics.json,report.md,heatmaps/}`; kopieres til historikken og vises på websitet.

### Loop (`mapforge/loop/`) – bygget (fase 6)
- **Orchestrator** (`run.py`): tilstandsmaskine i `runs/<map>/loop.json` (+ `LOOP.md`). Pr. iteration `runs/<map>/<NNN>/`: build (generate → compile + validate → render) → review → [simulate → analyze] → decide → apply. Fejler validate eller review, springes simuleringen over (hurtigt loop). Review og Decide besvares i Claude Code-sessionen af en frisk subagent pr. prompt; loopet skriver prompten og stopper med exit 3, og næste `./mf loop` samler svaret op.
- **Måling og rollback:** analyse mod bedste måling (`--baseline`). Ny bedste = lavere score og ikke "værre" ud over støjen. Er en måling "værre", anvendes næste plan på den bedste versions layout (rollback).
- **Stopkriterier** (`config/fitness.yaml` → stop/budget): mål ramt 2 målinger i træk (→ Gate B), plateau 5 målinger, hårde krav fejler 3 i træk, review fejler 5 i træk, max iterationer/wall clock, Decide eskalerer, eller Decide foreslår intet uden at målene er ramt.
- **Apply** (`apply.py`): værktøjskassens ændringer på `layout.yaml` (round-trip-YAML), hver prøve-genereret; låste roller (site/spawns) og `protected` afvises. `applied.json` viser anvendt/sprunget over/afvist af politik.

## Repo-struktur

```
cs-mapmaker/
├── CLAUDE.md
├── mf, mf.ps1               # `./mf <task>` = task i forge-containeren
├── compose.yaml             # forge-service, repo mountet på /work
├── docker/forge/Dockerfile  # Python + uv + go-task + SDHLT (Linux), Debian trixie
├── Taskfile.yml             # go-task
├── pyproject.toml           # uv-projekt, ruff, pytest
├── config/
│   ├── pipeline.yaml        # stier, compiler (pinnet), profiler, budget
│   ├── pipeline.local.yaml  # valgfri maskin-override (gitignored)
│   ├── fitness.yaml         # tærskler (spejler FITNESS.md)
│   └── cameras/
├── docs/
├── mapforge/                # Python-pakke, ét undermodul pr. trin
│   ├── config.py
│   ├── tools/               # fetch af compilere m.m.
│   ├── wad/                 # WAD3 writer + dev-teksturer
│   ├── compile/
│   ├── generator/           # (Fase 2)
│   ├── validate/            # (Fase 1)
│   ├── render/              # (Fase 3) egen renderer (moderngl)
│   ├── analyze/             # (Fase 5)
│   └── orchestrator/        # (Fase 6)
├── tests/
├── server/
│   ├── Dockerfile
│   ├── plugins/             # AMXX .sma
│   └── cfg/
├── maps/<navn>/
│   ├── layout.yaml
│   ├── ART_DIRECTION.md
│   └── src/<navn>.map
├── assets/
│   ├── wads/                # genererede .wad (gitignored)
│   └── LICENSES.md
├── tools/                   # hentede tredjepartsværktøjer (gitignored)
├── build/<navn>/            # compile-output (gitignored)
└── runs/<navn>/<iteration>/
```

## Afhængigheder (verificér versioner ved opsætning)
- SDHLT 1.3.0 (fork af Vluzacn's ZHLT v34/VHLT), Windows + Linux binaries – hentes med `uv run task tools:fetch`
- uv + go-task (`go-task-bin` i dev-deps)
- moderngl + Mesa/EGL (offscreen rendering), Pillow
- HLDS via SteamCMD, Metamod(-R), AMX Mod X, YaPB
- Python: numpy, pandas, matplotlib, pyyaml, pillow
