"""Topology of a map: rooms and connections (docs/MAPMAKER.md -> "Graf-laget").

`extract(layout)` turns a layout.yaml (after macro expansion) into the engine-neutral graph that
the mapmaker searches, learns and reasons on:

- nodes: one per room; areas that touch with no wall between them are one room (an L-room, a
  nook off a corridor), the same rule as `mapforge.validate.design.layout_graph`. A bridge deck
  is its own node (a door level with the deck leads onto the bridge, not into the room below).
- edges: doors, vents, windows (sightline only, not walkable) and hatches. A door between rooms on
  different floors is a `ramp` or `stairs` when one of the rooms holds one.

Extra view data (door points, room shapes, the T/CT spawn points) rides along under keys that
start with an underscore; `to_yaml_dict` drops them. Door points and lengths are estimates
(centre -> door -> centre); the BSP walk graph gives the real numbers.

Usage: python -m mapforge.topology --map <map>   -> build/<map>/topology.yaml
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import Any

import yaml

SPECIAL = ("site", "t_spawn", "ct_spawn")
WALL_SLACK = 48  # two rooms one wall apart: gap <= wall + slack


def _poly_area(pts: list[list[float]]) -> float:
    pairs = zip(pts, pts[1:] + pts[:1], strict=True)
    return abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in pairs)) / 2


def _shape(a: dict[str, Any]) -> list[list[float]]:
    if a.get("poly"):
        return [list(p) for p in a["poly"]]
    x0, y0, x1, y1 = a["rect"]
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _centre(a: dict[str, Any]) -> list[float]:
    pts = _shape(a)
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


def _size(area: float) -> str:
    return "S" if area < 300_000 else "M" if area < 900_000 else "L" if area < 2_000_000 else "XL"


def _level(floor: float) -> int:
    return max(-2, min(2, round(floor / 192)))


def _door_point(a: dict[str, Any], b: dict[str, Any], offset: float = 0) -> list[float]:
    """Where a door between two rooms sits (estimate from their bounding boxes)."""
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["rect"], b["rect"]
    oy0, oy1 = max(ay0, by0), min(ay1, by1)
    ox0, ox1 = max(ax0, bx0), min(ax1, bx1)
    gx = bx0 - ax1 if bx0 >= ax1 else ax0 - bx1 if ax0 >= bx1 else None
    gy = by0 - ay1 if by0 >= ay1 else ay0 - by1 if ay0 >= by1 else None
    if gx is not None and gx <= WALL_SLACK and oy1 > oy0:  # side by side along x
        x = (ax1 + bx0) / 2 if bx0 >= ax1 else (bx1 + ax0) / 2
        return [x, (oy0 + oy1) / 2 + offset]
    if gy is not None and gy <= WALL_SLACK and ox1 > ox0:  # one above the other along y
        y = (ay1 + by0) / 2 if by0 >= ay1 else (by1 + ay0) / 2
        return [(ox0 + ox1) / 2 + offset, y]
    if ox1 > ox0 and oy1 > oy0:  # polygon boxes overlap: the middle of the overlap
        return [(ox0 + ox1) / 2, (oy0 + oy1) / 2]
    cx = (max(ax0, bx0) + min(ax1, bx1)) / 2  # nearest corners
    cy = (max(ay0, by0) + min(ay1, by1)) / 2
    return [cx, cy]


def extract(layout: dict[str, Any]) -> dict[str, Any]:
    """The topology of a layout (see the module docstring)."""
    from mapforge.generator.spec import expand_macros

    lay = expand_macros(layout, int(layout.get("grid", 16)))
    raw = {a["name"]: a for a in lay.get("areas", [])}
    group = {n: n for n in raw}

    def find(n: str) -> str:
        while group[n] != n:
            n = group[n]
        return n

    def weight(n: str) -> tuple[int, float]:
        return (raw[n].get("role") in SPECIAL, _poly_area(_shape(raw[n])))

    names = list(raw)
    for i, n in enumerate(names):
        a = raw[n]
        for m in names[i + 1 :]:
            b = raw[m]
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["rect"], b["rect"]
            fa, fb = a.get("floor", 0), b.get("floor", 0)
            z_overlap = min(fa + a.get("height", 192), fb + b.get("height", 192)) > max(fa, fb)
            touch_x = (ax1 == bx0 or bx1 == ax0) and min(ay1, by1) > max(ay0, by0)
            touch_y = (ay1 == by0 or by1 == ay0) and min(ax1, bx1) > max(ax0, bx0)
            if z_overlap and (touch_x or touch_y):
                ra, rb = find(n), find(m)
                if ra != rb:  # keep the site/spawn, else the bigger room, as the node's name
                    keep, drop = (ra, rb) if weight(ra) >= weight(rb) else (rb, ra)
                    group[drop] = keep

    ramps = {r["area"] for r in lay.get("ramps", []) or []}
    stairs = {s["area"] for s in lay.get("stairs", []) or []}
    sites = {
        k: (v["area"] if isinstance(v, dict) else v) for k, v in (lay.get("sites") or {}).items()
    }
    site_of = {find(a): k for k, a in sites.items()}

    nodes: dict[str, dict[str, Any]] = {}
    for n in names:
        if find(n) != n:
            continue
        a = raw[n]
        members = [m for m in names if find(m) == n]
        node = {
            "id": n,
            "role": a.get("role", "room"),
            "level": _level(a.get("floor", 0)),
            "size": _size(sum(_poly_area(_shape(raw[m])) for m in members)),
            "_c": [round(v) for v in _centre(a)],
            "_zone": a.get("zone"),
            "_members": [
                {"name": m, "shape": _shape(raw[m]), "outdoor": bool(raw[m].get("outdoor"))}
                for m in members
            ],
        }
        if n in site_of:
            node["site"] = site_of[n]
        nodes[n] = node

    decks: dict[str, list[tuple[str, float]]] = {}
    for br in lay.get("bridges", []) or []:
        area = raw[br["area"]]
        node_id = f"{br['area']}/{br['name']}"
        cx, cy = _centre(area)
        c = [br["pos"], cy] if br.get("axis") == "y" else [cx, br["pos"]]
        top = area.get("floor", 0) + br["z"]
        nodes[node_id] = {
            "id": node_id,
            "role": "corridor",
            "level": _level(top),
            "size": "S",
            "_c": [round(v) for v in c],
            "_zone": area.get("zone"),
            "_members": [],
            "_deck": True,
        }
        decks.setdefault(br["area"], []).append((node_id, top))
        # view only: a deck across the middle of its room would sit on the room's node; move the
        # room's node off the deck (across it and a bit along it) so neither the node nor the
        # room's own through-route hides the bridge. Lengths are estimates anyway.
        host = nodes[find(br["area"])]
        if math.dist(host["_c"], nodes[node_id]["_c"]) < 320:
            x0, y0, x1, y1 = raw[host["id"]]["rect"]
            dx, dy = (-260, 340) if br.get("axis") == "x" else (340, -260)
            deck_x, deck_y = nodes[node_id]["_c"]
            host["_c"] = [
                round(min(x1 - 96, max(x0 + 96, deck_x + dx))),
                round(min(y1 - 96, max(y0 + 96, deck_y + dy))),
            ]

    def end(door: dict[str, Any], i: int) -> str:
        name = door["between"][i]
        other = raw.get(door["between"][1 - i], {})
        sill = max(raw.get(name, {}).get("floor", 0), other.get("floor", 0)) + door.get("sill", 0)
        for node_id, top in decks.get(name, []):
            if abs(sill - top) <= 18:
                return node_id
        return find(name)

    chokes = {c["door"]: c["name"] for c in lay.get("chokes", []) or [] if c.get("door")}
    edges = []
    for d in lay.get("doors", []) or []:
        a_name, b_name = d["between"]
        a, b = end(d, 0), end(d, 1)
        kind = d.get("kind", "door")
        fa, fb = raw[a_name].get("floor", 0), raw[b_name].get("floor", 0)
        if kind == "door" and fa != fb:
            if a_name in stairs or b_name in stairs:
                kind = "stairs"
            elif a_name in ramps or b_name in ramps:
                kind = "ramp"
        p = _door_point(raw[a_name], raw[b_name], d.get("offset", 0))
        ca, cb = nodes[a]["_c"], nodes[b]["_c"]
        w = int(d.get("width", 128))
        edge = {
            "id": d["name"],
            "a": a,
            "b": b,
            "kind": kind,
            "width": "narrow" if w < 128 else "normal" if w <= 192 else "wide",
            "_w": w,
            "_p": [round(v) for v in p],
        }
        if kind != "window":
            edge["length"] = int(round((math.dist(ca, p) + math.dist(p, cb)) / 16) * 16)
        if d["name"] in chokes:
            edge["choke"] = chokes[d["name"]]
        if d.get("gate"):
            edge["_gate"] = d["gate"]
        edges.append(edge)
    for h in lay.get("hatches", []) or []:
        x0, y0, x1, y1 = h["rect"]
        rise = abs(raw[h["upper"]].get("floor", 0) - raw[h["lower"]].get("floor", 0))
        edge = {
            "id": h["name"], "a": find(h["lower"]), "b": find(h["upper"]), "kind": "hatch",
            "width": "narrow", "_w": x1 - x0, "_p": [(x0 + x1) // 2, (y0 + y1) // 2],
            "length": int(rise + 64),
        }  # fmt: skip
        if h.get("lift"):  # a lift: humans only (YaPB's analyser makes no lift nodes)
            edge["lift"] = h["lift"]
        edges.append(edge)

    spawns = {}
    for team in ("T", "CT"):
        sp = (lay.get("spawns") or {}).get(team)
        if sp and find(sp["area"]) in nodes:
            c = _centre(raw[sp["area"]])
            off = sp.get("offset", [0, 0])
            at = [round(c[0] + off[0]), round(c[1] + off[1])]
            spawns[team] = {"node": find(sp["area"]), "at": at}
    return {
        "version": 1,
        "source": "layout",
        "name": lay.get("name"),
        "nodes": list(nodes.values()),
        "edges": edges,
        "_spawns": spawns,
        "_concept": lay.get("concept"),
    }


def to_yaml_dict(topo: dict[str, Any]) -> dict[str, Any]:
    """The topology.yaml content: view-only keys (leading underscore) dropped, `pos` kept."""

    def clean(d: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in d.items() if not k.startswith("_")}

    return {
        "version": topo["version"],
        "source": topo["source"],
        "nodes": [clean(n) for n in topo["nodes"]],
        "edges": [clean(e) for e in topo["edges"]],
        "pos": {n["id"]: n["_c"] for n in topo["nodes"]},
    }


def stats(topo: dict[str, Any]) -> dict[str, Any]:
    """The same topology numbers as layout_graph(): site entrances, CT entrance, junctions."""
    walk = [(e["a"], e["b"]) for e in topo["edges"] if e["kind"] != "window"]
    ids = [n["id"] for n in topo["nodes"]]
    role = {n["id"]: n["role"] for n in topo["nodes"]}
    nb: dict[str, set[str]] = {n: set() for n in ids}
    degree = {n: 0 for n in ids}
    for a, b in walk:
        degree[a] += 1
        degree[b] += 1
        nb[a].add(b)
        nb[b].add(a)
    sites = {n["site"]: n["id"] for n in topo["nodes"] if n.get("site")}
    entrances = {  # an opening into a dead end (only the site as neighbour) is no way in
        k: sum(1 for x, y in walk if a in (x, y) and len(nb[y if x == a else x]) > 1)
        for k, a in sites.items()
    }
    ct = {n for n in ids if role[n] == "ct_spawn"}
    ct_side = ct | {m for c in ct for m in nb[c]}
    junction = {n: d for n, d in degree.items() if role[n] not in SPECIAL}
    return {
        "site_entrances": entrances,
        "site_ct_entrance": {k: bool(nb[a] & ct_side) for k, a in sites.items()},
        "four_way": sorted(n for n, d in junction.items() if d >= 4),
        "three_way": sum(1 for d in junction.values() if d == 3),
    }


def main(argv: list[str] | None = None) -> int:
    from mapforge.config import load_config

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", required=True)
    args = ap.parse_args(argv)
    cfg = load_config()
    src = cfg.path("maps_dir") / args.map / "layout.yaml"
    if not src.is_file():
        print(f"topology: {src} not found", file=sys.stderr)
        return 1
    topo = extract(yaml.safe_load(src.read_text(encoding="utf-8")))
    out = cfg.path("build_dir") / args.map / "topology.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(to_yaml_dict(topo), sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    s = stats(topo)
    print(f"topology: {out} ({len(topo['nodes'])} nodes, {len(topo['edges'])} edges, "
          f"site entrances {s['site_entrances']})")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
