# cs-mapmaker

AI-assisted CS 1.6 map generator. Prompt an idea, visualize a 2D overview, generate `.map` files, and iteratively edit with AI suggestions.

**Stack**
- Frontend: SvelteKit (TypeScript) + Canvas/WebGL for 2D preview/editing
- Backend: Python (FastAPI) for API + AI orchestration and geometry/brush generation
- Jobs: Celery or RQ with Redis for async tasks (generation/compile)
- Storage: Postgres (metadata/specs), S3-compatible blob store (artifacts), optional Dockerized compile workers

**Goals**
- Map target: GoldSrc/CS 1.6 `.map` (brush-based) with valid entities
- AI + prompting: Natural language → structured design spec → deterministic generation
- Fast 2D iteration: Top-down layout preview and safe, incremental edits
- Deterministic core: Reproducible builds; validation against common pitfalls (leaks, limits)

**System Overview**
- Frontend (SvelteKit)
  - Concept/Preview page: Prompt, review constraints, 2D layout preview, quick tuners
  - Editor page: 2D orthographic editor with snapping, entity placement, AI-assisted diffs
  - Realtime: WebSocket/SSE progress for long-running jobs
- Backend (FastAPI)
  - API Gateway: REST for CRUD + job submission; WS/SSE for progress
  - AI Orchestrator: LLM calls, schema validation, guardrails
  - Geometry/Brush Engine: Deterministic conversion of spec → layout → brushes → `.map`
  - Map I/O: `.map` parser/serializer; optional `.bsp` compile integration
  - Workers: Async generation/compile tasks with structured logs and retries

**Core Data Model**
- Project: name, default WAD packs, settings
- MapVersion: immutable snapshot; parent pointer; authored by user/AI; artifacts
- MapIntent (AI-facing): extracted from prompt; map type/size/theme/goals
- LayoutGraph: nodes (areas/objectives/spawns), edges (paths/chokepoints)
- Geometry2D: polygons per room/corridor, widths, elevations, snapping grid
- BrushSet: convex brushes, textures/alignments, entity list with keyvalues
- Artifacts: `.map`, preview images, validation/compile logs, optional `.bsp`

**AI → Geometry Pipeline**
1) Prompt → Intent: LLM produces `MapIntent` JSON (schema-validated)
2) Intent → Layout: Programmatic generator (graph) with LLM-assisted constraint checks
3) Layout → Geometry: Deterministic 2D polygons with widths, cover, elevation; grid-snap
4) Geometry → Brushes: CSG-friendly convex brushes; textures; entity placement
5) Validation: Leak detection, reachability, brush/face limits, path timings
6) Edit with AI: Natural language → JSON Patch ops → preview diff → apply

**API (FastAPI, draft)**
- POST `/concepts`: prompt → `MapIntent`
- POST `/layouts`: intent → `LayoutGraph` + preview image
- POST `/geometry`: layout → `Geometry2D` + preview image
- POST `/maps`: geometry → `.map` + validation report
- POST `/edits`: NL prompt → patch ops → new `MapVersion`
- POST `/compile`: build `.bsp` from `.map` (optional, containerized)
- GET `/versions/{id}`: metadata + artifact links + validation
- WS/SSE `/progress`: subscribe to job updates

**Frontend (SvelteKit) Features**
- Canvas-based 2D views: layers for areas, paths, entities, cover, measurements
- Controls: drag walls, resize rooms, snap-to-grid, rotate, align, texture presets
- AI Assistant: chat UI proposes patch ops; side-by-side diff overlay before apply
- History: version timeline, branching, rollback, import/export `.map`

**Backend (Python) Components**
- Schemas: Pydantic models for `MapIntent`, `LayoutGraph`, `Geometry2D`, `BrushSet`
- Orchestration: LLM client with schema/JSON mode and output validation
- Geometry Engine: deterministic generators; unit-tested; seedable
- Map I/O: `.map` parser/serializer; texture/WAD presets for dev grid textures
- Validation: flood-fill leak checks, brush limits, portal complexity heuristics
- Compile (optional): VHLT (`hlcsg`, `hlbsp`, `hlvis`, `hlrad`) via Docker; logs/artifacts captured

**Storage & Ops**
- DB: Postgres (JSONB for specs); migrations with Alembic if needed
- Queue: Redis for Celery/RQ; idempotent job payloads with versioned seeds/configs
- Blobs: S3 bucket paths per Project/MapVersion; signed URLs for downloads
- Observability: structured logs, job traces, artifact retention policy

**MVP Milestones**
1) Prompt → Intent → 2D layout preview; save versions
2) Geometry generation + `.map` export + validation report; import `.map`
3) AI edit diffs with preview; version history and visual diffs
4) Optional compile to `.bsp`; texture packs; performance checks

**Implementation Notes**
- Keep the deterministic geometry/brush engine separate from AI logic
- Use JSON schemas and JSON Patch for safe, testable AI edits
- Store seeds, tool versions, and config with each `MapVersion` for reproducibility

**Next Steps**
- Define Pydantic models for `MapIntent` and `MapSpec`
- Stub FastAPI routes and job submission with Redis
- Scaffold SvelteKit pages: Concept/Preview and Editor (Canvas)
- Implement a basic rectilinear layout → geometry prototype with dev grid textures
