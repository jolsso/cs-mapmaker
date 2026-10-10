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
| 2 Compile | `.map`, WADs | `.bsp`, compile-log | VHLT: hlcsg → hlbsp → hlvis → hlrad |
| 3 Validate | `.bsp`, log | `validation.json` (leaks, limits, r_speeds-estimat) | Python BSP-parser, newbspguy `info` |
| 4 Render | `.bsp` | PNG: top-down, kameraviews, lysstyrkekort | newbspguy → OBJ → Blender headless; klient-screenshots for lys |
| 5 Simulate | `.bsp`, YaPB-graf | CSV-events (se TRACKER_SPEC.md) | HLDS (Docker) + Metamod + AMXX + YaPB |
| 6 Analyze | CSV, renders | `metrics.json`, heatmaps | Python (pandas, numpy, matplotlib) |
| 7 Decide | metrics, billeder, FITNESS.md | ændringsplan + næste .map | Claude Code headless (`claude -p`) |

## Komponenter

### Generator (`generator/`)
- Layout-spec i YAML: rum, korridorer, højder, sites, spawns, forbindelser.
- Producerer konvekse brushes på grid, forseglet ydre skal, entities.
- Skal kunne round-trippe: læse en eksisterende .map, ændre, skrive tilbage.

### Compile (`compile/`)
- Profiler: `fast` (hurtig iteration, lav rad-kvalitet) og `final` (`-extra`, flere bounces).
- Parser compile-log til struktureret JSON (warnings, errors, leak-koordinater fra pointfile).

### Validate (`validate/`)
- BSP-parser (lumps: entities, planes, faces, lighting, clipnodes, leafs).
- Tjek mod limits og design-normer i CLAUDE.md.
- Lysstyrkekort: sample lighting-lump pr. face → top-down grid → flag mørke spilområder.

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
cs16-mapforge/
├── CLAUDE.md
├── Makefile
├── config/
│   ├── pipeline.yaml        # stier, profiler, budget
│   ├── fitness.yaml         # tærskler (spejler FITNESS.md)
│   └── cameras/
├── docs/
├── generator/
├── compile/
├── validate/
├── render/
├── server/
│   ├── Dockerfile
│   ├── plugins/             # AMXX .sma
│   └── cfg/
├── analyze/
├── orchestrator/
├── maps/<navn>/
│   ├── layout.yaml
│   ├── ART_DIRECTION.md
│   └── src/<navn>.map
├── assets/
│   ├── wads/
│   └── LICENSES.md
└── runs/<navn>/<iteration>/
```

## Afhængigheder (verificér versioner ved opsætning)
- VHLT (Vluzacn's ZHLT) compilere
- newbspguy (UnrealKaraulov) – Windows/Linux
- Blender (headless) eller pyrender
- HLDS via SteamCMD, Metamod(-R), AMX Mod X, YaPB
- Python: numpy, pandas, matplotlib, pyyaml, pillow
