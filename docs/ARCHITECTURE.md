# Arkitektur

## Pipeline (én iteration)

```
 ┌────────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
 │ 1 Generate │──▶│2 Compile │──▶│3 Validate│──▶│ 4 Render │──▶│5 Simulate│──▶│6 Analyze │
 │  .map      │   │  VHLT    │   │ limits   │   │ views    │   │HLDS+bots │   │ metrics  │
 └────────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └────┬─────┘
       ▲                                                                            │
       └──────────────────── 7 Decide (Claude: ændringsforslag) ◀───────────────────┘
```

| Trin | Input | Output | Værktøj |
|---|---|---|---|
| 1 Generate | layout-spec (YAML) / forrige .map + ændringer | `.map` (Valve 220) | Python-generator |
| 2 Compile | `.map`, WADs | `.bsp`, compile-log | SDHLT (VHLT-fork): hlcsg → hlbsp → hlvis → hlrad |
| 3 Validate | `.bsp`, log | `validation.json` (leaks, limits, r_speeds-estimat) | Python BSP-parser, newbspguy `info` |
| 4 Render | `.bsp` | PNG: top-down, kameraviews, lysstyrkekort | newbspguy → OBJ → Blender headless; klient-screenshots for lys |
| 5 Simulate | `.bsp`, YaPB-graf | CSV-events (se TRACKER_SPEC.md) | HLDS (Docker) + Metamod + AMXX + YaPB |
| 6 Analyze | CSV, renders | `metrics.json`, heatmaps | Python (pandas, numpy, matplotlib) |
| 7 Decide | metrics, billeder, FITNESS.md | ændringsplan + næste .map | Claude Code headless (`claude -p`) |

## Eksekvering
Værten skal kun have Docker. Alt deterministisk kører i containere, der deler repoet som én mount (`/work`) og kun taler sammen gennem filer:
- **forge** (bygget, fase 0): Python, uv, go-task, SDHLT. Generate, compile, validate, analyze, orchestrator.
- **render** (fase 3): Blender headless.
- **hlds ×N** (fase 4): HLDS + Metamod + AMXX + YaPB. Eget image; kræver lovligt ejede CS-filer.
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
| `limit` | error > 90 %, warning > 75 % | .bsp | HLSDK `MAX_MAP_*` + AllocBlock fra compileren |
| `spawn_count`, `bomb_targets`, `buyzone_count` | error | .bsp (.map hvis compile fejlede) | FITNESS; per-map override i `maps/<map>/validate.yaml` |
| `spawn_stuck` | error | .bsp | stående hull passer ikke ved spawn-origin |
| `narrow_passage`, `low_ceiling` | warning | .bsp | gangbare celler (hull 1) med fri bredde < 64 eller loftshøjde < 96 |

Begrænsninger:
- Korridorbredde måles langs x- og y-aksen, så diagonale gange vurderes for bredt (lempeligt, aldrig falsk alarm).
- "Alle spawns kan nå begge sites" kræver sites fra layout-spec/YAPB-graf og kommer i fase 2/4.
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
