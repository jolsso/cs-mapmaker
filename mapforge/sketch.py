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
from mapforge.generator.spec import SpecError, corridor_chain


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
    knees, cors, doors = corridor_chain(vs, name, grid, width, height)
    return {"areas": knees, "corridors": [c for c, _ in cors], "doors": doors}


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
