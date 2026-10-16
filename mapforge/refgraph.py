"""Topology of a compiled map (BSP): rooms and connections from the walk graph (ROADMAP 8b).

The same graph format as `mapforge.topology` (source: bsp), so reference maps sit next to our
own maps on the Graph page and in the datasets. Steps:

1. Walk graph from the spawns (mapforge.validate.walk, the validator's settings).
2. Floor patches: the walk nodes in each `CELL`x`CELL` column, split into connected pieces (a
   floor above another floor is its own patch).
3. Clearance: units from the nearest edge of the walkable floor (on the fine walk grid).
4. Watershed on the clearance, highest first: a patch joins the neighbouring room with the
   highest peak. Two rooms meet at a saddle; they stay apart only when the saddle is a real
   narrowing (below `RATIO` of the lower peak and more than `SLACK` lower) - a door, not a crate.
   Rooms smaller than `MIN_CELLS` patches go to the neighbour they touch most.
5. Nodes: sites from the bomb targets, spawns from the spawn entities; a room holding two of
   them (CT spawn on a site) is split between them. Walk nodes in trigger_hurt are dropped.
   Edges: where two rooms touch; one-way only = `drop`, at a func_ladder = `ladder`,
   crouch-only = `vent`, a height step = `stairs`. Big open yards stay one hub room.

A heuristic: rooms are "places between narrowings", not the mapper's own names. Lengths are
estimates (centre -> opening -> centre); the walk graph gives the real timings (validate).

Usage: python -m mapforge.refgraph [--map NAME ...]   -> build/topologies/refmap/<map>.yaml/.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from mapforge.topology import _level, _size, stats, to_yaml_dict

CELL = 32  # floor patch size (units)
RATIO = 0.6  # saddle / lower peak above this: one room
SLACK = 16  # ... or at most this many units lower
MIN_CELLS = 24  # rooms smaller than this many patches are merged into a neighbour


def _patches(feet: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Patch id per walk node: connected pieces of the walk graph inside each CELL column."""
    ij = np.floor(feet[:, :2] / CELL).astype(np.int64)
    col = (ij[:, 0] + 4096) * 8192 + (ij[:, 1] + 4096)
    inner = edges[col[edges[:, 0]] == col[edges[:, 1]]]
    lab = np.arange(len(feet))
    while True:  # min-label propagation; converges in about a patch's diameter in nodes
        m = np.minimum(lab[inner[:, 0]], lab[inner[:, 1]])
        new = lab.copy()
        np.minimum.at(new, inner[:, 0], m)
        np.minimum.at(new, inner[:, 1], m)
        if np.array_equal(new, lab):
            break
        lab = new
    return np.unique(lab, return_inverse=True)[1]


def _clearance(feet: np.ndarray, edges: np.ndarray, cell: float) -> np.ndarray:
    """Units from each walk node to the nearest node that lacks a two-way neighbour on a side."""
    n = len(feet)
    key = edges[:, 0] * n + edges[:, 1]
    me = edges[np.isin(key, edges[:, 1] * n + edges[:, 0])]
    step = np.round((feet[me[:, 1], :2] - feet[me[:, 0], :2]) / cell).astype(np.int64)
    side = {(1, 0): 1, (-1, 0): 2, (0, 1): 4, (0, -1): 8}
    bits = np.zeros(len(me), dtype=np.int64)
    for (dx, dy), b in side.items():
        bits[(step[:, 0] == dx) & (step[:, 1] == dy)] = b
    mask = np.zeros(n, dtype=np.int64)
    np.bitwise_or.at(mask, me[:, 0], bits)
    order = np.argsort(me[:, 0], kind="stable")
    dst, starts = me[order, 1], np.searchsorted(me[order, 0], np.arange(n + 1))
    d = np.full(n, -1, dtype=np.int64)
    front = np.flatnonzero(mask != 15)
    d[front] = 0
    level = 0
    while len(front):  # breadth-first, one ring of walk cells per round
        level += 1
        cnt = starts[front + 1] - starts[front]
        idx = np.repeat(starts[front], cnt) + (
            np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        )
        nxt = np.unique(dst[idx])
        front = nxt[d[nxt] < 0]
        d[front] = level
    d[d < 0] = 0
    return d * int(cell)


def _watershed(nb: list[set[int]], d: np.ndarray) -> np.ndarray:
    parent: list[int] = []
    peak: list[int] = []

    def find(r: int) -> int:
        while parent[r] != r:
            parent[r] = parent[parent[r]]
            r = parent[r]
        return r

    label = np.full(len(d), -1)
    for i in sorted(range(len(d)), key=lambda i: (-d[i], i)):
        rs = sorted({find(label[j]) for j in nb[i] if label[j] >= 0}, key=lambda r: -peak[r])
        if not rs:
            parent.append(len(parent))
            peak.append(int(d[i]))
            label[i] = parent[-1]
            continue
        label[i] = rs[0]
        for r in rs[1:]:  # peak[r] <= peak[rs[0]]: r is the lower room
            if d[i] >= RATIO * peak[r] or peak[r] - d[i] <= SLACK:
                parent[r] = rs[0]
    return np.array([find(r) for r in label])


def _merge_small(region: np.ndarray, nb: list[set[int]]) -> np.ndarray:
    region = region.copy()
    islands: set[int] = set()  # small rooms touching nothing (unreachable from the rest): kept
    while True:
        size = Counter(region.tolist())
        small = [r for r, s in size.items() if s < MIN_CELLS and r not in islands]
        if not small:
            return region
        r = min(small, key=lambda r: (size[r], r))
        touch = Counter(
            int(region[j]) for i in np.flatnonzero(region == r) for j in nb[i] if region[j] != r
        )
        if touch:
            region[region == r] = touch.most_common(1)[0][0]
        else:
            islands.add(r)


def _brush_boxes(bsp: Any, classname: str) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for ent in bsp.entities:
        model = ent.get("model", "")
        if ent.get("classname") == classname and model.startswith("*"):
            m = bsp.models[int(model[1:])]
            shift = np.array([float(v) for v in ent.get("origin", "0 0 0").split()])
            out.append((m["mins"].astype(np.float64) + shift, m["maxs"].astype(np.float64) + shift))
    return out


def _inside(pts: np.ndarray, boxes: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    hit = np.zeros(len(pts), dtype=bool)
    for lo, hi in boxes:
        hit |= np.all((pts >= lo) & (pts <= hi), axis=1)
    return hit


def _split_shared(
    region: np.ndarray, nb: list[set[int]], anchors: dict[str, np.ndarray]
) -> np.ndarray:
    """A room holding two anchors (a spawn and a site, two sites) is split between them: each
    patch goes to the anchor it is fewest steps from inside the room."""
    region = region.copy()
    free = int(region.max()) + 1
    for r in sorted(set(region.tolist())):
        inside = {k: c[region[c] == r] for k, c in anchors.items()}
        inside = {k: c for k, c in inside.items() if len(c)}
        if len(inside) < 2:
            continue
        owner = {int(i): k for k, c in inside.items() for i in c}
        queue = deque(owner)
        while queue:
            i = queue.popleft()
            for j in nb[i]:
                if region[j] == r and j not in owner:
                    owner[j] = owner[i]
                    queue.append(j)
        for k in list(inside)[1:]:
            region[[i for i, o in owner.items() if o == k]] = free
            free += 1
    return region


def _runs(cells: np.ndarray) -> list[list[list[int]]]:
    """Row runs of patch columns (i, j) as rectangles: the room's shape on the page."""
    out = []
    for j in sorted(set(cells[:, 1].tolist())):
        xs = sorted(cells[cells[:, 1] == j, 0].tolist())
        start = prev = xs[0]
        for x in xs[1:] + [None]:
            if x is not None and x == prev + 1:
                prev = x
                continue
            x0, x1, y0, y1 = start * CELL, (prev + 1) * CELL, j * CELL, (j + 1) * CELL
            out.append([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
            if x is not None:
                start = prev = x
    return out


def extract_bsp(
    bsp: Any, wcfg: dict[str, Any], name: str, letters_override: list[str] | None = None
) -> dict[str, Any]:
    from mapforge.validate.checks import spawn_origins
    from mapforge.validate.walk import CROUCH, bomb_sites, build_walk_graph, site_labels

    origins, teams = spawn_origins(bsp.entities)
    g = build_walk_graph(
        bsp, origins, cell=float(wcfg["cell"]), z_step=float(wcfg["z_step"]),
        max_step=float(wcfg["max_step"]), max_drop=float(wcfg["max_drop"]),
        jump_height=float(wcfg.get("jump_height", 54)), crouch=bool(wcfg.get("crouch", True)),
    )  # fmt: skip
    # death pits and out-of-map floors (trigger_hurt) are no rooms: drop their walk nodes
    keep = ~_inside(g.feet + [0, 0, 36], _brush_boxes(bsp, "trigger_hurt"))
    new = np.cumsum(keep) - 1
    feet, stance = g.feet[keep], g.stance[keep]
    edges = new[g.edges[keep[g.edges].all(axis=1)]]
    seeds = [int(new[s]) if s is not None and keep[s] else None for s in g.seeds]
    ladders = _brush_boxes(bsp, "func_ladder")
    pid = _patches(feet, edges)
    n = int(pid.max()) + 1
    cnt = np.bincount(pid, minlength=n)
    xy = np.floor(feet[:, :2] / CELL).astype(np.int64)
    cell_ij = np.zeros((n, 2), dtype=np.int64)
    cell_ij[pid] = xy
    cz = np.bincount(pid, weights=feet[:, 2], minlength=n) / cnt
    crouch = np.bincount(pid, weights=(stance == CROUCH), minlength=n) / cnt

    ce = pid[edges]
    ce = np.unique(ce[ce[:, 0] != ce[:, 1]], axis=0)
    directed = {(int(a), int(b)) for a, b in ce}
    nb: list[set[int]] = [set() for _ in range(n)]
    for a, b in directed:
        if (b, a) in directed:
            nb[a].add(b)
    # clearance (units): from each walk node to the floor's edge (a node missing a side), on
    # the fine walk grid so a 64-wide door and a 128-wide corridor differ; a patch takes its max
    fine_d = _clearance(feet, edges, float(wcfg["cell"]))
    d = np.zeros(n, dtype=np.int64)
    np.maximum.at(d, pid, fine_d)
    region = _merge_small(_watershed(nb, d), nb)

    # anchors: the patches of each team's spawns and each site's bomb target
    labels = site_labels(bsp)
    if letters_override:  # unnamed bomb targets: the letters per site in entity order (config)
        labels = [*letters_override, *labels[len(letters_override) :]]
    letters = iter("ABCDEF")
    anchors: dict[str, np.ndarray] = {}
    for team in ("T", "CT"):
        own = [s for s, t in zip(seeds, teams, strict=True) if t == team and s is not None]
        if own:
            anchors[team] = np.unique(pid[own])
    for lab, boxes in zip(labels, bomb_sites(bsp), strict=True):
        # a standing player's box (32x32x72 from the feet) overlapping the target's box
        near = [(lo - [16, 16, 72], hi + [16, 16, 0]) for lo, hi in boxes]
        hit = np.flatnonzero(_inside(feet, near))
        if len(hit):
            anchors.setdefault(lab if lab.isalpha() else next(letters), np.unique(pid[hit]))
    region = _split_shared(region, nb, anchors)

    def room_of(cells: np.ndarray) -> int:
        return Counter(region[cells].tolist()).most_common(1)[0][0]

    spawn_room = {t: room_of(c) for t, c in anchors.items() if t in ("T", "CT")}
    site_room: dict[int, str] = {}
    for k, c in anchors.items():
        if k not in ("T", "CT"):
            site_room.setdefault(room_of(c), k)
    ids = sorted(set(region.tolist()))
    members = {r: np.flatnonzero(region == r) for r in ids}
    zref = float(np.median(feet[:, 2]))  # the map's typical floor is level 0

    def peak_xy(r: int) -> list[int]:
        i = members[r][np.argmax(d[members[r]])]
        return [int((cell_ij[i, 0] + 0.5) * CELL), int((cell_ij[i, 1] + 0.5) * CELL)]

    # readable ids: sites, spawns, then rooms numbered from the T spawn outwards
    name_of: dict[int, str] = {}
    for r, k in site_room.items():
        name_of[r] = f"{k.lower()}_site"
    for team, r in spawn_room.items():
        name_of.setdefault(r, f"{team.lower()}_spawn")
    t_at = peak_xy(spawn_room["T"]) if "T" in spawn_room else [0, 0]
    rest = sorted((r for r in ids if r not in name_of), key=lambda r: math.dist(peak_xy(r), t_at))
    for k, r in enumerate(rest, start=1):
        name_of[r] = f"r{k:02d}"

    node_site_zone = {r: k.lower() for r, k in site_room.items()}
    nodes = []
    for r in ids:
        m = members[r]
        width = 2 * int(d[m].max()) + 32
        area = float(cnt[m].sum()) * float(wcfg["cell"]) ** 2
        role = (
            "site" if r in site_room
            else "t_spawn" if spawn_room.get("T") == r
            else "ct_spawn" if spawn_room.get("CT") == r
            else "corridor" if area > 3 * width * width else "room"
        )  # fmt: skip
        node = {
            "id": name_of[r],
            "role": role,
            "level": _level(float(np.median(cz[m])) - zref),
            "size": _size(area),
            "_c": peak_xy(r),
            "_zone": {"site": node_site_zone.get(r), "t_spawn": "t", "ct_spawn": "ct"}.get(role),
            "_members": [
                {"name": name_of[r], "shape": s, "outdoor": False} for s in _runs(cell_ij[m])
            ],
        }
        if r in site_room:
            node["site"] = site_room[r]
        nodes.append(node)
    centre = {name_of[r]: n["_c"] for r, n in zip(ids, nodes, strict=True)}
    zmed = {r: float(np.median(cz[members[r]])) for r in ids}

    # edges: where two rooms touch
    contact: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for a, b in directed:
        ra, rb = int(region[a]), int(region[b])
        if ra != rb:
            contact.setdefault((min(ra, rb), max(ra, rb)), []).append((a, b))
    edges = []
    for (ra, rb), pairs in sorted(contact.items()):
        fwd = any(int(region[a]) == ra for a, _ in pairs)
        two_way = [(a, b) for a, b in pairs if (b, a) in directed]
        use = two_way or pairs  # the opening: where one can go both ways (else the drop)
        cells = np.array(sorted({c for q in use for c in q}))
        xyz = np.column_stack([(cell_ij[cells] + 0.5) * CELL, cz[cells]])
        # the contact patch nearest their mean: on the real boundary, not across a wall
        mid = np.argmin(((xyz[:, :2] - xyz[:, :2].mean(axis=0)) ** 2).sum(axis=1))
        p = [int(v) for v in xyz[mid, :2]]
        if not two_way:
            kind = "drop"
        elif _inside(xyz + [0, 0, 36], ladders).any():
            kind = "ladder"
        elif np.mean(crouch[cells]) > 0.5:
            kind = "vent"
        elif abs(zmed[ra] - zmed[rb]) > 48 or max(abs(cz[a] - cz[b]) for a, b in use) > 24:
            kind = "stairs"
        else:
            kind = "door"
        w = 2 * max(min(int(d[a]), int(d[b])) for a, b in use) + 32  # player width + clearance
        a_id, b_id = name_of[ra], name_of[rb]
        if not fwd:  # a drop goes from a to b
            a_id, b_id = b_id, a_id
        via = math.dist(centre[a_id], p) + math.dist(p, centre[b_id])
        edges.append({
            "id": f"{a_id}-{b_id}",
            "a": a_id, "b": b_id, "kind": kind,
            "width": "narrow" if w < 128 else "normal" if w <= 192 else "wide",
            "_w": int(w), "_p": p,
            "length": int(round(via / 16)) * 16,
        })  # fmt: skip
    spawns = {}
    for team, r in spawn_room.items():
        own = [s for s, t in zip(seeds, teams, strict=True) if t == team and s is not None]
        at = np.median(feet[own, :2], axis=0)
        spawns[team] = {"node": name_of[r], "at": [int(at[0]), int(at[1])]}
    return {
        "version": 1,
        "source": "bsp",
        "name": name,
        "nodes": nodes,
        "edges": edges,
        "_spawns": spawns,
        "_concept": None,
        "_sites_named": all(lab.isalpha() for lab in labels),
    }


def tier_of(cfg: Any, name: str) -> str:
    tiers = cfg.data.get("reference_maps", {}).get("tiers", {}) or {}  # override: {tier: [names]}
    for t, names in (tiers.get("override") or {}).items():
        if name in (names or []):
            return t
    return "A" if name in (tiers.get("A") or []) else "B"


def reference_de_maps(cfg: Any) -> dict[str, Path]:
    """de_ reference maps: not our own maps (maps/<name>/) and not the test variants."""
    from mapforge.refmaps import list_reference_maps

    own = cfg.path("maps_dir")
    return {
        k: p for k, p in list_reference_maps(cfg).items()
        if k.startswith("de_") and not (own / k).is_dir() and "variants" not in p.parts
    }  # fmt: skip


def out_dir(cfg: Any) -> Path:
    return cfg.path("build_dir") / "topologies" / "refmap"


def main(argv: list[str] | None = None) -> int:
    from mapforge.bsp.reader import read_bsp
    from mapforge.config import load_config

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", action="append", help="only these maps (default: all de_ refmaps)")
    args = ap.parse_args(argv)
    cfg = load_config()
    maps = reference_de_maps(cfg)
    if args.map:
        missing = [m for m in args.map if m not in maps]
        if missing:
            print(f"refgraphs: not a de_ reference map: {', '.join(missing)}", file=sys.stderr)
            return 1
        maps = {m: maps[m] for m in args.map}
    out = out_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    wcfg = cfg.data["validate"]["walk"]
    refcfg = cfg.data.get("reference_maps", {})
    failed = 0
    for name, path in sorted(maps.items()):
        try:
            letters = (refcfg.get("site_letters") or {}).get(name)
            topo = extract_bsp(read_bsp(path), wcfg, name, letters)
        except Exception as exc:  # one odd map must not stop the rest
            print(f"  {name}: FAILED ({exc})")
            failed += 1
            continue
        topo["tier"] = tier_of(cfg, name)
        doc = {"tier": topo["tier"], **to_yaml_dict(topo)}
        (out / f"{name}.yaml").write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
        )
        (out / f"{name}.json").write_text(json.dumps(topo, separators=(",", ":")), encoding="utf-8")
        s = stats(topo)
        note = "" if topo["_sites_named"] else " (unnamed sites: A/B in entity order)"
        if len(s["site_entrances"]) < 2:
            note += " WARNING: fewer than 2 sites found"
        print(f"  {name} [{topo['tier']}]: {len(topo['nodes'])} rooms, {len(topo['edges'])} "
              f"edges, site entrances {s['site_entrances']}{note}")  # fmt: skip
    print(f"refgraphs: {len(maps) - failed}/{len(maps)} -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
