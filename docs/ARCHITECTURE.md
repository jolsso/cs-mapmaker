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
| 4 Render | `.bsp` | `renders/*.png` + `renders/index.json` | newbspguy → OBJ → Blender headless; lysstyrkekort fra BSP | < 5 min |
| 5 Review | renders, `validation.json`, layout-spec, review-tjekliste | `review.json` (pass/fail + fund) | Deterministiske pre-sim-checks + Claude (`claude -p`) ser billederne | ~1 min |
| 6 Simulate | `.bsp`, YaPB-graf | CSV (TRACKER_SPEC.md) | HLDS + Metamod + AMXX + YaPB | min.–timer |
| 7 Analyze | CSV, renders | `metrics.json`, heatmaps | Python (pandas, numpy, matplotlib) | sek. |
| 8 Decide | se input-kontrakt nedenfor | `plan.json` + `NOTES.md` | Claude Code headless (`claude -p`) | ~1 min |

### 5 Review – pre-sim-gate
Formål: fange alt hvad der kan ses på et billede eller beregnes fra geometrien, før der bruges bot-tid.
- **Deterministisk (først, gratis):** alle hårde krav fra Validate; nåbarhed spawn → begge sites på walkable-grafen fra hull 1 (samme celler som korridor-checket) – flytter FITNESS-kravet "alle spawns kan nå begge sites" fra YaPB-grafen til før simulering; topologi matcher layout-spec (rum/forbindelser findes).
- **Visuelt (Claude):** top-down og kameraviews holdes op mod layout-spec og en fast tjekliste: svarer formen til spec'en, flydende/manglende geometri, sites og spawns hvor de skal være, åbenlyse sigtelinjer tværs over mappet, mørke spilområder. Svar som `review.json`: `{ "pass": bool, "findings": [{ "severity": "critical|major|minor", "where": "...", "what": "...", "image": "renders/…png" }] }`. `critical` eller `major` = fail.
- **Budget:** max 5 hurtige iterationer i træk uden at bestå Review → stop og eskalér til mennesket.

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
- **forge** (bygget, fase 0): Python, uv, go-task, SDHLT. Generate, compile, validate, analyze, orchestrator.
- **render** (fase 3): Blender headless.
- **hlds ×N** (fase 4): HLDS + Metamod + AMXX + YaPB. Eget image; kræver lovligt ejede CS-filer.
- **Referencemaps:** din Half-Life-installation mountes read-only på `/refmaps/hl` (`HL_DIR` i `.env`); `test_maps/*.rar` pakkes ud i `build/refmaps/` med `unar` i forge-imaget. Bruges kun til test/kalibrering og committes aldrig.
- **Undtagelse:** CS 1.6-klienten til screenshots med rigtige lightmaps kører på værten (GPU).

## Komponenter

### Generator (`generator/`)
- Layout-spec i YAML: rum, korridorer, højder, sites, spawns, forbindelser.
- Producerer konvekse brushes på grid, forseglet ydre skal, entities.
- Skal kunne round-trippe: læse en eksisterende .map, ændre, skrive tilbage.

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
| `narrow_passage`, `low_ceiling` | warning (egne maps) / info (referencemaps) | .bsp | design-norm: nåbare passager med væg på begge sider og fri bredde < 64, eller loft < 96; clusters < 4 celler ignoreres |

**Walkable-graf** (`mapforge/validate/walk.py`): flood-fill fra alle spawns på et 8-units grid, i to stillinger: stående (hull 1) og crouch (hull 3). Træk til hver nabo, i rækkefølge: gå (trin op ≤ 18), hop op på noget (duck-jump ≤ 54), crouch ind under noget, duck-jump ind i en crouch-åbning (vents). Fald (envejs) ≤ 1024, stiger (`func_ladder`) fra bund til top; crouch-celler rejser sig, så snart der er plads. `func_wall` er solid; døre og breakables er passable. **Sites:** `func_bomb_target`-brushes inden for 128 units af hinanden er ét site (prodigy/torn bygger et site af flere). Nåbarhed: omvendt søgning fra hvert site, så envejsfald tæller rigtigt.

Begrænsninger:
- Hop på tværs af huller, at svømme opad og bunny-hop-tricks modelleres ikke – grafen er konservativ (kan underestimere, ikke overestimere nåbarhed).
- Tid: dust2 ~12 s, store udendørsmaps (de_mon) ~5 min. Kan optimeres (grovere grid til nåbarhed), hvis det bliver flaskehalsen i det hurtige loop.
- Korridorbredde måles langs x- og y-aksen, så diagonale gange vurderes for bredt (lempeligt, aldrig falsk alarm).
- Lysstyrkekort (mørke zoner) bygger på `Bsp.face_lightmap` og kommer i fase 3.

### Render (`render/`)
- **Geometri:** newbspguy exportobj → Blender `--background` script med faste kameraer. ⚠️ VERIFICÉR exportobj-kvalitet (markeret WIP i originalt bspguy).
- **Lys/udseende:** Start klient med `+map <navn>`, sæt kamera via config/script, tag `screenshot`. Lightmaps findes ikke i OBJ-renders.
- Kamera-presets i `config/cameras/<map>.yaml` (spawns, sites, mid, key angles).

### Simulate (`server/`)
- Docker-image: HLDS (SteamCMD, app 90, mod cstrike) + ReHLDS/ReGameDLL_CS (valgfrit) + Metamod(-R) + AMX Mod X + YaPB.
- Kræver lovligt ejede CS 1.6-filer.
- YaPB-navigationsgraf genereres pr. map. ⚠️ VERIFICÉR kommando til automatisk graf-generering i YaPB-docs.
- Kør flere servere parallelt for flere runder pr. time. ⚠️ VERIFICÉR om server kan køres hurtigere end realtid; antag realtid indtil bevist.

### Analyze (`analyze/`)
- Heatmaps: position, kills, deaths, første kontakt.
- Metrikker defineret i FITNESS.md → `metrics.json`.
- Overlay heatmaps på top-down render.

### Orchestrator (`orchestrator/`)
- Kører loop, håndterer stopkriterier og budget, skriver `runs/`.
- Kalder Claude Code headless med prompt + metrics + billeder, modtager ændringsplan.

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
│   ├── render/              # (Fase 3)
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
- newbspguy (UnrealKaraulov) – Windows/Linux
- Blender (headless) eller pyrender
- HLDS via SteamCMD, Metamod(-R), AMX Mod X, YaPB
- Python: numpy, pandas, matplotlib, pyyaml, pillow
