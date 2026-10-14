"""Sketch strokes -> angled corridors (LAYOUT_SPEC "Vinkler og niveauer").

A stroke drawn on the dashboard (an annotation of kind "path", e.g. on the blank grid of
"+ Nyt map") is a freehand line in world coordinates. It becomes layout pieces: the line is
simplified (Ramer-Douglas-Peucker) to a few bends on the grid; each bend becomes a small
square room (a knee), each stretch between bends a `corridors:` entry at whatever angle it
has, with doors into the knees. The ends of the stroke stay open: Claude joins them to the
areas they were drawn from and to (`<name>_start` / `<name>_end` doors are left to the layout).

The result is a suggestion for layout.yaml, not a finished layout: the design rules
(DESIGN_GUIDE.md) still decide, and `./mf generate` / `validate` check it.

Usage: python -m mapforge.sketch --map <map> [--id N] [--width 128] [--height 192]
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import Any

import yaml

from mapforge import annotations
from mapforge.config import load_config
from mapforge.generator.spec import SpecError, corridor_poly

WALL = 16


def simplify(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Ramer-Douglas-Peucker: the fewest points within `tolerance` of the freehand line."""
    if len(points) < 3:
        return [list(p) for p in points]
    (ax, ay), (bx, by) = points[0], points[-1]
    length = math.hypot(bx - ax, by - ay)
    best, at = -1.0, 0
    for i, (px, py) in enumerate(points[1:-1], 1):
        if length:
            d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
        else:
            d = math.hypot(px - ax, py - ay)
        if d > best:
            best, at = d, i
    if best <= tolerance:
        return [list(points[0]), list(points[-1])]
    return simplify(points[: at + 1], tolerance)[:-1] + simplify(points[at:], tolerance)


def _snap(v: float, grid: int) -> int:
    return int(round(v / grid)) * grid


def bends(points: list[list[float]], grid: int, width: int, tolerance: float) -> list[list[int]]:
    """The stroke's bends on the grid; stretches shorter than ~3 corridor widths are merged."""
    pts = [[_snap(x, grid), _snap(y, grid)] for x, y in simplify(points, tolerance)]
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= 3 * width:
            out.append(p)
    if len(out) > 1:
        out[-1] = pts[-1]  # always end where the stroke ends (a short last stretch merges)
    return out


def corridors_from_stroke(
    points: list[list[float]],
    name: str,
    grid: int = 16,
    width: int = 128,
    height: int = 192,
    tolerance: float = 96,
) -> dict[str, list[dict[str, Any]]]:
    """Layout pieces {areas, corridors, doors} for one stroke."""
    vs = bends(points, grid, width, tolerance)
    if len(vs) < 2:
        raise SpecError(f"{name}: the stroke is too short for a corridor (< {3 * width} units)")
    n = len(vs) - 1
    # knee rooms: wide enough for the end of every corridor that meets them
    side = {i: 2 * (width // 2 // grid + 2) * grid for i in range(1, n)}
    for _ in range(3):  # the corridor ends depend on the knee sizes and the other way round
        cors = []
        for k in range(n):
            (ax, ay), (bx, by) = vs[k], vs[k + 1]
            along_y = abs(by - ay) >= abs(bx - ax)
            sgn = 1 if (by - ay if along_y else bx - ax) > 0 else -1
            fx, fy, tx, ty = ax, ay, bx, by
            if k > 0:  # start on the knee's wall (one wall away from it)
                off = sgn * (side[k] // 2 + WALL)
                fy, fx = (ay + off, ax) if along_y else (ay, ax + off)
            if k < n - 1:
                off = sgn * (side[k + 1] // 2 + WALL)
                ty, tx = (by - off, bx) if along_y else (by, bx - off)
            c = {"name": f"{name}_{k + 1}", "from": [fx, fy], "to": [tx, ty], "width": width,
                 "height": height}  # fmt: skip
            try:
                _, along, half, _ = corridor_poly(c, grid)
            except SpecError as exc:
                raise SpecError(f"{name}: bends too close together ({exc})") from exc
            if (along == "y") != along_y:  # moving the ends onto the knees tipped it past 45°
                raise SpecError(f"{name}: stretch {k + 1} is too close to 45° for its knees; "
                                "draw it steeper or flatter, or use `diagonals:`")  # fmt: skip
            cors.append((c, half))
        grown = False
        for k, (_, half) in enumerate(cors):
            for i in (k, k + 1):
                if i in side and side[i] < 2 * half + 2 * grid:
                    side[i], grown = 2 * half + 2 * grid, True
        if not grown:
            break
    areas = [
        {"name": f"{name}_knee{i}", "rect": [vs[i][0] - s // 2, vs[i][1] - s // 2,
                                             vs[i][0] + s // 2, vs[i][1] + s // 2],
         "height": height, "role": "corridor"}
        for i, s in side.items()
    ]  # fmt: skip
    doors = []
    for k, (c, half) in enumerate(cors):
        for i in (k, k + 1):
            if i in side:
                knee = f"{name}_knee{i}"
                doors.append({"name": f"{c['name']}_knee{i}", "between": [c["name"], knee],
                              "width": 2 * half})  # fmt: skip
    return {"areas": areas, "corridors": [c for c, _ in cors], "doors": doors}


def sketch_yaml(map_name: str, ann_id: int | None = None, **kw: Any) -> str:
    """The layout pieces for the map's path annotations, as YAML to paste into layout.yaml."""
    cfg = load_config()
    items = [
        a
        for a in annotations.load(cfg.path("maps_dir"), map_name)
        if a["kind"] == "path" and (ann_id is None or a["id"] == ann_id)
    ]
    out = []
    for a in items:
        pieces = corridors_from_stroke(a["points"], f"s{a['id']}", **kw)
        head = f'# annotation:{a["id"]} "{a["text"]}" -> {len(pieces["corridors"])} corridor(s)'
        body = yaml.safe_dump(pieces, sort_keys=False, default_flow_style=None, width=120)
        out.append(head + "\n" + body)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    parser.add_argument("--id", type=int, default=None, help="only this annotation")
    parser.add_argument("--width", type=int, default=128, help="corridor width across the slant")
    parser.add_argument("--height", type=int, default=192)
    parser.add_argument(
        "--tolerance", type=float, default=96, help="how closely to follow the line"
    )
    args = parser.parse_args(argv)
    try:
        text = sketch_yaml(args.map, args.id, width=args.width, height=args.height,
                           tolerance=args.tolerance)  # fmt: skip
    except SpecError as exc:
        print(f"sketch failed: {exc}", file=sys.stderr)
        return 1
    print(text or f"no strokes (path annotations) for {args.map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
