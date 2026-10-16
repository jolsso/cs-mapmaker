# Graph editor: design a map as a graph, and send changes to a running map

Date: 2026-10-16. Status: approved by the human ("when it's ready, you have the go to implement").
Origin: a brainstorming session and a throwaway spike (`.superpowers/brainstorm/…/graph-editor-spike16.html`,
template `editor_tpl.html` in the session scratchpad). This document replaces the spike; the spike is not code to keep.

## Why
Every map generated so far (de_forge01, de_tilt01, de_cistern*, de_viaduct01, de_nasa) shares de_forge01's
3x3 three-lane grid, because Claude wrote each `layout.yaml` from the same template. The official maps are
all different. The human wants to decide the **structure** (where spawns and sites are, which rooms connect)
and have the pipeline keep them inside the design rules, instead of Claude inventing the same layout again.

## Goals
1. **New map:** the human places T spawn, CT spawn, site A, site B and rooms, connects them, and sees the
   design checks and the closest reference maps update live. Suggestions (accept/reject) appear in a side
   pane. The approved graph is turned into a `layout.yaml` that the existing pipeline builds.
2. **Change a running map:** on any own map's page, "+ Add change" opens the same editor loaded with the
   map's current graph. The edit is sent as a wish that the next loop iteration carries out.
3. **Queued input is visible:** the map page shows what the next iteration will take as input (open wishes,
   including graph changes, with a small picture of the change).
4. **Skip:** the human can skip the running iteration, so a change is applied without waiting for the
   simulation to finish.

## Non-goals (now)
- Learned suggestions (a GAN, a trained generator or surrogate). Suggestions stay rule-based. Accepted and
  rejected suggestions are **logged** so they can become training data in phase 8g.
- "Three alternative graphs" generated for the human: replaced by templates (start from any own or reference map).
- Hand-annotated reference graphs (the 8b "facit" item) and better room segmentation of reference maps.
- Multi-level geometry beyond what the generator already has (hatches, bridges stay as today).

## Anti-goals (a failure even if it works)
- The editor's numbers silently disagree with the built map. The estimate and the measured BSP timings must
  be shown side by side after a build.
- A change on a map locked after Gate B is applied without the human's explicit approval (CLAUDE.md rule 3).
- Templates reproduce an existing map unchanged without the editor saying so (similarity > 85 % is flagged).

## Decisions made by the human
- The human places spawns and sites and draws rooms and connections; the pipeline computes corridors etc.
- Suggestions in a side pane, each with Accept / Reject; hovering a suggestion previews it on the board.
- Live check with ▲/▼ arrows (green = closer to its band, red = further away) and a total distance score.
- Similarity to reference maps: structure + layout (where CT and the sites sit relative to T, and the times).
- Templates: start from any own map or reference map (simplified skeleton by default).
- Every property of a node or connection is editable in an inspector; nodes and connections have a free-text
  **description** ("what I want from site B").
- **Claude turns descriptions into details** (cover, landmarks, height) in the session, as part of building
  the layout. Not automated without Claude.
- Changes to a running map are input to the next iteration and shown as such in the front end.
- The human can skip the current iteration.

## Parts

### 1. Editor page (`build/site/editor.html`)
Ported from the spike into the site like `graph.html`: `mapforge/site/editor.js` + `editor.css`, page body
from `mapforge/site/editor.py`, linked from the top bar ("Editor"), the new-map guide and each own map's page.
Two modes from the URL: `editor.html#new/<map>` (new map) and `editor.html#change/<map>` (running map).

Behaviour kept from the spike (it was tried by the human and accepted):
- Tools: Select (default), T, CT, A, B, Room, Connect, Move, Delete; dragging a node moves it in any tool
  except Connect/Delete; double-click renames; Undo/Clear.
- Connection kinds: `corridor`, `choke` (door/chokepoint), `drop` (one-way, first → second), `ladder`
  (stairs/ladder; a level change counts double). Edge time = straight distance × 1.3 (+96 per level, ×2 on a
  ladder) unless a length is set. 250 u/s. Board = 6144 × 6144 units, 256-unit grid.
- Inspector: node name, role (spawns/sites unique; the old holder becomes a room), level (−1/0/+1), size
  (S/M/L/XL), outdoor, description; connection kind, width (narrow/normal/wide), length, description, swap ends.
- Live check (DESIGN_GUIDE bands): T→A, T→B 14–26 s; CT first ≥ 3 s at each site; rotation 10–15 s;
  entrances 2–3 per site; CT retake route to both; no 4-way junctions; no spawn→site door; chokepoints;
  total distance from the bands. Arrows show the change since the last edit.
- Closest reference maps: overall = 0.6 × structure (Weisfeiler-Lehman features on the skeleton: dead ends
  dropped, corridor chains merged) + 0.4 × layout (CT/A/B relative to T, normalised, mirror allowed; timing
  profile). Top 3 + a mini drawing of the closest. Warn above 85 %.
- Suggestions: try every small edit (add/remove connection, move T or CT spawn, change a room's level), keep
  the three that lower the total distance most, or, when all checks pass and the map is > 80 % like a
  reference, the ones that make it least alike. Text says what changes. Hover = preview. Rejected suggestions
  are not shown again for this graph.
- Templates: own maps + reference maps, grouped (own / tier A / tier B), simplified by default, real scale
  unless it does not fit.

New in the product (not in the spike):
- The page loads and saves through the live API (below); the board survives a reload.
- In change mode, the "before" graph is fixed and shown faintly under the edited one; "Send as change" posts
  the difference. Node ids are the layout's area names, so the difference maps onto the layout.
- Reference data comes from a file the site build writes (`build/site/refgraphs.json`, from
  `build/topologies/refmap/*.json` + own topologies), not inlined in the page.

### 2. Graph file (`maps/<map>/graph.json`, versioned)
```json
{"version": 1, "map": "de_nasa", "status": "draft|approved",
 "nodes": [{"id": "b_site", "name": "B", "role": "B", "level": 0, "size": "L", "outdoor": false,
            "desc": "the satellite in a clean-room lab…", "pos": [-1792, 1440]}],
 "edges": [{"a": "b_tunnel", "b": "b_site", "kind": "choke", "width": "normal", "len": null, "desc": ""}],
 "suggestions": [{"key": "add:mid-b_tunnel", "action": "accepted|rejected", "time": "…", "metrics_before": {…}}],
 "estimate": {"tA": 18.2, "tB": 19.0, "cA": 3.1, "cB": 9.4, "rot": 14.2}}
```
Positions in world units. `estimate` is what the editor showed when the graph was approved (compared with
the BSP timings after the build).

### 3. Live API (mapforge/live, same origin rules as today)
- `GET /api/maps/<map>/graph`, `PUT /api/maps/<map>/graph` (`{graph, approve: bool}`): new-map mode.
  Validation at the boundary: schema, unique spawns/sites, ids `[a-z0-9_]`, positions within ±4096, sizes
  and kinds from the enums, ≤ 200 nodes / 400 edges, text ≤ 2000 characters.
- `POST /api/maps/<map>/changes` (`{before, after}`): change mode. Stores a wish (see 5).
- `POST /api/loop/<map>/skip`: requests a skip (see 6).
- `GET /api/maps/<map>/topology`: the current graph of an own map, from `mapforge.topology.extract`
  (so change mode needs no site rebuild).

### 4. Graph → layout (`mapforge/fromgraph.py`, `./mf fromgraph MAP=<map>`)
Deterministic code, then Claude in the session.
1. **Rooms:** one area per node, centred on its position, snapped to the 16 grid. Size: S 384, M 640,
   L 896, XL 1152 (square; spawns ≥ 768 × 640 so 16 spawns fit; sites ≥ M). Level −1/0/+1 → floor
   −160/0/+160; outdoor flag; role and zone from the role.
2. **Connections:** each edge becomes a corridor between the two rooms' facing walls: the existing
   `corridors:` macro (angled, any grid angle) with `between:` doors, width narrow 96 / normal 160 /
   wide 256, height 192 (outdoor 256). A corridor that would cross another room gets a `via` knee around it.
   `choke` → the door into the target room is narrowed to 128 and gets `frame` + `light` and a `chokes:`
   entry; `drop` → the target end is lower (a ledge); `ladder` → `ladders:` (or stairs for ≤ 64 rise);
   a level change on a corridor → `rise`.
3. **Fit:** push overlapping rooms apart (keeping one wall between neighbours), then scale corridor lengths
   until the walking times match the editor's estimate within ±10 %. Snap. Rooms with a fixed `len` keep it.
4. **Write** `maps/<map>/layout.yaml` with the soul fields (`concept` from the intent, `landmarks` and
   `chokes` from the graph, `intended_strategies` left for Claude) and every description as a comment and
   in a `notes:` block; and `build/<map>/fromgraph_report.json` (every change Fit made, with the reason).
5. **Claude** (session) reads the report and the descriptions and adds details: cover, landmarks, heights,
   props, as today when writing a layout. Then generate → validate → render, and the loop starts
   (CLAUDE.md "Nye maps fra dashboardet" is updated to this flow).
6. After the first validate, the map page shows the editor's estimate next to the measured BSP timings.

### 5. Changes to a running map (wish kind `graph`)
- The wish stored by `POST …/changes`: `{kind: "graph", text: <generated summary>, points: [], status:
  "open", graph: {before, after}, ops: [...]}` in `maps/<map>/annotations.json` (annotations.py gains the
  kind; validation as for the other kinds). The picture is drawn by the site from `before`/`after`.
- **What change mode edits:** `graph.json` when the map has one (maps made with the editor); otherwise the
  layout's topology, with plain corridor areas (role corridor, exactly two connections) folded back into
  one connection that remembers the area (`via_area`), so both modes show the same kind of graph.
- `ops` = the difference as Decide operators: added/removed edge → `add_connection`/`remove_connection`;
  an added connection between rooms that are not one wall apart → `add_corridor` (new operator: the
  `corridors:` macro with `between:`); a removed connection that is a folded corridor area → `remove_area`;
  moved node → `move_corridor` (rooms) or `move_spawn`; level change → `set_level` (new operator, an area's
  floor) ; kind/width change → `adjust_opening`/`set_gate`; new node → `add_area` (the wish is the required
  annotation); removed node → `remove_area`. Rename and descriptions → layout `notes:` only.
- Decide's prompt lists graph wishes with their ops as **requested changes**: Decide carries them out
  (with `addresses: annotation:<id>`) or explains why not. For changes that address a human graph wish, the
  per-iteration limits (one connection change, max 1 of a kind) and `max_abs_delta` (±256 moves) do **not**
  apply; locks, protected elements and minimum widths do. Moving a room can break its doors: Decide moves the
  neighbouring corridors along, and apply's trial generate skips what cannot be built, with the reason.
- Locked maps (`geometry_frozen`): the editor opens with a banner; structural ops are stored, the wish is
  marked `needs_human` at once and Decide does not apply them. They go through only after the human unlocks.
- After the iteration the wish is done/needs_human as today.

### 6. Skip the current iteration
- `POST /api/loop/<map>/skip` writes `maps/<map>/skip.json` (time + reason; `maps/` is the live container's
  only writable mount, like `project.json`). The live container cannot stop the loop process; the loop
  checks the flag:
  - at every step boundary, and while simulating (between batches; `simulate` gets a cancel check), and
  - if the loop is waiting for a review/decide answer, the next `./mf loop` run sees it.
- Skip in `build` or `review` (or while waiting for a review answer): go straight to `decide`. Skip during
  `sim`: finished batches stay on disk but are not scored. The loop deletes `skip.json` when it acts on it.
- On skip: stop the map's HLDS containers, record the iteration as `skipped` (history, `NOTES.md`: "skipped
  by the human at <step>"), go straight to `decide` with no new simulation metrics (Decide's prompt says so;
  the last measured metrics stay the baseline). Best/rollback are not updated from a skipped iteration.
- Skip does nothing when the loop is stopped; the API returns the loop state so the button can say so.

### 7. Front end on the map page
- "+ Add change" button (opens the editor in change mode); disabled on a closed map.
- "Input to the next iteration" panel at the top of the loop section: open wishes (drawings, notes, in-game
  notes and graph changes), each graph change with a small before/after picture and its ops.
- "Skip current iteration" button with the current step ("simulating, batch 2/4"); a confirm dialog.

## Constraints
- Docker is the official way; host Python only for debugging. LF files. No hardcoded paths (config).
- CLAUDE.md rules: commit + push per feature; `./mf test` + `./mf lint` green; ROADMAP + `docs/overview.html`
  updated and `./mf site` rebuilt before each commit.
- This pulls 8c items forward (dashboard editor, live graph lint, Parse/Fit) while 8a acceptance and the rest
  of 8b are open; the human asked for it. ROADMAP records the reorder.
- The local site is static + the live API (no build step for JS, no libraries).

## Calls made by Claude after the builder check (the human pre-approved the design)
1. Change mode edits `graph.json`, or the folded topology for maps without one (section 5).
2. Long new connections → new operator `add_corridor`; removed folded corridors → `remove_area` (section 5).
3. Human graph wishes lift the per-iteration limits and the ±256 move cap; Decide carries them out; no
   re-run of fromgraph on a running map (it would wipe the details Claude added).
4. The skip flag lives in `maps/<map>/skip.json` (writable mount); no compose change.
5. Skip before the simulation goes straight to Decide; partial batches are not scored.

## Left to the builder
- Exact file split of the JS, CSS details, the mini-drawing style.
- Fit's algorithm details (any deterministic method that meets ±10 % and keeps rooms apart).
- How the site draws the before/after picture.
- Test design: Python tests for fromgraph (no overlapping rooms, every edge becomes a walkable door, generate
  succeeds, timings within tolerance on a small fixture), the graph API validation, the `graph` wish kind,
  the skip flag; a Playwright-free smoke check of the editor page (it is built and references its data).
