# Graph Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A graph editor on the local website for designing new maps (spawns, sites, rooms, connections → layout.yaml) and for sending graph changes to a running map, with a skip for the current loop iteration.

**Architecture:** Python owns the data (graph.json schema, topology folding, graph diff → Decide ops, graph → layout, skip flag); the live API exposes it; a static page (vanilla JS, ported from the accepted spike) edits it. Decide carries out graph wishes with two new operators (`add_corridor`, `set_level`) and lifted per-iteration limits.

**Tech Stack:** Python 3.11 (numpy, pyyaml, ruamel), vanilla JS/SVG, asyncio HTTP in mapforge/live/collector.py, pytest, Docker (`./mf`).

**Spec:** `docs/superpowers/specs/2026-10-16-graph-editor-design.md`. Spike to port (accepted by the human): `.superpowers/brainstorm/1596-1792164933/content/graph-editor-spike16.html` (template in the session scratchpad `editor_tpl.html`).

## Global Constraints
- Docker is the official way: run everything with `./mf <task>` (PowerShell: `./mf.ps1`); `docker compose run --rm --quiet forge uv run pytest -q tests/<file>` for a single test file.
- LF line endings; no hardcoded paths (use `cfg.path(...)`, `MAPS_DIR`); type hints; `ruff` clean (line length 100).
- Board scale: 6144 × 6144 units; edge time = straight distance × 1.3 + 96 per level change (× 2 on `ladder`), or `len` when set; 250 u/s.
- Bands (DESIGN_GUIDE): T→site 14–26 s; CT first ≥ 3 s; rotation 10–15 s; entrances 2–3; no 4-way junctions; no spawn→site door.
- Node roles `T|CT|A|B|room` (T, CT, A, B unique); levels −1/0/+1; sizes S 384, M 640, L 896, XL 1152; edge kinds `corridor|choke|drop|ladder`; widths narrow 96 / normal 160 / wide 256.
- graph.json limits: ≤ 200 nodes, ≤ 400 edges, ids `^[a-z][a-z0-9_]{0,31}$`, positions |x|,|y| ≤ 4096, text ≤ 2000 characters.
- Per feature commit (CLAUDE.md rule 7): `./mf test` + `./mf lint` green → ROADMAP/docs updated → `docs/overview.html` updated and `./mf site` rebuilt → commit → push. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Writes to the live API only from `MAPFORGE_SITE_ORIGINS`; the live container can write only `maps/`.

## Review Focus
1. A graph posted with a missing or duplicated spawn/site, a dangling edge or a self-loop → the API answers 400 with a clear message, nothing is written (Task 1 tests `test_validate_rejects_*`).
2. Change mode on a map without graph.json whose layout has angled corridors and bridges → folding still gives a connected graph whose ids are layout area names (Task 1 `test_fold_keeps_angled_corridor_and_bridge`).
3. A graph wish on a frozen map (de_forge01) → stored, marked `needs_human` at once, never applied (Task 3 `test_graph_wish_on_frozen_map_needs_human`).
4. Skip pressed while the loop waits for a review answer, then `./mf loop` run → goes to decide, deletes the flag, records "skipped" (Task 5 `test_skip_while_awaiting_review`).
5. fromgraph on rooms placed so close they overlap → rooms pushed apart, generate still succeeds, the report says what moved (Task 4 `test_overlapping_rooms_are_pushed_apart`).

---

### Task 1: Graph model (schema, folding, diff → ops)

**Files:**
- Create: `mapforge/graph.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces:
  - `ROLES = ("T", "CT", "A", "B", "room")`, `KINDS = ("corridor", "choke", "drop", "ladder")`, `SIZES = {"S": 384, "M": 640, "L": 896, "XL": 1152}`, `WIDTHS = {"narrow": 96, "normal": 160, "wide": 256}`
  - `validate(graph: dict) -> dict` (clean copy; raises `ValueError`)
  - `path_of(maps_dir: Path, map_name: str) -> Path` (`maps/<map>/graph.json`), `load(maps_dir, map_name) -> dict | None`, `save(maps_dir, map_name, graph: dict) -> dict` (validates, atomic write)
  - `from_layout(layout: dict) -> dict` (a graph from `mapforge.topology.extract`, plain corridor areas folded into edges with `via_area`)
  - `diff_ops(before: dict, after: dict) -> list[dict]` (Decide changes: `{"type", "params", "why"}`)
  - `summary(ops: list[dict]) -> str` (one line per op, ≤ 500 chars total, for the wish text)
- Node: `{"id", "name", "role", "level", "size", "outdoor", "desc", "pos": [x, y]}`; edge: `{"a", "b", "kind", "width", "len", "desc", "via_area"?}`; graph: `{"version": 1, "map", "status": "draft|approved", "nodes", "edges", "suggestions": [], "estimate": {}}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_validate_accepts_a_minimal_graph(): ...   # T, CT, A, B + 2 rooms, 6 edges -> same ids back, defaults filled (size "M", kind kept, width "normal")
def test_validate_rejects_missing_spawn():         # no CT -> ValueError match "CT"
def test_validate_rejects_duplicate_site():        # two nodes role "A" -> ValueError match "A"
def test_validate_rejects_dangling_edge_and_self_loop()  # edge to "nope", edge a == b -> ValueError
def test_validate_rejects_out_of_bounds_and_long_text()  # pos [5000, 0]; desc 2001 chars -> ValueError
def test_save_and_load_roundtrip(tmp_path)          # save -> load equal; file ends with "\n"
def test_fold_keeps_angled_corridor_and_bridge():   # from_layout(yaml of maps/de_viaduct01/layout.yaml):
    # every node id is an area name of the expanded layout; graph connected; sites/spawns present;
    # at least one edge has via_area; no node has role "corridor"
def test_fold_forge01_has_four_chokes():            # from_layout(de_forge01) -> 4 edges kind "choke"
def test_diff_add_far_connection_is_add_corridor(): # add edge between two rooms 2000 apart -> [{"type": "add_corridor", "params": {"from_area", "to_area", "width": 160}}]
def test_diff_add_near_connection_is_add_connection()  # rooms one wall apart (layout rects) -> add_connection
def test_diff_remove_folded_corridor_is_remove_area()  # remove edge with via_area "mid_s" -> remove_area target mid_s
def test_diff_moves_and_levels():                   # moved room 800 -> move_corridor delta [dx, dy] on the 16 grid; moved T -> move_spawn; level 0 -> 1 -> set_level target, floor 160
def test_diff_rename_and_desc_are_notes_only():     # only name/desc changed -> [] ops; summary mentions the rename
```

Fixtures: build graphs inline; use `yaml.safe_load` of real layouts from `maps/` for folding.

- [ ] **Step 2: Run** `docker compose run --rm --quiet forge uv run pytest -q tests/test_graph.py` → FAIL (module missing).

- [ ] **Step 3: Implement `mapforge/graph.py`.** `from_layout` starts from `mapforge.topology.extract(layout)`: node ids/positions/levels from it (`_c`, `level`, `site`, role mapping site→A/B, t_spawn→T, ct_spawn→CT, else room; size from the topology's `size`); then repeatedly fold a node with role `corridor` and exactly two neighbours into one edge (`via_area` = its id, kind `choke` if either door is a choke, else `corridor`; door kinds `stairs|ramp` → `corridor`, `hatch|ladder` → `ladder`, `drop` stays). `diff_ops` needs "one wall apart" for add_connection vs add_corridor: pass the layout rects through the graph as node `rect` (from the topology members' bounding box) and treat |gap| ≤ 48 as adjacent. Moves snap to 16.

- [ ] **Step 4: Run** the test file → PASS.

- [ ] **Step 5: Commit** (with the next task's API, see Task 2 Step 6; this task alone has no user-visible change).

### Task 2: Live API (graph, topology-as-graph, changes, skip)

**Files:**
- Modify: `mapforge/live/collector.py` (`maps_api`; new `loop_api`; router in `http`)
- Create: `mapforge/skip.py` (`request(maps_dir, map_name, reason) -> dict`, `pending(maps_dir, map_name) -> dict | None`, `clear(maps_dir, map_name) -> None`; file `maps/<map>/skip.json`)
- Test: `tests/test_live.py` (extend), `tests/test_skip.py`

**Interfaces:**
- Consumes: Task 1 `validate`, `load`, `save`, `from_layout`, `diff_ops`, `summary`; Task 3 `annotations.add_graph_wish`.
- Produces endpoints:
  - `GET /api/maps/<map>/graph` → graph.json, or 404 `{"error": "no graph"}`
  - `PUT /api/maps/<map>/graph` `{graph, approve: bool}` → 200 saved graph (status "approved" when approve)
  - `GET /api/maps/<map>/topology` → `{"graph": graph.json if present else from_layout(layout), "frozen": bool}`
  - `POST /api/maps/<map>/changes` `{before, after}` → 201 the stored wish
  - `POST /api/loop/<map>/skip` `{reason?}` → 202 `{"requested": true, "loop": {status, step, iteration}}`; 409 when the loop is stopped or absent
  - `GET /api/loop/<map>` → `{status, step, iteration, skip: pending|null}` (read-only, any origin)

- [ ] **Step 1: Write failing tests** in `tests/test_live.py` following its existing pattern (call the api coroutine with a fake writer, assert status + JSON): `test_graph_put_get_roundtrip`, `test_graph_put_rejects_invalid_with_400_and_writes_nothing`, `test_topology_endpoint_folds_layout`, `test_changes_creates_graph_wish`, `test_skip_writes_flag_and_409_when_stopped`, `test_writes_refused_from_foreign_origin`. In `tests/test_skip.py`: `test_request_pending_clear(tmp_path)`.
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.** Route `/api/loop` in `http` like the others (body cap 200 000 stays; graph posts fit). Loop state is read from `runs/<map>/loop.json` via the config's `runs_dir` (read-only mount is fine). `frozen` = `decide.policy.locked_for(load_fitness(), map).get("geometry_frozen")`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5:** Update `docs/MAPMAKER.md` "Dashboard → API" list with the new endpoints.
- [ ] **Step 6: Commit + push** Tasks 1–2: `Graph editor: graph.json model, folding, diff -> ops and the live API`.

### Task 3: Graph wishes in annotations, Decide and apply (`add_corridor`, `set_level`)

**Files:**
- Modify: `mapforge/annotations.py` (kind `graph`; `add_graph_wish`; `prompt_text` lists ops)
- Modify: `mapforge/decide/policy.py` (`check_plan`: lifted limits for graph-wish changes)
- Modify: `mapforge/loop/apply.py` (`_apply_one`: `add_corridor`, `set_level`)
- Modify: `config/fitness.yaml` (`allowed_changes.add_corridor`, `allowed_changes.set_level`, both `before_gate_b_only`, `requires_annotation`)
- Modify: `docs/LAYOUT_SPEC.md` ("Hvad Decide kan ændre": the two operators and the lifted limits)
- Test: `tests/test_annotations.py` (or extend the existing annotations tests file), `tests/test_decide_policy.py`, `tests/test_apply.py` (or the existing apply tests)

**Interfaces:**
- Consumes: Task 1 `diff_ops`, `summary`, `validate`.
- Produces:
  - `annotations.add_graph_wish(maps_dir, map_name, before: dict, after: dict, frozen: bool) -> dict` — stores `{kind: "graph", text: summary(ops), points: [], graph: {before, after}, ops, status: "needs_human" if frozen and any structural op else "open"}`.
  - Operator `add_corridor` params `{from_area, to_area, width, via?: [[x, y]]}` → appends a `corridors:` entry `{name: "c_<from>_<to>", from, to, width, height: 192, between: [from_area, to_area]}` where `from`/`to` are the middles of the two areas' facing walls one wall outside them (grid-snapped); `via` passes through. Description returned: `"corridor c_x_y added between x and y"`.
  - Operator `set_level` params `{target, floor}` → the area's `floor` (multiple of 16; guarded like `move_corridor`).
  - Policy: a change whose `addresses` names `annotation:<id>` of a wish with kind `graph` skips `max_abs_delta`, `max_per_iteration` and the one-connection limit; all other checks stay. `check_plan` gets the wishes through a new optional parameter `graph_wishes: set[str] | None = None` (ids like `"annotation:7"`), passed by `mapforge/decide/run.py` and `mapforge/loop/run.py` from `annotations.load`.

- [ ] **Step 1: Failing tests:** `test_graph_wish_stored_with_ops`, `test_graph_wish_on_frozen_map_needs_human` (frozen=True + an add_connection op → status needs_human), `test_prompt_text_lists_graph_ops`, `test_policy_lifts_limits_for_graph_wish` (two add_connection + a move delta 800 addressing a graph wish → accepted; same without the address → rejected), `test_policy_frozen_still_rejects_graph_wish`, `test_add_corridor_generates` (apply to `maps/de_nasa/layout.yaml` copy: corridor between `b_tunnels_s` and `mid_s`, then `try_generate` passes and the topology has an edge path between them), `test_set_level_changes_floor`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (as Interfaces). Decide's prompt (`decide/run.py annotations_text`) shows graph wishes as "REQUESTED by the human: <ops as JSON>; carry them out with addresses annotation:<id>, or explain why not".
- [ ] **Step 4: Run** the three test files → PASS; run `tests/test_loop.py` → still PASS.
- [ ] **Step 5: Commit + push:** `Graph wishes: Decide carries out a human's graph change (add_corridor, set_level, lifted limits)`.

### Task 4: Graph → layout (`./mf fromgraph`)

**Files:**
- Create: `mapforge/fromgraph.py`
- Modify: `Taskfile.yml` (task `fromgraph`, `MAP` required), `CLAUDE.md` (command + "Nye maps fra dashboardet" flow: editor → approve → `./mf fromgraph` → Claude adds details from the descriptions → generate → validate → render → loop)
- Test: `tests/test_fromgraph.py`

**Interfaces:**
- Consumes: Task 1 `load`, `validate`, `SIZES`, `WIDTHS`.
- Produces: `build_layout(graph: dict, intent: dict | None = None) -> tuple[dict, dict]` (layout dict, report `{"moved": [...], "edges": [{"a", "b", "target", "actual", "ok"}], "notes": [...]}`); `main(argv) -> int` writes `maps/<map>/layout.yaml` (refuses to overwrite an existing one unless `--force`) and `build/<map>/fromgraph_report.json`.
- Mapping (spec §4): rooms square by size centred on `pos`, spawns ≥ 768 × 640, sites ≥ M; floor −160/0/+160 by level; `outdoor`; `role` T→t_spawn, CT→ct_spawn, A/B→site; `zone` t/ct/a/b/mid. Each edge → `corridors:` entry with `between`, width from `WIDTHS`, height 192 (256 when both rooms are outdoor), `via` knee when the straight corridor would cross another room or is within 10° of 45°; `choke` → its door into the target room narrowed to 128 (`doors` override with `frame` + `light`) and a `chokes:` entry; `drop` → `rise` downwards at the target end only one way (target floor lower by ≥ 64; if the graph has equal levels, the target room's floor −64); `ladder` → `ladders:` on the upper room's wall when rise > 64, else `rise`. `sites`, `spawns` (16 each), `buyzones: true`, `concept`/`landmarks` from `intent` when given, and each description as `notes: {<id>: <text>}` (generator ignores unknown keys — verify; if it rejects them, put them under `x_notes`).
- Fit: separate overlapping rooms (keep ≥ 16 + corridor room between non-neighbours; push along the line between centres, snap 16, ≤ 20 rounds), then per edge compare the walking length (centre → corridor → centre) with the target (`len` or distance × 1.3) and add a `via` knee to lengthen edges more than 10 % short; report edges more than 10 % long (they cannot be shortened without moving rooms).

- [ ] **Step 1: Failing tests:** `test_minimal_graph_builds` (T, CT, A, B + 2 rooms → `try_generate(layout)` passes; 16 spawns per team; both sites), `test_every_edge_becomes_a_route` (topology of the result: for each graph edge a path between the two rooms), `test_overlapping_rooms_are_pushed_apart` (two rooms at the same pos → report.moved non-empty, generate passes), `test_choke_becomes_a_framed_narrow_door` (door width 128, `frame`, `light`, `chokes` entry), `test_edge_lengths_within_tolerance` (fixture graph: every report edge `ok` or listed as too long), `test_refuses_to_overwrite_layout(tmp_path)`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `./mf generate` + `./mf validate` on a scratch map made from the de_nasa graph (Task 7) is the end-to-end check.
- [ ] **Step 5:** ROADMAP 8c: mark "Parse" and "Fit" as done in their simple form (graph → layout, ±10 %), with the date and this command.
- [ ] **Step 6: Commit + push:** `fromgraph: an approved graph becomes a layout.yaml (rooms, corridors, chokes, fit)`.

### Task 5: Skip the current iteration (loop)

**Files:**
- Modify: `mapforge/loop/run.py` (check `skip.pending` at the top of each step in `run()`, and pass a cancel callback to simulate)
- Modify: `mapforge/simulate/run.py` (`Simulation.run` checks an optional `cancel: Callable[[], bool]` before each batch; when it returns True: stop the map's HLDS containers, set `stop_reason="skipped"`, `ok=False`)
- Test: `tests/test_loop.py` (extend), `tests/test_skip.py`

**Interfaces:**
- Consumes: Task 2 `mapforge.skip.pending/clear`.
- Produces: `Loop.skip_now(at: str) -> str` — records `{"skipped": True, "at": step, "reason"}` in history, writes/extends the iteration's `NOTES.md` with `skipped by the human at <step>`, clears the flag, sets `step = "decide"`, does not touch best/rollback/counters; Decide's context (`loop_context`) says "this iteration was skipped by the human: no new simulation; carry out the open wishes".

- [ ] **Step 1: Failing tests:** `test_skip_in_build_goes_to_decide`, `test_skip_while_awaiting_review` (state awaiting review + flag → `run()` → step decide, flag gone, history has skipped), `test_skip_during_sim_is_not_scored` (simulate stubbed to return `stop_reason="skipped"` → `_evaluate` not called, best unchanged), `test_cancel_between_batches` (Simulation with a fake `run_group` and `cancel` returning True after batch 1 → one batch, stop_reason "skipped").
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_loop.py tests/test_skip.py tests/test_simulate*.py` → PASS.
- [ ] **Step 5:** CLAUDE.md loop section: one line on skip (map page button or `POST /api/loop/<map>/skip`; acted on at the next step or batch).
- [ ] **Step 6: Commit + push:** `Loop: skip the current iteration from the map page`.

### Task 6: Editor page

**Files:**
- Create: `mapforge/site/editor.py` (`editor_body() -> str`, `refgraphs(cfg, own_maps) -> dict`), `mapforge/site/editor.js`, `mapforge/site/editor.css`
- Modify: `mapforge/site/build.py` (write `editor.html`, `editor.js`, `editor.css`, `refgraphs.json`; top-bar link "Editor")
- Test: `tests/test_site_editor.py`

**Interfaces:**
- Consumes: Task 2 endpoints (`LIVE` base URL as other site JS uses, e.g. annotate.js), `build/topologies/refmap/*.json`, `mapforge.topology.extract` for own maps.
- Produces: `refgraphs.json` = `{"<name>": {"tier": "A|B|own", "nodes": [[id, role, site, level, [x, y]]], "edges": [[a, b, kind]], "choke_edges": [[a, b]]}}` (own maps keyed `own:<map>`); page modes from the hash: `#new/<map>` (load/save `GET/PUT /api/maps/<map>/graph`; "Approve graph" button sends `approve: true` with `estimate`) and `#change/<map>` (load `GET /api/maps/<map>/topology`; the before graph drawn faint; "Send as change" posts `{before, after}`; banner when `frozen`).
- Port from the spike unchanged in behaviour: tools, inspector, live check with arrows, closest reference maps (0.6 structure + 0.4 layout), suggestions with hover preview and accept/reject (accepted/rejected logged into `graph.suggestions` with `key`, `action`, `time`), templates, export. Replace the inlined `REFS` with `fetch("refgraphs.json")`; replace in-memory state with the API (autosave the draft with PUT, debounced 1 s, in new mode).

- [ ] **Step 1: Failing tests:** `test_site_writes_editor_and_refgraphs(tmp_path)` (build_site with tmp build_dir → `editor.html` references `editor.js`; `refgraphs.json` parses, contains every `build/topologies/refmap/*.json` stem and `own:de_forge01`), `test_editor_js_has_no_inlined_refs` (`/*REFS*/` absent, `refgraphs.json` fetched).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** (port the spike's JS into `editor.js`, CSS into `editor.css`, using the site's own colours from `style.css` variables).
- [ ] **Step 4: Run** → PASS; `./mf site`; open `http://localhost:8080/editor.html#new/de_scratch` and check with Playwright: place T/CT/A/B, connect, the live check fills, a suggestion appears, reload keeps the board.
- [ ] **Step 5:** `docs/overview.html` (8c: dashboard editor + live graph lint done), ROADMAP 8c items "Dashboard-editor" and "Live graf-lint" marked done (simple form, date).
- [ ] **Step 6: Commit + push:** `Graph editor page: design a map as a graph with live checks, reference similarity and suggestions`.

### Task 7: Map page and new-map guide wiring

**Files:**
- Modify: `mapforge/site/build.py` (`loop_section`: "Input to the next iteration" panel + skip button; map page "+ Add change" link `editor.html#change/<map>`; new-map guide: a "Graph" step after the intent, link `editor.html#new/<map>`), `mapforge/site/annotate.js` (render `kind: "graph"` wishes as text + before/after mini drawing), small `mapforge/site/loopctl.js` (skip button: `POST /api/loop/<map>/skip`, shows the result; polls `GET /api/loop/<map>` every 10 s)
- Test: `tests/test_site.py` (extend)

**Interfaces:**
- Consumes: Task 2 endpoints, Task 3 wish format (`graph.before`, `graph.after`, `ops`).
- Produces: the panel lists open/needs_human wishes of every kind under "Input to the next iteration", newest first; graph wishes show the op list. When `maps/<map>/graph.json` has an `estimate` and `build/<map>/validation.json` has `stats.timings`, the map page shows both side by side ("graph estimate" vs "measured", T→A, T→B, CT first at A/B) — spec §4.6 / anti-goal 1; test `test_map_page_shows_estimate_vs_measured`.

- [ ] **Step 1: Failing tests:** `test_map_page_has_add_change_and_skip(tmp_path)` (a map with loop.json running → page contains `editor.html#change/<map>` and `data-skip="<map>"`), `test_closed_map_disables_add_change` (project closed → link has `aria-disabled="true"`), `test_new_page_links_graph_step`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `./mf site`; Playwright: on de_nasa's page "+ Add change" opens the editor with de_nasa's graph; move a room and send → the wish appears under "Input to the next iteration".
- [ ] **Step 5: End-to-end on de_nasa:** draw de_nasa's graph in the editor (or start from its folded topology), approve, `./mf fromgraph MAP=de_nasa -- --force` into a scratch copy, generate → validate; record estimate vs BSP timings in the commit message. (The human then designs de_nasa's real graph; the current draft layout is replaced only when they approve one.)
- [ ] **Step 6:** ROADMAP note (8c pulled forward on the human's request, 2026-10-16), overview, `./mf site`.
- [ ] **Step 7: Commit + push:** `Map page: + Add change, input to the next iteration, skip; new-map guide graph step`.
