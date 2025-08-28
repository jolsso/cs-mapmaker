# cs-mapmaker

Visual-first, AI-assisted CS 1.6 map maker. Describe a concept, see it instantly as a 2D layout, refine with direct manipulation and AI suggestions, and export clean `.map` files.

## Quickstart (Task)
- Prereqs: Python 3.10+ and pip installed.
- Install Task (choose one):
  - Windows (Scoop): `scoop install task`
  - Windows (Chocolatey, Admin): `choco install go-task -y`
  - Cross‑platform (pip fallback): `pip install go-task-bin` (ensure the pip Scripts directory is on PATH; see Troubleshooting below)
- Start the backend and UI: `task run`
  - API docs: http://127.0.0.1:8000/docs
  - UI (prototype): http://127.0.0.1:8000/ui/
- Run tests: `task test`

What `task run` does:
- Creates a virtualenv at `backend/.venv`
- Installs backend dependencies
- Runs `uvicorn app.main:app --reload --port 8000`

## Why Visual-First
- Keep the canvas central: every action updates the view.
- AI is a co-pilot: it proposes diffs you can preview and apply.
- Deterministic generation ensures compile-friendly, reproducible maps.

## UX Principles
- Visual-first: Canvas is the source of truth; edits are always visible.
- AI as co-pilot: Suggestions arrive as diffs, never silent overwrites.
- Progressive disclosure: Start simple; reveal advanced controls as needed.
- Safe by design: All changes are reversible, validated, and seedable.

## Information Architecture
- Left Panel: Projects/maps, versions, layers, templates.
- Canvas (Center): 2D top-down, grid + snapping, rulers, overlays.
- Right Panel: Properties inspector and AI prompt/chat.
- Bottom Bar: Metrics (route timings, chokepoints), job progress/logs, undo/redo.

## First-Time Onboarding
- Coach marks highlighting prompt box, Generate, and canvas controls.
- 6-10 curated templates (symmetry, size, route count).
- Empty state prompt with example chips (type, symmetry, theme, size).

## Flow: Concept -> Layout
- Prompt Box: Free text + chips for map type, symmetry, theme, size.
- AI Parse: Extracted constraints shown as editable chips for transparency.
- Generate Preview: Intent -> layout; renders areas, paths, spawns/objectives.
- Quick Tuners: Sliders for scale, corridor width, chokepoint density, symmetry toggle.
- Risk Hints: Inline warnings for timing imbalance, loops, sightlines.

## Flow: Layout -> Geometry
- Commit Concept: 'Looks good -> Make geometry' triggers deterministic generation.
- Preview Layers: Toggle brush outlines, cover modules, entities.
- Validation Panel: Leak risk, brush counts, unreachable paths, timing parity.

## Editor (Visual-First)
- Direct Manipulation: Drag walls/vertices, resize rooms, rotate, snap-to-grid.
- Entity Palette: Spawns, bombsites, buyzones; click-to-place with guides.
- Properties: Contextual fields (width, height, elevation, texture preset).
- Guides: Route time heatmap, choke widths, sightlines overlay.

## AI Co-Pilot
- Ask: 'Narrow mid by ~20%', 'Add alternate connector to A'.
- Propose: Side-by-side diff and overlay highlights of changed polygons/entities.
- Apply: JSON Patch; create a new version with seed/config notes.
- Explain: Why-summary (timing delta, chokepoint count change, validation effects).

## Feedback & Metrics
- Sanity Meters: Route parity, chokepoint and cover density, portal complexity.
- Inline Deltas: Before/after metrics for every change (manual or AI).
- Tooltips: Short guidance with recommended ranges.

## Versioning & History
- Timeline: Named versions with thumbnails and key metrics.
- Branching: 'Try alternative mid' -> branch; visual merge/compare.
- Compare: Split-view canvas; toggle layers to see what changed.

## Jobs & Progress
- Non-blocking: Long tasks run in background; progress toast + bottom logs.
- Artifacts: Preview PNG/SVG, validation JSON, `.map`, optional `.bsp`.
- Retry/Pin: Re-run with same seed; pin stable versions.

## Import/Export
- Import `.map`: Parse and render; warn on invalid brushes; baseline version.
- Export: Always `.map`; optional compile to `.bsp` with logs.

## Keyboard & Micro-Interactions
- Shortcuts: Pan (Space+Drag), snap (Shift), align (A), measure (M).
- Context Menu: Area/path -> duplicate/mirror, add connector, set width.
- Grid Controls: Quick grid-size switcher; dev grid textures toggle.

## Error Handling & Guardrails
- Soft Blocks: Red outlines for illegal geometry; explain constraints.
- Recoverable Edits: All changes are reversible and logged as patches.
- Licensing: Clear WAD pack selection; disclaimers for third-party content.

---

## Architecture (Concise)
- Frontend: SvelteKit (TypeScript) + Canvas 2D (WebGL later if needed).
  - Note: A minimal static prototype UI is currently served at `/ui` (see Frontend UI below) while the full SvelteKit app is scoped for later.
- Backend: Python FastAPI for API, AI orchestration, geometry/brush generation.
- Jobs: Redis + Celery for async generation/compile; progress via WebSocket (SSE optional).
- Storage: Local dev: SQLite + filesystem. Production: Postgres (metadata/specs) + S3-compatible blobs (artifacts). Optional Dockerized compile workers (VHLT, Phase 2).
- Deterministic Core: Separate geometry/brush engine; seedable and unit-tested.
- Realtime: WebSocket for events; SSE for logs-only streams if desired.

## Core Data Model (Brief)
- Project, MapVersion (immutable), MapIntent (from prompt), LayoutGraph, Geometry2D, BrushSet, Artifacts.

## Patch Targets
- Intent: JSON Patch over `MapIntent` for high-level goals.
- Layout: JSON Patch over `LayoutGraph` (nodes/edges, widths, symmetry).
- Geometry: JSON Patch over `Geometry2D` (polygons, elevations, modules).
Every applied patch creates a new `MapVersion` with seed/config stored.

## API Surface (Draft)
- POST `/concepts`: prompt -> MapIntent.
- POST `/layouts`: intent -> LayoutGraph + preview image.
- POST `/geometry`: layout -> Geometry2D + preview image.
- POST `/maps`: geometry -> `.map` + validation report.
- POST `/edits`: NL prompt -> JSON Patch -> new MapVersion.
- POST `/compile`: optional `.bsp` compile; logs/artifacts (Phase 2).
- GET `/versions/{id}`: metadata + artifact links.
- WS/SSE `/progress`: job updates.

## MVP Scope
- Must: Prompt -> layout preview, quick tuners, geometry generation, editor basics, AI diffs with preview, versioning, `.map` export, validation panel.
- Later: `.bsp` compile, multi-user collab, texture painting, template RAG.

## Next Steps
- Scaffold SvelteKit pages: Concept/Preview and Editor (Canvas).
- Define Pydantic models for MapIntent, LayoutGraph, Geometry2D, BrushSet.
- Stub FastAPI routes and Redis-backed Celery jobs; stream progress to frontend via WebSocket.
- Implement a basic rectilinear layout -> geometry prototype with dev grid textures.

---

## Diagrams
- Source (Mermaid): `docs/diagram.mmd` (class + sequence)
- Export PNG (Windows): `./scripts/export-diagram.ps1`
- Export PNG (Node-only): `npx -y @mermaid-js/mermaid-cli -i docs/diagram.mmd -o docs/diagram.png`

Preview (after export):

![UML overview](docs/diagram.png)

---

## Backend (FastAPI) — Getting Started

- Install Python 3.10+.
- Create a venv and install deps:
  - Windows PowerShell:
    - `cd backend`
    - `python -m venv .venv`
    - `.\.venv\Scripts\Activate.ps1`
    - `pip install -r requirements.txt`
  - macOS/Linux:
    - `cd backend`
    - `python -m venv .venv`
    - `source .venv/bin/activate`
    - `pip install -r requirements.txt`
- Run the API:
  - `uvicorn app.main:app --reload --port 8000`

Endpoints (stubbed, deterministic):
- `POST /concepts`: `{ prompt }` -> `MapIntent`
- `POST /layouts`: `MapIntent` -> `LayoutGraph`
- `POST /geometry`: `LayoutGraph` -> `Geometry2D`
- `POST /maps`: `Geometry2D` -> `MapExport`
- `POST /edits`: `{ prompt }` -> `{ version_id, patch[] }`

Quick check:
- `GET /` -> `{ service: "cs-mapmaker", status: "ok" }`
- `GET /health` -> `{ status: "healthy" }`

---

## Frontend UI (Prototype)
- Served by FastAPI at `/ui` using static files in `frontend/`.
- Files to tweak:
  - `frontend/index.html` — page structure and controls
  - `frontend/styles.css` — dark theme styles
  - `frontend/app.js` — calls API endpoints and renders geometry to canvas
- Usage flow:
  - Enter a prompt and click “Generate Concept” (or “Run All”).
  - Click “Generate Layout”, then “Generate Geometry” to see a preview square.
  - Click “Export Map” to get artifact links.
  - Use “Propose Edit” to send a natural‑language edit and get a deterministic version id.

## Task Targets
- `task bootstrap`: Create venv and install deps
- `task run`: Start FastAPI with reload on port 8000
- `task test`: Run pytest

## Troubleshooting Task on Windows
If you installed Task via pip and `task` is not found, add pip’s user Scripts directory to your PATH.

For Microsoft Store Python 3.13, the default location is:

```
%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts
```

You can set it for your user in PowerShell:

```
[Environment]::SetEnvironmentVariable(
  'Path', $env:Path + ';' + "$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts",
  'User'
)
```

Then restart your shell and run `task run` again.
