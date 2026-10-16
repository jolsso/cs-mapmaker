"""An approved editor graph -> layout.yaml (spec: docs/superpowers/specs/, graph editor §4).

Deterministic: rooms at the graph's positions (square, by size), an angled corridor along every
connection (wall to wall, a knee where two rooms sit diagonally), pushed apart where rooms
overlap, corridors lengthened with a side step where they are much shorter than the editor's
estimate. Claude then adds the details from the descriptions (cover, landmarks, height).

Usage: python -m mapforge.fromgraph --map <map> [--force]
  -> maps/<map>/layout.yaml (refused if it exists, unless --force)
  -> build/<map>/fromgraph_report.json (what was moved/changed and why, edge lengths)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any

import yaml

from mapforge import graph as gr
from mapforge.config import load_config

GRID, WALL = 16, 16
MIN_GAP = 96  # between two rooms: room for a corridor (and never one shared wall by accident)
ROLE = {"T": "t_spawn", "CT": "ct_spawn", "A": "site", "B": "site", "room": "room"}
ZONE = {"T": "t", "CT": "ct", "A": "a", "B": "b", "room": "mid"}
ZONES = {  # dev-WAD tints per zone (the art pass replaces them)
    "t": {"floor": "DEV_FLOOR_SAND", "wall": "DEV_WALL_SAND", "ceiling": "DEV_CEIL_SAND"},
    "ct": {"floor": "DEV_FLOOR_BLUE", "wall": "DEV_WALL_BLUE", "ceiling": "DEV_CEIL_BLUE"},
    "mid": {"floor": "DEV_FLOOR_GREY", "wall": "DEV_WALL_GREY", "ceiling": "DEV_CEIL_GREY"},
    "a": {"floor": "DEV_FLOOR_RED", "wall": "DEV_WALL_RED", "ceiling": "DEV_CEIL_RED"},
    "b": {"floor": "DEV_FLOOR_GREEN", "wall": "DEV_WALL_GREEN", "ceiling": "DEV_CEIL_GREEN"},
}
DETOUR, SPEED = 1.3, 250
CHOKE_DOOR = 128


def _snap(v: float) -> int:
    return int(round(v / GRID)) * GRID


def _rect(n: dict[str, Any]) -> list[int]:
    side = gr.SIZES[n["size"]]
    if n["role"] != "room":
        side = max(side, gr.SIZES["M"])  # 16 spawns / a bomb site with cover need the room
    h = side // 2
    x, y = (_snap(v) for v in n["pos"])
    return [x - h, y - h, x + h, y + h]


def _overlap(a: list[int], b: list[int], gap: int) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def _separate(rects: dict[str, list[int]]) -> list[dict[str, Any]]:
    """Push rooms apart until MIN_GAP separates them (≤ 40 rounds). fromgraph does not stack
    rooms: a level is a floor height, so rooms on different levels need their own floor plan."""
    moved: dict[str, list[int]] = {}
    ids = list(rects)
    for _ in range(40):
        clash = False
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if not _overlap(rects[a], rects[b], MIN_GAP):  # every level: rooms are not stacked
                    continue
                clash = True
                ra, rb = rects[a], rects[b]
                ax, ay = (ra[0] + ra[2]) / 2, (ra[1] + ra[3]) / 2
                bx, by = (rb[0] + rb[2]) / 2, (rb[1] + rb[3]) / 2
                dx, dy = bx - ax, by - ay
                if abs(dx) >= abs(dy):  # push along the axis that needs least
                    need = (ra[2] - ra[0] + rb[2] - rb[0]) / 2 + MIN_GAP - abs(dx)
                    sx, sy = int(math.copysign(_snap(need / 2 + 8), dx or 1)), 0
                else:
                    need = (ra[3] - ra[1] + rb[3] - rb[1]) / 2 + MIN_GAP - abs(dy)
                    sx, sy = 0, int(math.copysign(_snap(need / 2 + 8), dy or 1))
                for k, s in ((a, -1), (b, 1)):
                    r = rects[k]
                    rects[k] = [r[0] + s * sx, r[1] + s * sy, r[2] + s * sx, r[3] + s * sy]
                    m = moved.setdefault(k, [0, 0])
                    m[0] += s * sx
                    m[1] += s * sy
        if not clash:
            break
    return [{"node": k, "delta": [int(v[0]), int(v[1])], "why": "overlapped another room"}
            for k, v in moved.items() if v != [0, 0]]  # fmt: skip


def _centre(r: list[int]) -> tuple[float, float]:
    return (r[0] + r[2]) / 2, (r[1] + r[3]) / 2


def _path_len(pts: list[list[int]]) -> float:
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:], strict=False))


SIDES = ("E", "W", "N", "S")


def _range_slots(lo: int, hi: int, width: int) -> list[int]:
    """Door positions on a stretch of wall [lo, hi], from its middle outwards (64 apart)."""
    lo, hi = lo + width // 2 + 32, hi - width // 2 - 32
    if hi < lo:
        return []
    mid = _snap((lo + hi) / 2)
    out = [mid]
    for k in range(1, 64):
        out += [t for t in (mid - 64 * k, mid + 64 * k) if lo <= t <= hi]
        if mid - 64 * k < lo and mid + 64 * k > hi:
            break
    return out


def _slots(r: list[int], side: str, width: int) -> list[int]:
    return _range_slots(*((r[1], r[3]) if side in ("E", "W") else (r[0], r[2])), width)


def _door_point(r: list[int], side: str, t: int) -> list[int]:
    return {"E": [r[2] + WALL, t], "W": [r[0] - WALL, t], "N": [t, r[3] + WALL],
            "S": [t, r[1] - WALL]}[side]  # fmt: skip


def _seg_box(p: list[int], q: list[int], width: int) -> list[int]:
    hw = width // 2 + 32  # knee rooms are a little wider than the corridor
    return [min(p[0], q[0]) - hw, min(p[1], q[1]) - hw, max(p[0], q[0]) + hw, max(p[1], q[1]) + hw]


def _candidates(a: list[int], b: list[int], width: int):
    """(side_a, t_a, side_b, t_b, points) routes from a to b: straight across facing walls, then
    the two L shapes (along x then y, along y then x), door positions from the middle out."""
    (acx, acy), (bcx, bcy) = _centre(a), _centre(b)
    dx, dy = bcx - acx, bcy - acy
    sx = ("E", "W") if dx > 0 else ("W", "E")
    sy = ("N", "S") if dy > 0 else ("S", "N")
    straight = []
    for (sa, sb), lo, hi in ((sx, max(a[1], b[1]), min(a[3], b[3])),
                             (sy, max(a[0], b[0]), min(a[2], b[2]))):  # fmt: skip
        for t in _range_slots(lo, hi, width):  # the stretch both walls share
            straight.append((sa, t, sb, t, [_door_point(a, sa, t), _door_point(b, sb, t)]))
    ls = []
    for first, second in ((sx, sy), (sy, sx)):
        sa, sb = first[0], second[1]  # leave a along the first axis, enter b along the second
        for ta in _slots(a, sa, width)[:5]:
            for tb in _slots(b, sb, width)[:5]:
                pa, pb = _door_point(a, sa, ta), _door_point(b, sb, tb)
                knee = [pb[0], pa[1]] if sa in ("E", "W") else [pa[0], pb[1]]
                ok_a = (
                    (knee[0] - pa[0]) * (1 if sa == "E" else -1) >= width
                    if sa in ("E", "W")
                    else (knee[1] - pa[1]) * (1 if sa == "N" else -1) >= width
                )
                ok_b = (
                    (pb[1] - knee[1]) * (1 if sb == "S" else -1) >= width
                    if sb in ("N", "S")
                    else (pb[0] - knee[0]) * (1 if sb == "W" else -1) >= width
                )
                if ok_a and ok_b:
                    ls.append((sa, ta, sb, tb, [pa, knee, pb]))
    yield from straight
    yield from ls
    # around: out of both rooms on the same side, along beyond both (and what lies between),
    # back in - for rooms that face each other across something in the way
    for side in ("N", "S", "E", "W"):
        for k in range(2, 12):
            off = k * 128
            ta, tb = _slots(a, side, width)[:1], _slots(b, side, width)[:1]
            if not ta or not tb:
                continue
            pa, pb = _door_point(a, side, ta[0]), _door_point(b, side, tb[0])
            if side in ("N", "S"):
                y = max(a[3], b[3]) + off if side == "N" else min(a[1], b[1]) - off
                pts = [pa, [pa[0], y], [pb[0], y], pb]
            else:
                x = max(a[2], b[2]) + off if side == "E" else min(a[0], b[0]) - off
                pts = [pa, [x, pa[1]], [x, pb[1]], pb]
            if abs(pts[1][0] - pts[2][0]) + abs(pts[1][1] - pts[2][1]) >= width + 96:
                yield side, ta[0], side, tb[0], pts


def _free(pts, width, rects, ends, placed) -> bool:
    """No stretch runs through another room (or through its own rooms past the door), and no
    stretch touches a corridor that is already placed."""
    segs = list(zip(pts, pts[1:], strict=False))
    for i, (p, q) in enumerate(segs):
        box = _seg_box(p, q, width)
        for k, r in rects.items():
            own = (k == ends[0] and i == 0) or (k == ends[1] and i == len(segs) - 1)
            if not own and _overlap(box, r, 16):
                return False
        if any(_overlap(box, other, 16) for other in placed):
            return False
    return True


def _route(e, rects, width, used, placed):
    """The first free route for an edge. Without one: a route that crosses another corridor
    (an extra junction) but no room; only then the first candidate at all. -> (route, free)."""
    first = no_room = None
    for sa, ta, sb, tb, pts in _candidates(rects[e["a"]], rects[e["b"]], width):
        route = (sa, ta, sb, tb, pts)
        first = first or route
        taken = any(abs(ta - t) < width + 64 for t in used.get((e["a"], sa), [])) or any(
            abs(tb - t) < width + 64 for t in used.get((e["b"], sb), [])
        )
        if not taken and _free(pts, width, rects, (e["a"], e["b"]), placed):
            return route, True
        if no_room is None and _free(pts, width, rects, (e["a"], e["b"]), []):
            no_room = route
    return no_room or first, False


def _detour(pts, extra, width, rects, ends, placed):
    """A straight corridor made longer by a U-shaped step to one side (axis-aligned knees)."""
    (p, q) = pts
    along_x = p[1] == q[1]
    o = min(_snap(extra / 2), 1024)
    leg = width + 96  # every leg needs room for its knee rooms (generator: corridor_chain)
    if o < 2 * GRID or math.dist(p, q) / 4 < leg:
        return None
    o = max(o, _snap(leg))
    for s in (1, -1):
        if along_x:
            q1, q3 = _snap(p[0] + (q[0] - p[0]) / 4), _snap(p[0] + 3 * (q[0] - p[0]) / 4)
            via = [[q1, p[1]], [q1, p[1] + s * o], [q3, p[1] + s * o], [q3, p[1]]]
        else:
            q1, q3 = _snap(p[1] + (q[1] - p[1]) / 4), _snap(p[1] + 3 * (q[1] - p[1]) / 4)
            via = [[p[0], q1], [p[0] + s * o, q1], [p[0] + s * o, q3], [p[0], q3]]
        trial = [p, *via, q]
        if _free(trial, width, rects, ends, placed):
            return trial
    return None


def build_layout(
    graph: dict[str, Any], intent: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(layout dict, report) from an approved graph."""
    g = gr.validate(graph)
    if g["status"] != "approved":
        raise ValueError("only an approved graph becomes a layout (approve it in the editor)")
    nodes = {n["id"]: n for n in g["nodes"]}
    rects = {k: _rect(n) for k, n in nodes.items()}
    report: dict[str, Any] = {"moved": _separate(rects), "edges": [], "notes": []}

    areas = []
    for k, n in nodes.items():
        area = {"name": k, "rect": rects[k], "height": 320 if n["outdoor"] else 256,
                "role": ROLE[n["role"]], "zone": ZONE[n["role"]]}  # fmt: skip
        if n["level"]:
            area["floor"] = n["level"] * gr.LEVEL_FLOOR
        if n["outdoor"]:
            area["outdoor"] = True
        areas.append(area)

    corridors, chokes = [], []
    used: dict[tuple[str, str], list[int]] = {}
    placed: list[list[int]] = []
    # short connections first: they have the fewest ways to go
    order = sorted(g["edges"], key=lambda e: math.dist(nodes[e["a"]]["pos"], nodes[e["b"]]["pos"]))
    for e in order:
        a, b = nodes[e["a"]], nodes[e["b"]]
        name = f"c_{e['a']}_{e['b']}"
        width = gr.WIDTHS[e["width"]]
        (sa, ta, sb, tb, pts), free = _route(e, rects, width, used, placed)
        if not free:
            report["notes"].append(f"{name}: no free route (it touches another room or corridor)"
                                   ": move a room in the editor")  # fmt: skip
        level_step = abs(a["level"] - b["level"]) * 96 * (2 if e["kind"] == "ladder" else 1)
        target = e["len"] or math.dist(a["pos"], b["pos"]) * DETOUR + level_step
        ca, cb = _centre(rects[e["a"]]), _centre(rects[e["b"]])

        def walk_of(path: list[list[int]], ca=ca, cb=cb) -> float:
            return math.dist(ca, path[0]) + _path_len(path) + math.dist(path[-1], cb)

        walk = walk_of(pts)
        if walk < 0.9 * target and len(pts) == 2:
            longer = _detour(pts, target - walk, width, rects, (e["a"], e["b"]), placed)
            if longer:
                pts, walk = longer, walk_of(longer)
        rise = abs(a["level"] - b["level"]) * gr.LEVEL_FLOOR

        def ramp_len(path: list[list[int]], width=width) -> float:  # knee rooms carry no ramp
            return _path_len(path) - (len(path) - 2) * (width + 96)

        steep = bool(rise) and ramp_len(pts) < 2 * rise  # ramps: rise <= length / 2 (YaPB)
        if steep and len(pts) == 2:
            longer = _detour(
                pts, 2 * rise - _path_len(pts) + 64, width, rects, (e["a"], e["b"]), placed
            )
            if longer:
                pts, walk = longer, walk_of(longer)
                steep = ramp_len(pts) < 2 * rise
        used.setdefault((e["a"], sa), []).append(ta)
        used.setdefault((e["b"], sb), []).append(tb)
        placed += [_seg_box(p, q, width) for p, q in zip(pts, pts[1:], strict=False)]
        if abs(walk - target) > 0.1 * target:
            how = "shorter" if walk < target else "longer"
            report["notes"].append(f"{name} is {abs(walk - target) / target:.0%} {how} than the "
                                   "editor's estimate: move a room to fix it")  # fmt: skip
        c: dict[str, Any] = {"name": name, "from": pts[0], "to": pts[-1], "width": width,
                             "height": 192, "between": [e["a"], e["b"]]}  # fmt: skip
        if len(pts) > 2:
            c["via"] = pts[1:-1]
        if steep:  # no room for a walkable ramp: a ledge, one can only drop down it
            c["rise"] = 0
            report["notes"].append(
                f"{name}: too short for a ramp between the levels; built as a drop from the "
                "upper room (move the rooms apart for a ramp)"
            )
        elif e["kind"] == "drop":
            if b["level"] < a["level"]:  # stays at the source floor: a ledge into the target
                c["rise"] = 0
            else:
                report["notes"].append(
                    f"{name}: a drop needs a lower target room; built as a corridor"
                )
        elif e["kind"] == "ladder" and a["level"] != b["level"]:
            report["notes"].append(f"{name}: ladder built as a ramp")
        if e["kind"] == "choke":
            c["door_width"] = CHOKE_DOOR
            chokes.append({"name": f"{a['name']} - {b['name']}", "door": f"{name}_to",
                           "type": "doorway", "engagement": "mid"})  # fmt: skip
        corridors.append(c)
        report["edges"].append({"a": e["a"], "b": e["b"], "target": round(target),
                                "actual": round(walk), "ok": abs(walk - target) <= 0.1 * target,
                                "seconds": round(walk / SPEED, 1), "free": free})  # fmt: skip

    site = {n["role"]: k for k, n in nodes.items() if n["role"] in ("A", "B")}
    spawn = {n["role"]: k for k, n in nodes.items() if n["role"] in ("T", "CT")}
    lay: dict[str, Any] = {"name": g["map"] or "de_new", "grid": GRID, "wall": WALL}
    if intent and intent.get("concept"):
        lay["concept"] = intent["concept"]
    if intent and intent.get("archetype"):
        lay["archetype"] = intent["archetype"]
    if any(n["outdoor"] for n in nodes.values()):
        lay["sky"] = {"name": "grnplsnt",
                      "sun": {"pitch": -45, "yaw": 135, "color": [255, 244, 225],
                              "brightness": 260, "ambient": 100}}  # fmt: skip
    lay["lights"] = {"spacing": 320, "brightness": 230, "color": [240, 244, 255]}
    lay["zones"] = {z: dict(t) for z, t in ZONES.items()}
    spawns = {t: {"area": spawn[t], "count": 16} for t in ("T", "CT")}
    lay.update(areas=areas, corridors=corridors, doors=[], chokes=chokes,
               sites={"A": site["A"], "B": site["B"]}, spawns=spawns, buyzones=True)  # fmt: skip
    notes = {k: n["desc"] for k, n in nodes.items() if n["desc"]}
    notes.update({f"c_{e['a']}_{e['b']}": e["desc"] for e in g["edges"] if e["desc"]})
    if notes:
        lay["notes"] = notes  # the human's descriptions: Claude turns them into details
    return lay, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", required=True)
    ap.add_argument("--force", action="store_true", help="overwrite an existing layout.yaml")
    args = ap.parse_args(argv)
    cfg = load_config()
    maps = cfg.path("maps_dir")
    g = gr.load(maps, args.map)
    if g is None:
        print(f"fromgraph: no {gr.path_of(maps, args.map)} (draw and approve it in the editor)",
              file=sys.stderr)  # fmt: skip
        return 1
    out = maps / args.map / "layout.yaml"
    if out.exists() and not args.force:
        print(f"fromgraph: {out} exists (use --force to replace it)", file=sys.stderr)
        return 1
    intent_p = maps / args.map / "intent.json"
    intent = json.loads(intent_p.read_text(encoding="utf-8")) if intent_p.is_file() else None
    try:
        lay, report = build_layout(g, intent)
    except ValueError as exc:
        print(f"fromgraph: {exc}", file=sys.stderr)
        return 1
    head = (
        f"# {args.map}: built from the editor graph (maps/{args.map}/graph.json) by "
        "./mf fromgraph.\n# Claude adds the details from `notes` (the human's descriptions).\n"
    )
    out.write_text(head + yaml.safe_dump(lay, sort_keys=False, allow_unicode=True, width=100),
                   encoding="utf-8")  # fmt: skip
    rep = cfg.path("build_dir") / args.map / "fromgraph_report.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bad = [e for e in report["edges"] if not e["ok"]]
    print(f"fromgraph {args.map}: {len(lay['areas'])} rooms, {len(lay['corridors'])} corridors, "
          f"{len(report['moved'])} moved, {len(bad)} edges off by > 10 % -> {out}")  # fmt: skip
    for n in report["notes"]:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
