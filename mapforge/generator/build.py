"""Layout spec -> Valve 220 .map.

Geometry: the spec only describes empty space (areas + doors). Everything else inside an
outer shell (the bounding box of all empty space, grown by `wall`) is solid: the coordinate
axes are compressed to the boundaries that occur, each resulting cell is marked empty or
solid, and solid cells are greedily merged into boxes. The map is therefore sealed by
construction (no leaks) and every vertex lies on the spec's grid.

Inside the empty space the spec adds solids: stairs, ramps, wedges (angled walls), cover
(also raised: platforms, bridges, stacked crates), ladders, and entities in the openings
(glass, door leaves). With zones, every shell face gets the textures of the area it faces.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from mapforge.generator.props import Solid
from mapforge.generator.props import solids as prop_solids
from mapforge.generator.spec import (
    AMBIENT_RADIUS,
    MATERIALS,
    Area,
    Bridge,
    Cover,
    Door,
    Layout,
    SpecError,
)
from mapforge.mapfile.parser import Brush, MapFile
from mapforge.mapfile.writer import box_brush, entity, polyhedron_brush, prism_brush

WORLD_LIMIT = 4096
EMPTY, SOLID, SKY = 0, 1, 2
DETAIL_MAX_H = 128  # func_detail only for solids up to this height above their floor
ZONE_LABEL = 10  # solid cells owned by zone k get ZONE_LABEL + k (keeps zones in separate boxes)

Box = tuple[tuple[int, int, int], tuple[int, int, int]]

# armoury_entity "item" (CS 1.6 FGD)
ARMOURY_ITEMS = {
    "mp5navy": 0, "tmp": 1, "p90": 2, "mac10": 3, "ak47": 4, "sg552": 5, "m4a1": 6, "aug": 7,
    "scout": 8, "g3sg1": 9, "awp": 10, "m3": 11, "xm1014": 12, "m249": 13, "flashbang": 14,
    "hegrenade": 15, "kevlar": 16, "assaultsuit": 17, "smokegrenade": 18,
}  # fmt: skip
BUYING = {"both": 0, "ct": 1, "t": 2, "none": 3}


@dataclass
class Generated:
    mapfile: MapFile
    voids: dict[str, Box]  # area/door name -> empty box
    stats: dict[str, int]
    rad: str = ""  # texture lights for hlrad -lights (<map>.rad); "" = none used


# env_sound room types (HL): tunnel/concrete by size, outside, water
ROOM_TUNNEL, ROOM_CONCRETE, ROOM_OUTSIDE, ROOM_WATER = (5, 6, 7), (17, 18, 19), 21, 15


def _room_type(a: Area, wet: bool) -> int:
    if wet:
        return ROOM_WATER
    if a.outdoor:
        return ROOM_OUTSIDE
    x0, y0, x1, y1 = a.rect
    floor_area = (x1 - x0) * (y1 - y0)
    size = 0 if floor_area < 256 * 512 else 1 if floor_area < 768 * 768 else 2
    return (ROOM_TUNNEL if a.role == "corridor" else ROOM_CONCRETE)[size]


def _octagon(lo: tuple, hi: tuple, grid: int = 8) -> list[tuple[int, int]]:
    """A box's footprint with its corners cut (about a quarter of the short side, on the grid)."""
    (x0, y0), (x1, y1) = lo[:2], hi[:2]
    c = max(grid, min(x1 - x0, y1 - y0) // 4 // grid * grid)
    return [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1),
            (x0, y1 - c), (x0, y0 + c)]  # fmt: skip


def _cylinder(lo: tuple, hi: tuple, grid: int = 8) -> list[tuple[int, int]]:
    """A box's footprint as a faceted ellipse: 8, 12 or 16 sides by size, vertices snapped to
    the grid (inside the box) and reduced to their convex hull, so the prism stays convex."""
    (x0, y0), (x1, y1) = lo[:2], hi[:2]
    across = min(x1 - x0, y1 - y0)
    n = 16 if across >= 128 else 12 if across >= 64 else 8
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2

    def snap(v: float, a: int, b: int) -> int:
        return min(b, max(a, round(v / grid) * grid))

    def facets(phase: float) -> list[tuple[int, int]]:
        pts = {
            (snap(cx + rx * math.cos(t), x0, x1), snap(cy + ry * math.sin(t), y0, y1))
            for t in (2 * math.pi * (i + phase) / n for i in range(n))
        }
        return _hull(sorted(pts))

    # Snapping can make neighbours collinear; keep the rotation that leaves the most sides
    # (ties: flat sides on the axes).
    return max((facets(0.5), facets(0.0)), key=len)


def _hull(pts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Convex hull (monotone chain, counter-clockwise, no collinear points) of sorted points."""

    def turn(o, a, b) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def half(seq):
        out: list[tuple[int, int]] = []
        for p in seq:
            while len(out) >= 2 and turn(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(pts[::-1])


def cover_solids(c: Cover, floor: int) -> list[Solid]:
    """The solids of a cover item: one for a plain cover, several for a preset or themed prop
    (all inside its footprint, so spawns and the walk check treat it as one box)."""
    (px, py), (w, d, h) = c.pos, c.size
    z0 = floor + c.z
    x0, y0, x1, y1 = px - w // 2, py - d // 2, px + w // 2, py + d // 2
    if c.preset is None:
        return [Solid(c.shape, (x0, y0, z0), (x1, y1, z0 + h))]
    return prop_solids(c.preset, (x0, y0), (x1, y1), z0, h)


ARCH_SPRING = 80  # lowest springing line: a standing player (72) fits the whole width


def arch_brushes(lo: tuple, hi: tuple, tex: str, grid: int = 8) -> list[Brush]:
    """Fill for the two top corners of a door opening, leaving a (half-)elliptic arch.

    The arch spans the opening's width; its rise is half the width, but never lower than
    ARCH_SPRING above the floor. Each corner is a fan of triangles from the corner to the
    snapped arc (monotone, so the fan never folds), extruded through the wall.
    """
    ax = 0 if (hi[0] - lo[0]) > (hi[1] - lo[1]) else 1  # the opening's width runs along ax
    u0, u1, z0, z1 = lo[ax], hi[ax], lo[2], hi[2]
    rise = min((u1 - u0) // 2, z1 - z0 - ARCH_SPRING) // grid * grid
    if rise < 2 * grid:
        raise SpecError(f"opening {lo}..{hi}: too low for an arch (needs {ARCH_SPRING + 16})")
    uc, zs, half = (u0 + u1) / 2, z1 - rise, (u1 - u0) / 2

    def snap(v: float) -> int:
        return round(v / grid) * grid

    out = []
    for corner_u, sign in ((u0, -1), (u1, 1)):
        arc = []
        for i in range(9):  # top of the arch (centre) -> springing point at the side
            t = math.pi / 2 * i / 8
            p = (snap(uc + sign * half * math.sin(t)), snap(zs + rise * math.cos(t)))
            if not arc or p != arc[-1]:
                arc.append(p)
        for p, q in zip(arc, arc[1:], strict=False):
            tri = [(corner_u, z1), p, q]
            if (p[0] - corner_u) * (q[1] - z1) == (q[0] - corner_u) * (p[1] - z1):
                continue  # degenerate: all three on one line
            out.append(_extrude_uz(tri, ax, lo[1 - ax], hi[1 - ax], tex))
    return out


def _extrude_uz(poly: list[tuple[int, int]], ax: int, t0: int, t1: int, tex: str) -> Brush:
    """Prism from a convex (u, z) polygon, u along axis `ax`, through t0..t1 on the other."""

    def at(u: int, z: int, t: int) -> tuple[int, int, int]:
        return (u, t, z) if ax == 0 else (t, u, z)

    s0 = [at(u, z, t0) for u, z in poly]
    s1 = [at(u, z, t1) for u, z in poly]
    n = len(poly)
    sides = [[s0[i], s0[(i + 1) % n], s1[(i + 1) % n], s1[i]] for i in range(n)]
    return polyhedron_brush([s0, s1, *sides], tex)


def _pipe(lo: tuple, hi: tuple, tex) -> Brush:
    """A horizontal octagonal prism along the box's long side."""
    ax = 1 if (hi[0] - lo[0]) >= (hi[1] - lo[1]) else 0  # the cross-section's u axis
    profile = _octagon((lo[ax], lo[2]), (hi[ax], hi[2]))
    side = tex if isinstance(tex, str) else tex.get("side", next(iter(tex.values())))
    return _extrude_uz(profile, ax, lo[1 - ax], hi[1 - ax], side)


DOOR_LIGHT_OUT = 48  # a door light hangs this far from the opening, inside each area
FRAME_W, FRAME_D = 16, 8  # a door frame: jamb/lintel width, how far it stands out of the wall


def frame_boxes(lo: tuple, hi: tuple, ceiling: int) -> list[Box]:
    """Jambs on both sides of an opening and a lintel over it, standing FRAME_D out of the wall
    on both sides; the lintel is left out where it would reach the lower ceiling."""
    ax = 0 if (hi[0] - lo[0]) > (hi[1] - lo[1]) else 1  # the opening's width runs along ax
    t0, t1 = lo[1 - ax] - FRAME_D, hi[1 - ax] + FRAME_D
    u0, u1, z0, z1 = lo[ax], hi[ax], lo[2], hi[2]

    def box(a0: int, a1: int, b0: int, b1: int) -> Box:
        if ax == 0:
            return (a0, t0, b0), (a1, t1, b1)
        return (t0, a0, b0), (t1, a1, b1)

    out = [box(u0 - FRAME_W, u0, z0, z1), box(u1, u1 + FRAME_W, z0, z1)]
    if z1 + FRAME_W <= ceiling:
        out.append(box(u0 - FRAME_W, u1 + FRAME_W, z1, z1 + FRAME_W))
    return out


def pitch_fill(a: Area, tex) -> list[Brush]:
    """A pitched ceiling: the room's void reaches `rise` above its eaves; these prisms fill the
    space above the roof slopes, so the ceiling reads as a gable or a shed roof from inside."""
    pt = a.pitch or {}
    x0, y0, x1, y1 = a.rect
    top, rise = a.top, int(pt["rise"])
    gable = pt["shape"] == "gable"
    # the profile's u axis: across the ridge for a gable, along the slope for a shed
    ax = (1 if pt["axis"] == "x" else 0) if gable else (0 if pt["axis"] == "x" else 1)
    u0, u1 = (x0, x1) if ax == 0 else (y0, y1)
    t0, t1 = (y0, y1) if ax == 0 else (x0, x1)
    hi = top + rise
    if gable:
        m = (u0 + u1) // 2
        tris = [[(u0, top), (u0, hi), (m, hi)], [(u1, top), (m, hi), (u1, hi)]]
    else:  # low at the low end of the axis, high at the other
        tris = [[(u0, top), (u0, hi), (u1, hi)]]
    return [_extrude_uz(t, ax, t0, t1, tex) for t in tris]


def roof_brushes(ro, a: Area, tex: str, post_tex: str) -> list[Brush]:
    """A roof slab (flat, shed or gable) over ro.rect, open on the sides, plus corner posts."""
    rx0, ry0, rx1, ry1 = ro.rect
    zb, t, rise = a.floor + ro.z, ro.thickness, ro.rise
    out: list[Brush] = []
    if ro.shape == "flat":
        out.append(box_brush((rx0, ry0, zb), (rx1, ry1, zb + t), tex))
        under = {c: zb for c in ((rx0, ry0), (rx1, ry0), (rx0, ry1), (rx1, ry1))}
    else:
        gable = ro.shape == "gable"
        ax = (1 if ro.axis == "x" else 0) if gable else (0 if ro.axis == "x" else 1)
        u0, u1 = (rx0, rx1) if ax == 0 else (ry0, ry1)
        t0, t1 = (ry0, ry1) if ax == 0 else (rx0, rx1)
        if gable:
            m = (u0 + u1) // 2
            quads = [[(u0, zb), (m, zb + rise), (m, zb + rise + t), (u0, zb + t)],
                     [(m, zb + rise), (u1, zb), (u1, zb + t), (m, zb + rise + t)]]  # fmt: skip
        else:
            quads = [[(u0, zb), (u1, zb + rise), (u1, zb + rise + t), (u0, zb + t)]]
        out += [_extrude_uz(q, ax, t0, t1, tex) for q in quads]

        def under_at(x: int, y: int) -> int:
            u = x if ax == 0 else y
            if gable:
                return zb
            return zb + (rise if u == u1 else 0)

        under = {c: under_at(*c) for c in ((rx0, ry0), (rx1, ry0), (rx0, ry1), (rx1, ry1))}
    if ro.posts:
        for (cx, cy), z_top in under.items():
            px = cx if cx == rx0 else cx - 16
            py = cy if cy == ry0 else cy - 16
            out.append(box_brush((px, py, a.floor), (px + 16, py + 16, z_top), post_tex))
    return out


def fit_texture(brush: Brush, lo: tuple, hi: tuple) -> Brush:
    """Shift every face's texture so it starts at the box's corner (texture space): a panel the
    size of its texture shows exactly one door or window, not a slice of the tiling."""
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    faces = []
    for f in brush.faces:
        u, v = f.u_axis, f.v_axis
        su = -min(sum(c[k] * u[k] for k in range(3)) for c in corners)
        sv = -min(sum(c[k] * v[k] for k in range(3)) for c in corners)
        faces.append(replace(f, u_axis=(u[0], u[1], u[2], su), v_axis=(v[0], v[1], v[2], sv)))
    return replace(brush, faces=faces)


def wall_detail_boxes(layout: Layout, voids: dict[str, Box]) -> list[tuple[Box, str]]:
    """Locked doors and windows along the walls of the listed areas: every `spacing` along each
    wall, doors and windows taking turns (textures picked stably), `depth` out of the wall.
    A panel keeps 16 clear of openings, cover, models and ladders, and fits under the ceiling."""
    wd = layout.wall_details or {}
    if not wd:
        return []
    doors = [p for p in wd["panels"] if p["kind"] == "door"]
    windows = [p for p in wd["panels"] if p["kind"] == "window"]
    spacing, depth = wd["spacing"], wd["depth"]
    out = []
    for name in wd["areas"]:
        a = layout.areas[name]
        if a.poly is not None:
            continue
        x0, y0, x1, y1 = a.rect
        blockers = [b for n, b in voids.items() if n not in layout.areas]  # doors, hatches
        for c in layout.cover:
            if c.area == name:
                (px, py), (w, d, _) = c.pos, c.size
                blockers.append(((px - w // 2, py - d // 2, 0), (px + w // 2, py + d // 2, 0)))
        for m in layout.models:
            if m.area == name and m.clip:
                w, d, _ = m.clip
                blockers.append(((m.pos[0] - w // 2, m.pos[1] - d // 2, 0),
                                 (m.pos[0] + w // 2, m.pos[1] + d // 2, 0)))  # fmt: skip
        for ld in layout.ladders:
            if ld.area == name:
                blockers.append(_ladder_box(layout, ld))
        sides = [("-x", 0, x0, (y0, y1)), ("+x", 0, x1, (y0, y1)),
                 ("-y", 1, y0, (x0, x1)), ("+y", 1, y1, (x0, x1))]  # fmt: skip
        for side, ax, at, (s0, s1) in sides:
            inward = 1 if side[0] == "-" else -1
            k = 0
            for c in range(s0 + spacing // 2, s1 - spacing // 4, spacing):
                pool = (doors, windows)[k % 2] or doors or windows
                k += 1
                pick = int(hashlib.sha1(f"{name}{side}{c}".encode()).hexdigest(), 16)
                p = pool[pick % len(pool)]
                half = p["w"] // 2
                c8 = c // 8 * 8
                u0, u1 = c8 - half, c8 + half
                if u0 < s0 + 16 or u1 > s1 - 16 or p["z"] + p["h"] + 16 > a.height:
                    continue
                t0, t1 = (at, at + depth) if inward > 0 else (at - depth, at)
                lo = [0, 0, a.floor + p["z"]]
                hi = [0, 0, a.floor + p["z"] + p["h"]]
                lo[ax], hi[ax] = t0, t1
                lo[1 - ax], hi[1 - ax] = u0, u1
                clear = True
                for b_lo, b_hi in blockers:  # 16 of room around the panel, in plan
                    if (b_lo[0] < hi[0] + 16 and lo[0] - 16 < b_hi[0]
                            and b_lo[1] < hi[1] + 16 and lo[1] - 16 < b_hi[1]):  # fmt: skip
                        clear = False
                        break
                if clear:
                    out.append(((tuple(lo), tuple(hi)), p["texture"]))
    return out


def door_box(door: Door, areas: dict[str, Area], wall: int) -> Box:
    """The empty box cut through the wall between the two areas of a door.

    The areas must be exactly `wall` units apart on one axis and overlap by at least the door
    width on the other; the door is centred on that overlap (+ offset). A window/vent starts
    `sill` units above the higher floor.
    """
    a, b = (areas[n] for n in door.between)
    ax0, ay0, ax1, ay1 = a.rect
    bx0, by0, bx1, by1 = b.rect
    floor = max(a.floor, b.floor) + door.sill
    height = door.height or min(a.top, b.top) - floor
    if height <= 0 or min(a.top, b.top) < floor + height:
        raise SpecError(f"door {door.name}: sill + height go above the lower of its two ceilings")
    # (gap between the areas, axis the door goes through, wall start, wall end, a's side)
    sides = (
        (bx0 - ax1, "x", ax1, bx0, "+x"),  # b east of a
        (ax0 - bx1, "x", bx1, ax0, "-x"),  # b west of a
        (by0 - ay1, "y", ay1, by0, "+y"),  # b north of a
        (ay0 - by1, "y", by1, ay0, "-y"),  # b south of a
    )
    flip = {"+": "-", "-": "+"}
    for gap, axis, w_lo, w_hi, side in sides:
        # the open stretch of both walls (an angled area only opens where its polygon has an
        # edge on its bounding box)
        sa, sb = a.side_span(side), b.side_span(flip[side[0]] + side[1])
        if sa is None or sb is None:
            continue
        s0, s1 = max(sa[0], sb[0]), min(sa[1], sb[1])
        if s1 - s0 < door.width:
            continue
        if gap == 0:
            raise SpecError(f"door {door.name}: the areas touch, there is no wall between them")
        if gap != wall:
            continue
        c = (s0 + s1) // 2 + door.offset
        o0, o1 = c - door.width // 2, c + door.width // 2
        if o0 < s0 or o1 > s1:
            raise SpecError(f"door {door.name}: offset puts it outside the shared wall")
        if axis == "x":
            return ((w_lo, o0, floor), (w_hi, o1, floor + height))
        return ((o0, w_lo, floor), (o1, w_hi, floor + height))
    raise SpecError(
        f"door {door.name}: {door.between[0]} and {door.between[1]} do not share a wall "
        f"(they must be exactly {wall} units apart with >= {door.width} units of overlap; "
        "an angled area only opens on the polygon edges that lie on its bounding box)"
    )


def _overpasses(voids: list[tuple[Box, bool]], sky_over: list[Area], wall: int) -> list[Box]:
    """Space stacked over an outdoor area (a corridor crossing above a street) sits in that
    area's sky: its shell (`wall` thick: floor slab, side walls and, unless it is outdoor
    itself, a roof) must be solid there, not sky. (box, outdoor) voids -> shell boxes."""
    out = []
    for (lo, hi), open_top in voids:
        for a in sky_over:
            x0, y0, x1, y1 = a.rect
            if lo[2] >= a.top and lo[0] < x1 and hi[0] > x0 and lo[1] < y1 and hi[1] > y0:
                top = hi[2] if open_top else hi[2] + wall
                out.append(((lo[0] - wall, lo[1] - wall, a.top), (hi[0] + wall, hi[1] + wall, top)))
                break
    return out


PARAPET = 16  # a yard's walls end this far above its open top
GABLE_MAX = 96  # highest ridge over a building block (stays below the sky: skyline.air >= 128)


@dataclass
class Skyline:
    """Buildings on the plan grid (cells = the shell's x/y cuts)."""

    roof: np.ndarray  # (nx, ny) roof height per column; yards: their open top
    blocks: list[dict]  # building blocks: {cells, z, box: (x0, y0, x1, y1), rect: bool}


def skyline_plan(layout: Layout, voids: dict[str, Box], xs, ys) -> Skyline:
    """The buildings around the play space, on the plan grid (third version, after two play
    tests: per-area heights gave strips, per-block heights gave fragments that did not line up).

    The yards are the streets. Their edges (and a wall's thickness off them) cut the plan into
    city blocks:
    - a yard's own column is open above its top; the strip of wall around it ends PARAPET above
      that (the same height all the way round); an opening between two yards stays open;
    - every other block is one building: high enough for everything inside it (an indoor room
      or corridor: its ceiling + wall; a pitched hall: its ridge + wall) and for the yard walls
      around it, plus a stable variation from the block's position, with a gable roof.
    Buildings therefore line up along the yards and every one of them has a roof."""
    sk = layout.skyline or {}
    hs, wall = sk["heights"], layout.wall
    sx0, sx1, sy0, sy1 = xs[0], xs[-1], ys[0], ys[-1]
    yards = [a for a in layout.areas.values() if a.outdoor]
    cut_x, cut_y = {sx0, sx1}, {sy0, sy1}
    for a in yards:
        x0, y0, x1, y1 = a.rect
        cut_x |= {x0 - wall, x0, x1, x1 + wall}
        cut_y |= {y0 - wall, y0, y1, y1 + wall}
    bx = sorted(c for c in cut_x if sx0 <= c <= sx1)
    by = sorted(c for c in cut_y if sy0 <= c <= sy1)
    cx = (np.array(xs[:-1]) + np.array(xs[1:])) / 2
    cy = (np.array(ys[:-1]) + np.array(ys[1:])) / 2
    gx, gy = np.meshgrid(cx, cy, indexing="ij")
    roof = np.zeros(gx.shape)

    def dist(a: Area, x, y):
        x0, y0, x1, y1 = a.rect
        return np.maximum(np.maximum(x0 - x, x - x1), 0) + np.maximum(np.maximum(y0 - y, y - y1), 0)

    # first the yards and their walls (the buildings need their heights)
    kind = {}
    for i in range(len(bx) - 1):
        for j in range(len(by) - 1):
            mx, my = (bx[i] + bx[i + 1]) / 2, (by[j] + by[j + 1]) / 2
            inside = [a for a in yards if dist(a, mx, my) == 0]
            near = [a for a in yards if 0 < dist(a, mx, my) <= wall]
            if inside:
                kind[i, j] = ("yard", max(voids[a.name][1][2] for a in inside))
            elif near:
                kind[i, j] = ("wall", max(voids[a.name][1][2] for a in near) + PARAPET)
            else:
                kind[i, j] = ("building", 0)
    blocks = []
    for (i, j), (k, z) in kind.items():
        x0, x1, y0, y1 = bx[i], bx[i + 1], by[j], by[j + 1]
        cells = (gx > x0) & (gx < x1) & (gy > y0) & (gy < y1)
        if k != "building":
            roof[cells] = z
            continue
        need = 0
        for a in layout.areas.values():  # everything indoor under this block
            ax0, ay0, ax1, ay1 = a.rect
            if not a.outdoor and ax0 < x1 and x0 < ax1 and ay0 < y1 and y0 < ay1:
                need = max(need, voids[a.name][1][2] + wall)
        for (i2, j2), (k2, z2) in kind.items():  # and the yard walls touching it
            if k2 == "wall" and abs(i2 - i) + abs(j2 - j) == 1:
                need = max(need, z2)
        if not need:
            need = max(voids[a.name][1][2] for a in layout.areas.values()) + wall
        pick = int(hashlib.sha1(f"{x0},{y0},{x1},{y1}".encode()).hexdigest(), 16) % len(hs)
        z = int(need) + hs[pick]
        roof[cells] = z
        blocks.append({"z": z, "box": (int(x0), int(y0), int(x1), int(y1)), "rect": True})
    for d in layout.doors:  # an opening between two yards is open above (no beam over it)
        a, b = (layout.areas[n] for n in d.between)
        if a.outdoor and b.outdoor and d.walkable:
            (dx0, dy0, _), (dx1, dy1, dz1) = voids[d.name]
            if dz1 >= min(a.top, b.top):
                gap = (gx > dx0) & (gx < dx1) & (gy > dy0) & (gy < dy1)
                roof[gap] = dz1
    return Skyline(roof, blocks)


def gable_roofs(sky: Skyline, tex: dict[str, str], grid: int = 8) -> list[Brush]:
    """A gable roof on every rectangular building block: ridge along the long side, rise half
    the short side (at most GABLE_MAX); slopes in the roof texture, gable ends in the facade's."""
    out = []
    for b in sky.blocks:
        x0, y0, x1, y1 = b["box"]
        if not b["rect"] or min(x1 - x0, y1 - y0) < 128:
            continue
        ax = 1 if (x1 - x0) >= (y1 - y0) else 0  # the profile runs across the ridge
        u0, u1 = (x0, x1) if ax == 0 else (y0, y1)
        t0, t1 = (y0, y1) if ax == 0 else (x0, x1)
        m = (u0 + u1) // 2 // grid * grid
        rise = min((u1 - u0) // 2 // grid * grid, GABLE_MAX)
        z = b["z"]
        tri = [(u0, z), (m, z + rise), (u1, z)]
        brush = _extrude_uz(tri, ax, t0, t1, tex["roof"])
        out.append(brush)
    return out


def _solid_cells(
    voids: list[Box],
    sky_over: list[Area],
    shell: Box,
    owners: list[tuple[Area, int]],
    overpasses: list[Box] = (),
    skyline=None,
    wall: int = 16,
) -> tuple[list, np.ndarray, Skyline | None]:
    """Label grid cells of the shell. Classic: solid everywhere, sky straight above outdoor areas.
    With a skyline (a function from the plan grid to a Skyline): each column is a building up to
    its roof height, open air above it, and sky on the shell's skin above the roofs."""
    (sx0, sy0, sz0), (sx1, sy1, sz1) = shell
    axes = []
    for i, (lo, hi) in enumerate(((sx0, sx1), (sy0, sy1), (sz0, sz1))):
        cuts = {lo, hi}
        if skyline is not None:
            cuts |= {lo + wall, hi - wall}
        for b in [*voids, *overpasses]:
            cuts |= {b[0][i], b[1][i]}
        for a in sky_over:  # split at outdoor area edges so sky cells line up with them
            if i < 2:
                cuts |= {a.rect[i], a.rect[i + 2]}
            else:
                cuts.add(a.top)
        axes.append(sorted(c for c in cuts if lo <= c <= hi))
    xs, ys, zs = axes
    sky = skyline(xs, ys) if skyline is not None else None
    if sky is not None:  # the roofs' heights become z cuts too
        zs = sorted(set(zs) | {int(v) for v in np.unique(sky.roof) if sz0 < v < sz1})
        axes[2] = zs
    cx = (np.array(xs[:-1]) + np.array(xs[1:])) / 2
    cy = (np.array(ys[:-1]) + np.array(ys[1:])) / 2
    cz = (np.array(zs[:-1]) + np.array(zs[1:])) / 2
    gx, gy, gz = np.meshgrid(cx, cy, cz, indexing="ij")
    label = np.full(gx.shape, SOLID, dtype=np.int16)
    if any(k for _, k in owners):
        # each solid cell belongs to the zone of the nearest area, so no box spans two zones
        best = np.full(gx.shape, np.inf)
        for a, k in owners:
            x0, y0, x1, y1 = a.rect
            d = (np.maximum(np.maximum(x0 - gx, gx - x1), 0)
                 + np.maximum(np.maximum(y0 - gy, gy - y1), 0)
                 + np.maximum(np.maximum(a.floor - gz, gz - a.top), 0))  # fmt: skip
            closer = d < best
            best[closer] = d[closer]
            label[closer] = SOLID if k == 0 else ZONE_LABEL + k
    if sky is not None:
        skin = (gx < sx0 + wall) | (gx > sx1 - wall) | (gy < sy0 + wall) | (gy > sy1 - wall)
        skin |= gz > sz1 - wall
        above = gz > sky.roof[:, :, None]
        for a in sky_over:  # straight above a yard the air starts at the yard's own top
            x0, y0, x1, y1 = a.rect
            above |= (gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > a.top)
        label[above & skin] = SKY
        label[above & ~skin] = EMPTY  # open air over the roofs and the yards
        for (x0, y0, z0), (x1, y1, z1) in overpasses:
            inside = (gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > z0) & (gz < z1)
            label[inside & ((label == SKY) | (label == EMPTY))] = SOLID
    else:
        for a in sky_over:
            x0, y0, x1, y1 = a.rect
            label[(gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > a.top)] = SKY
        for (x0, y0, z0), (x1, y1, z1) in overpasses:
            inside = (gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > z0) & (gz < z1)
            label[inside & (label == SKY)] = SOLID
    for (x0, y0, z0), (x1, y1, z1) in voids:
        label[(gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > z0) & (gz < z1)] = EMPTY
    return axes, label, sky


def _greedy_boxes(label: np.ndarray) -> list[tuple[int, slice, slice, slice]]:
    """Merge equal-label non-empty cells into boxes (x first, then y, then z)."""
    done = label == EMPTY
    nx, ny, nz = label.shape
    boxes = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                if done[i, j, k]:
                    continue
                lab = label[i, j, k]
                i1 = i + 1
                while i1 < nx and not done[i1, j, k] and label[i1, j, k] == lab:
                    i1 += 1
                j1 = j + 1
                while j1 < ny and np.all(~done[i:i1, j1, k] & (label[i:i1, j1, k] == lab)):
                    j1 += 1
                k1 = k + 1
                while k1 < nz and np.all(~done[i:i1, j:j1, k1] & (label[i:i1, j:j1, k1] == lab)):
                    k1 += 1
                done[i:i1, j:j1, k:k1] = True
                boxes.append((int(lab), slice(i, i1), slice(j, j1), slice(k, k1)))
    return boxes


def _along(a: Area, axis: str, start: int) -> tuple[str, int, int, int]:
    """(axis letter, sign, coordinate where the feature begins, far end of the area)."""
    x0, y0, x1, y1 = a.rect
    along = axis[1]
    sign = 1 if axis[0] == "+" else -1
    lo, hi = (x0, x1) if along == "x" else (y0, y1)
    begin = lo + start if sign > 0 else hi - start
    end = hi if sign > 0 else lo
    return along, sign, begin, end


def _stair_boxes(layout: Layout) -> list[tuple[Box, Area]]:
    out = []
    for st in layout.stairs:
        a = layout.areas[st.area]
        x0, y0, x1, y1 = a.rect
        n = st.rise // st.step
        along, sign, begin, end = _along(a, st.axis, st.start)
        for i in range(1, n + 1):
            # step i reaches from its front edge to the far end of the area (a solid flight)
            front = begin + sign * (i - 1) * st.run
            s0, s1 = sorted((front, end))
            z1 = a.floor + i * st.step
            if along == "x":
                out.append((((s0, y0, a.floor), (s1, y1, z1)), a))
            else:
                out.append((((x0, s0, a.floor), (x1, s1, z1)), a))
    return out


def _profile_brush(a: Area, along: str, profile: list[tuple[int, int]], tex) -> Brush:
    """Prism across the whole area width from a convex (along, z) profile."""
    x0, y0, x1, y1 = a.rect
    if along == "x":
        side0 = [(u, y0, z) for u, z in profile]
        side1 = [(u, y1, z) for u, z in profile]
    else:
        side0 = [(x0, u, z) for u, z in profile]
        side1 = [(x1, u, z) for u, z in profile]
    n = len(profile)
    faces = [side0, side1] + [
        [side0[i], side0[(i + 1) % n], side1[(i + 1) % n], side1[i]] for i in range(n)
    ]
    return polyhedron_brush(faces, tex)


def _stair_clips(layout: Layout, tex: str) -> list[Brush]:
    """A player-clip ramp resting on the step nosings of each `clip: true` flight."""
    out = []
    for st in layout.stairs:
        if not st.clip:
            continue
        a = layout.areas[st.area]
        n = st.rise // st.step
        if n < 2:
            continue
        along, sign, begin, end = _along(a, st.axis, st.start)
        lo, hi = (a.rect[0], a.rect[2]) if along == "x" else (a.rect[1], a.rect[3])
        top = begin + sign * (n - 1) * st.run  # front of the last step
        foot = begin - sign * st.run  # where the nosing line meets the floor
        edge = lo if sign > 0 else hi
        if (foot - edge) * sign < 0:  # the line meets the floor outside the area: start higher
            z_edge = a.floor + abs(edge - foot) * st.step // st.run
            if abs(edge - foot) * st.step % st.run:
                raise SpecError(f"stairs {st.name}: clip ramp would be off the grid")
            prof = [(edge, a.floor), (edge, z_edge), (top, a.floor + st.rise), (top, a.floor)]
        else:
            prof = [(foot, a.floor), (top, a.floor + st.rise), (top, a.floor)]
        out.append(_profile_brush(a, along, prof, tex))
    return out


def _ramp_brushes(layout: Layout, surf, ramps: list | None = None) -> list[Brush]:
    out = []
    for rp in layout.ramps if ramps is None else ramps:
        a = layout.areas[rp.area]
        along, sign, begin, end = _along(a, rp.axis, rp.start)
        top = begin + sign * rp.length
        z0, z1 = a.floor, a.floor + rp.rise
        out.append(_profile_brush(a, along, [(begin, z0), (top, z1), (top, z0)], surf(a)))
        if top != end:  # the rest of the area is raised
            s0, s1 = sorted((top, end))
            x0, y0, x1, y1 = a.rect
            lo, hi = ((s0, y0, z0), (s1, y1, z1)) if along == "x" else ((x0, s0, z0), (x1, s1, z1))
            out.append(box_brush(lo, hi, surf(a)))
    return out


def _wedge_brushes(layout: Layout, surf) -> list[Brush]:
    out = []
    for w in layout.wedges:
        a = layout.areas[w.area]
        x0, y0, x1, y1 = a.rect
        dx, dy = w.size
        cx, sx = (x1, -1) if "e" in w.corner else (x0, 1)
        cy, sy = (y1, -1) if "n" in w.corner else (y0, 1)
        tri = [(cx, cy), (cx + sx * dx, cy), (cx, cy + sy * dy)]
        out.append(prism_brush(tri, a.floor, a.floor + (w.height or a.height), surf(a)))
    return out


def _poly_fill(a: Area) -> list[list[tuple[int, int]]]:
    """Triangles filling the part of a polygon area's bounding box outside the polygon: each
    slanted edge with the box corner it faces (the corner sees the whole convex chain, so the
    fans of the four corners tile the leftover exactly)."""
    if a.poly is None:
        return []
    x0, y0, x1, y1 = a.rect
    out = []
    pts = a.poly
    for p, q in zip(pts, pts[1:] + pts[:1], strict=True):
        nx, ny = q[1] - p[1], p[0] - q[0]  # outward normal of a counter-clockwise edge
        if nx == 0 or ny == 0:
            continue  # an axis-aligned edge of a convex polygon lies on the bounding box
        out.append([(x1 if nx > 0 else x0, y1 if ny > 0 else y0), p, q])
    return out


LIFT_BUTTON = (16, 40, 8)  # footprint, pedestal height, button height


def _lift_entities(h, areas: dict[str, Area], tex: dict[str, str], world) -> list:
    """A func_plat filling the hatch at the upper floor (plats are drawn at the top) that
    travels down to the lower floor. `auto`: it waits at the bottom and rises when stepped
    on; `button`: it starts at the top and a button on each floor (a pedestal next to the
    hatch) sends it up or down. Bots cannot ride it (YaPB's analyser makes no lift nodes), so
    it must never be the only way between two areas."""
    lower, upper = areas[h.lower], areas[h.upper]
    hx0, hy0, hx1, hy1 = h.rect
    name = f"lift_{h.name}"
    props = {"classname": "func_plat", "height": str(upper.floor - lower.floor),
             "speed": "150", "sounds": "2"}  # fmt: skip
    if h.lift == "button":
        props["targetname"] = name
    plat = box_brush((hx0, hy0, upper.floor - 8), (hx1, hy1, upper.floor), tex["door"])
    out = [entity(props, [plat])]
    if h.lift != "button":
        return out
    size, pedestal, knob = LIFT_BUTTON
    cx, cy = (hx0 + hx1) // 2, (hy0 + hy1) // 2
    for a in (lower, upper):
        for bx, by in ((hx1 + 16, cy - size // 2), (hx0 - 16 - size, cy - size // 2),
                       (cx - size // 2, hy1 + 16), (cx - size // 2, hy0 - 16 - size)):  # fmt: skip
            if a.inside(bx, by, margin=0) and a.inside(bx + size, by + size, margin=0):
                break
        else:
            raise SpecError(f"hatch {h.name}: no room for the lift button in {a.name}")
        z = a.floor
        world.brushes.append(box_brush((bx, by, z), (bx + size, by + size, z + pedestal),
                                       tex["door"]))  # fmt: skip
        out.append(entity({"classname": "func_button", "target": name, "angle": "-2",
                           "speed": "50", "wait": "1", "lip": "4", "sounds": "1"},
                          [box_brush((bx, by, z + pedestal), (bx + size, by + size,
                                                              z + pedestal + knob),
                                     tex["door"])]))  # fmt: skip
    return out


def _bridge_boxes(br: Bridge, a: Area) -> list[Box]:
    """A bridge's deck (first) and its railings: wall to wall along its axis."""
    x0, y0, x1, y1 = a.rect
    top = a.floor + br.z
    lo, hi = (y0, y1) if br.axis == "x" else (x0, x1)
    c = (lo + hi) // 2 + br.pos
    c0, c1 = c - br.width // 2, c + br.width // 2
    parts = [(c0, c1, top - br.thickness, top)]
    if br.rail:
        parts += [(c0, c0 + 8, top, top + br.rail), (c1 - 8, c1, top, top + br.rail)]
    if br.axis == "x":
        return [((x0, s0, z0), (x1, s1, z1)) for s0, s1, z0, z1 in parts]
    return [((s0, y0, z0), (s1, y1, z1)) for s0, s1, z0, z1 in parts]


def _ladder_box(layout: Layout, ld) -> Box:
    a = layout.areas[ld.area]
    x0, y0, x1, y1 = a.rect
    depth = 8
    z0, z1 = a.floor, a.floor + ld.height
    if ld.wall[1] == "x":
        c = (y0 + y1) // 2 + ld.pos
        xa, xb = (x1 - depth, x1) if ld.wall[0] == "+" else (x0, x0 + depth)
        return ((xa, c - ld.width // 2, z0), (xb, c + ld.width // 2, z1))
    c = (x0 + x1) // 2 + ld.pos
    ya, yb = (y1 - depth, y1) if ld.wall[0] == "+" else (y0, y0 + depth)
    return ((c - ld.width // 2, ya, z0), (c + ld.width // 2, yb, z1))


def _face_textures(
    lo: tuple, hi: tuple, voids: list[tuple[Box, Area]], tex_of, outside: dict | None = None
) -> dict[str, str]:
    """Per side of a shell box: the texture of the area it faces (largest touching overlap);
    with a skyline, a side that faces no area looks out into the open air: roof on top,
    facade on the sides (hidden inner faces get them too, which costs nothing)."""
    out = {}
    for axis in range(3):
        for sign, coord in ((-1, lo[axis]), (1, hi[axis])):
            o = [i for i in range(3) if i != axis]
            best, best_a = 0, None
            for (vlo, vhi), area in voids:
                touch = vhi[axis] == coord if sign < 0 else vlo[axis] == coord
                if not touch:
                    continue
                ov = 1
                for i in o:
                    ov *= max(0, min(hi[i], vhi[i]) - max(lo[i], vlo[i]))
                if ov > best:
                    best, best_a = ov, area
            side = "xyz"[axis]
            key = ("+" if sign > 0 else "-") + side
            if best_a is None and outside:
                out[key] = outside["roof"] if key == "+z" else outside["facade"]
                continue
            t = tex_of(best_a)
            out[key] = t["floor"] if key == "+z" else t["ceiling"] if key == "-z" else t["wall"]
    return out


def generate(layout: Layout) -> Generated:
    tex = layout.textures
    areas = layout.areas
    zone_names = sorted(layout.zones)

    def tex_of(a: Area | None) -> dict[str, str]:
        z = layout.zones.get(a.zone) if a is not None and a.zone else None
        return {**tex, **{k: v for k, v in (z or {}).items() if k in tex}}

    def surf(a: Area | None) -> dict[str, str]:
        t = tex_of(a)
        return {"top": t["floor"], "bottom": t["ceiling"], "side": t["wall"]}

    voids: dict[str, Box] = {
        a.name: (
            (a.rect[0], a.rect[1], a.floor),
            (a.rect[2], a.rect[3], a.top + (int(a.pitch["rise"]) if a.pitch else 0)),
        )
        for a in areas.values()
    }
    for a in areas.values():  # the roof space of a pitched hall must be free (+ a wall above)
        if not a.pitch:
            continue
        (hx0, hy0, _), (hx1, hy1, hz1) = voids[a.name]
        for b in areas.values():
            bx0, by0, bx1, by1 = b.rect
            if (b is not a and bx0 < hx1 and hx0 < bx1 and by0 < hy1 and hy0 < by1
                    and b.floor < hz1 + layout.wall and b.top > a.top):  # fmt: skip
                raise SpecError(f"area {a.name}: its pitched roof runs into {b.name} above it")
    for d in layout.doors:
        voids[d.name] = door_box(d, areas, layout.wall)
    for h in layout.hatches:
        hx0, hy0, hx1, hy1 = h.rect
        voids[h.name] = ((hx0, hy0, areas[h.lower].top), (hx1, hy1, areas[h.upper].floor))
    lo = np.min([b[0] for b in voids.values()], axis=0) - layout.wall
    hi = np.max([b[1] for b in voids.values()], axis=0) + layout.wall
    roofline = bool(layout.skyline)
    if roofline:  # room for the highest building + its gable + open air, then the sky
        tallest = max(v[1][2] for v in voids.values()) + layout.wall + PARAPET
        hi[2] = max(hi[2], tallest + max(layout.skyline["heights"]) + GABLE_MAX
                    + layout.skyline["air"] + layout.wall)  # fmt: skip
    if np.any(np.abs(lo) > WORLD_LIMIT) or np.any(np.abs(hi) > WORLD_LIMIT):
        raise SpecError(f"map exceeds ±{WORLD_LIMIT} units: {lo.tolist()} .. {hi.tolist()}")
    shell: Box = (tuple(int(v) for v in lo), tuple(int(v) for v in hi))
    outdoor = [a for a in areas.values() if a.outdoor]
    owners = [(a, zone_names.index(a.zone) + 1 if a.zone else 0) for a in areas.values()]
    over = _overpasses(
        [(b, n in areas and areas[n].outdoor) for n, b in voids.items()], outdoor, layout.wall
    )
    plan = (lambda xs_, ys_: skyline_plan(layout, voids, xs_, ys_)) if roofline else None
    (xs, ys, zs), label, sky = _solid_cells(
        list(voids.values()), outdoor, shell, owners, over, plan, layout.wall
    )
    door_area = {d.name: areas[d.between[0]] for d in layout.doors}
    door_area.update({h.name: areas[h.lower] for h in layout.hatches})
    void_areas = [(b, areas.get(n) or door_area[n]) for n, b in voids.items()]
    sk = layout.skyline or {}
    outside = (
        {"facade": sk.get("facade") or tex["wall"], "roof": sk.get("roof") or tex["ceiling"]}
        if roofline
        else None
    )  # building faces that look out into the open air above the roofs

    world = entity(
        {
            "classname": "worldspawn",
            "mapversion": "220",
            "wad": "mapforge_dev.wad",
            "skyname": layout.sky.get("name", "desert"),
            "MaxRange": "8192",
            "message": layout.name,
        }
    )
    for lab, si, sj, sk in _greedy_boxes(label):
        b_lo = (xs[si.start], ys[sj.start], zs[sk.start])
        b_hi = (xs[si.stop], ys[sj.stop], zs[sk.stop])
        if lab == SKY:
            t: str | dict[str, str] = tex["sky"]
        elif layout.zones or roofline:
            t = _face_textures(b_lo, b_hi, void_areas, tex_of, outside)
        else:
            t = surf(None)
        world.brushes.append(box_brush(b_lo, b_hi, t))
    if sky is not None:
        world.brushes += gable_roofs(sky, outside)
    if roofline:  # players stay below each yard's open top: no boosting onto the roofs
        for a in outdoor:
            x0, y0, x1, y1 = a.rect
            world.brushes.append(box_brush((x0, y0, a.top), (x1, y1, a.top + 8), tex["clip"]))
    n_shell = len(world.brushes)

    # Solids inside the empty space. With `detail`, the low ones (stairs, ramps, crates: top at
    # most DETAIL_MAX_H above the floor) go into one func_detail (SDHLT): they still block and
    # are lit like world, but do not split vis leaves. Wall-like solids (angled walls, pillars,
    # anything taller) stay structural: they seal sightlines for VIS and the world faces behind
    # them are removed by CSG.
    inner: list[tuple[Brush, int]] = []  # (brush, height above the area floor)
    for (b_lo, b_hi), a in _stair_boxes(layout):
        inner.append((box_brush(b_lo, b_hi, surf(a)), b_hi[2] - a.floor))
    for rp in layout.ramps:
        inner += [(b, rp.rise) for b in _ramp_brushes(layout, surf, [rp])]
    walls = _wedge_brushes(layout, surf)
    for a in areas.values():  # angled walls of polygon areas: structural, like wedges
        walls += [prism_brush(tri, a.floor, a.top, surf(a)) for tri in _poly_fill(a)]
    for br in layout.bridges:
        a = areas[br.area]
        for i, (b_lo, b_hi) in enumerate(_bridge_boxes(br, a)):  # deck, then railings
            inner.append((box_brush(b_lo, b_hi, surf(a) if i == 0 else tex_of(a)["cover"]),
                          b_hi[2] - a.floor))  # fmt: skip
    breakables: list[Brush] = []
    ents = [world]
    for c in layout.cover:
        a = areas[c.area]
        ctex = c.texture or tex_of(a)["cover"]
        for i, sol in enumerate(cover_solids(c, a.floor)):
            shape, c_lo, c_hi = sol.shape, sol.lo, sol.hi
            stex = c.texture or sol.tex or ctex  # an explicit texture beats the prop's own
            if shape == "octagon":
                brush = prism_brush(_octagon(c_lo, c_hi), c_lo[2], c_hi[2], stex)
            elif shape == "cylinder":
                brush = prism_brush(_cylinder(c_lo, c_hi), c_lo[2], c_hi[2], stex)
            elif shape == "pipe":
                brush = _pipe(c_lo, c_hi, stex)
            else:
                brush = box_brush(c_lo, c_hi, stex)
            if c.breakable:
                mat = MATERIALS[c.breakable]
                tname = f"break_{c.name}" + (f"_{i + 1}" if c.preset else "")
                ents.append(entity({"classname": "func_breakable", "material": str(mat),
                                    "health": "20" if c.breakable == "glass" else "80",
                                    "targetname": tname}, [brush]))  # fmt: skip
                breakables.append(brush)
                continue
            inner.append((brush, c_hi[2] - a.floor))
    detail = [b for b, top in inner if layout.detail and top <= DETAIL_MAX_H]
    world.brushes += walls + [b for b, top in inner if not (layout.detail and top <= DETAIL_MAX_H)]
    if detail:
        ents.append(entity({"classname": "func_detail", "zhlt_detaillevel": "1"}, detail))
    world.brushes += _stair_clips(layout, tex["clip"])
    for a in areas.values():  # pitched hall ceilings
        if a.pitch:
            world.brushes += pitch_fill(a, tex_of(a)["ceiling"])
    for ro in layout.roofs:  # roofs over parts of areas, open on the sides
        a = areas[ro.area]
        world.brushes += roof_brushes(ro, a, ro.texture or tex_of(a)["ceiling"], tex_of(a)["cover"])

    # Openings: glass panes and door leaves fill the opening's box; arches round its top;
    # frames (jambs + lintel) are detail brushes around it.
    frames: list[Brush] = []
    for d in layout.doors:
        (o_lo, o_hi) = voids[d.name]
        if d.frame:
            ceiling = min(areas[n].top for n in d.between)
            frames += [box_brush(a, b, d.frame) for a, b in frame_boxes(o_lo, o_hi, ceiling)]
        if d.arch:
            try:
                world.brushes += arch_brushes(o_lo, o_hi, tex_of(areas[d.between[0]])["wall"])
            except SpecError as exc:
                raise SpecError(f"door {d.name}: {exc}") from None
        if d.glass:
            ents.append(entity({"classname": "func_breakable", "material": "0", "health": "20",
                                "rendermode": "2", "renderamt": "110"},
                               [box_brush(o_lo, o_hi, tex["glass"])]))  # fmt: skip
        elif d.gate == "sliding":
            ents.append(entity({"classname": "func_door", "angle": "-1", "speed": "160",
                                "wait": "3", "lip": "8", "targetname": f"gate_{d.name}"},
                               [box_brush(o_lo, o_hi, tex["door"])]))  # fmt: skip
        elif d.gate == "rotating":
            # hinge (ORIGIN brush) at the low end of the opening's long side
            ax = 0 if (o_hi[0] - o_lo[0]) > (o_hi[1] - o_lo[1]) else 1
            h_lo = list(o_lo)
            h_hi = list(o_hi)
            h_hi[ax] = o_lo[ax] + 16
            ents.append(entity({"classname": "func_door_rotating", "distance": "90",
                                "speed": "120", "wait": "3", "targetname": f"gate_{d.name}"},
                               [box_brush(o_lo, o_hi, tex["door"]),
                                box_brush(tuple(h_lo), tuple(h_hi), tex["origin"])]))  # fmt: skip

    # Ladders: a non-solid ladder texture against the wall + the climbable func_ladder volume.
    for ld in layout.ladders:
        l_lo, l_hi = _ladder_box(layout, ld)
        ents.append(
            entity({"classname": "func_illusionary"}, [box_brush(l_lo, l_hi, tex["ladder"])])
        )
        ents.append(entity({"classname": "func_ladder"}, [box_brush(l_lo, l_hi, tex["trigger"])]))

    # Hatches: an optional lift (func_plat, drawn at the top) or ladder through the hole.
    for h in layout.hatches:
        if h.lift:
            ents += _lift_entities(h, areas, tex, world)
            continue
        if not h.ladder:
            continue
        hx0, hy0, hx1, hy1 = h.rect
        z0, z1 = areas[h.lower].floor, areas[h.upper].floor
        if h.ladder[1] == "x":
            cy = (hy0 + hy1) // 2
            xa, xb = (hx1 - 8, hx1) if h.ladder[0] == "+" else (hx0, hx0 + 8)
            l_lo, l_hi = (xa, cy - 16, z0), (xb, cy + 16, z1)
        else:
            cx = (hx0 + hx1) // 2
            ya, yb = (hy1 - 8, hy1) if h.ladder[0] == "+" else (hy0, hy0 + 8)
            l_lo, l_hi = (cx - 16, ya, z0), (cx + 16, yb, z1)
        ents.append(
            entity({"classname": "func_illusionary"}, [box_brush(l_lo, l_hi, tex["ladder"])])
        )
        ents.append(entity({"classname": "func_ladder"}, [box_brush(l_lo, l_hi, tex["trigger"])]))

    # Water: liquid brushes (texture !WATER) from the floor up `depth`.
    for w in layout.water:
        a = areas[w.area]
        wx0, wy0, wx1, wy1 = w.rect
        world.brushes.append(
            box_brush((wx0, wy0, a.floor), (wx1, wy1, a.floor + w.depth), tex["water"])
        )

    # Spot lights.
    for sp in layout.spots:
        a = areas[sp.area]
        r, g, bl = sp.color
        ents.append(entity({"classname": "light_spot",
                            "origin": f"{sp.pos[0]} {sp.pos[1]} {a.floor + sp.z}",
                            "angles": f"{sp.pitch} {sp.yaw} 0", "pitch": str(sp.pitch),
                            "_light": f"{r} {g} {bl} {sp.brightness}",
                            "_cone": str(sp.cone[0]), "_cone2": str(sp.cone[1])}))  # fmt: skip

    for (p_lo, p_hi), ptex in wall_detail_boxes(layout, voids):  # locked doors and windows
        frames.append(fit_texture(box_brush(p_lo, p_hi, ptex), p_lo, p_hi))
    if frames:
        ents.append(entity({"classname": "func_detail", "zhlt_detaillevel": "1"}, frames))

    # Ambient sounds: looping ambient_generic, audible within its radius.
    for am in layout.ambient:
        a = areas[am.area]
        x, y = (
            am.pos
            if am.pos
            else a.centroid()
            if a.poly
            else ((a.rect[0] + a.rect[2]) // 2, (a.rect[1] + a.rect[3]) // 2)
        )
        ents.append(entity({"classname": "ambient_generic", "targetname": f"amb_{am.name}",
                            "origin": f"{int(x)} {int(y)} {a.floor + am.z}", "message": am.sound,
                            "health": str(am.volume), "pitch": "100", "pitchstart": "100",
                            "spawnflags": str(AMBIENT_RADIUS[am.radius])}))  # fmt: skip

    # Models the game ships: env_sprite shows a .mdl (cycler_sprite is buggy and meant for
    # testing); neither is solid, so `clip` puts a player-clip box around it.
    for mo in layout.models:
        a = areas[mo.area]
        z = a.floor + mo.z
        ents.append(entity({"classname": "env_sprite", "targetname": f"mdl_{mo.name}",
                            "model": mo.model, "origin": f"{mo.pos[0]} {mo.pos[1]} {z}",
                            "angles": f"0 {mo.yaw} 0", "spawnflags": "1", "framerate": "1",
                            "scale": "1", "rendermode": "0", "renderamt": "255"}))  # fmt: skip
        if mo.clip:  # from the floor up, also when the model's origin is raised to stand on it
            w, d, h = mo.clip
            lo_c = (mo.pos[0] - w // 2, mo.pos[1] - d // 2, a.floor)
            world.brushes.append(
                box_brush(lo_c, (lo_c[0] + w, lo_c[1] + d, a.floor + h), tex["clip"])
            )

    # Room acoustics: an env_sound per area (explicit room type, or by size with `sounds`).
    wet = {w.area for w in layout.water}
    for a in areas.values():
        if a.sound is None and not layout.sounds:
            continue
        rt = a.sound if a.sound is not None else _room_type(a, a.name in wet)
        x0, y0, x1, y1 = a.rect
        radius = int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 2)
        origin = f"{(x0 + x1) // 2} {(y0 + y1) // 2} {a.floor + 64}"
        ents.append(entity({"classname": "env_sound", "roomtype": str(rt), "radius": str(radius),
                            "origin": origin}))  # fmt: skip

    # Lights: sun for outdoor areas, a grid of point lights in indoor areas (zone colour).
    if outdoor:
        sun = layout.sky.get("sun", {})
        r, g, bl = sun.get("color", [255, 240, 215])
        a = outdoor[0]
        ents.append(
            entity(
                {
                    "classname": "light_environment",
                    "origin": f"{(a.rect[0] + a.rect[2]) // 2} {(a.rect[1] + a.rect[3]) // 2} "
                    f"{a.top - 32}",
                    "_light": f"{r} {g} {bl} {sun.get('brightness', 280)}",
                    "pitch": str(sun.get("pitch", -50)),
                    "angles": f"0 {sun.get('yaw', 135)} 0",
                    "_diffuse_light": f"{r} {g} {bl} {sun.get('ambient', 90)}",
                }
            )
        )

    def light_cfg(a: Area) -> tuple[dict[str, Any], str]:
        lcfg = {**layout.lights, **((layout.zones.get(a.zone) or {}).get("light") or {}),
                **(a.light or {})}  # fmt: skip
        lr, lg, lb = lcfg.get("color", [255, 236, 210])
        return lcfg, f"{lr} {lg} {lb} {lcfg.get('brightness', 220)}"

    for a in areas.values():
        if a.outdoor:
            continue
        lcfg, light = light_cfg(a)
        if lcfg.get("off"):
            continue
        spacing = int(lcfg.get("spacing", 384))
        x0, y0, x1, y1 = a.rect
        nx, ny = max(1, round((x1 - x0) / spacing)), max(1, round((y1 - y0) / spacing))
        pts = [(x0 + (x1 - x0) * (2 * i + 1) // (2 * nx), y0 + (y1 - y0) * (2 * j + 1) // (2 * ny))
               for i in range(nx) for j in range(ny)]  # fmt: skip
        if a.poly is not None:  # a polygon area: only the lights over its floor
            pts = [p for p in pts if a.inside(*p, margin=32)]
            if not pts:
                cx, cy = a.centroid()
                pts = [(int(cx) // 8 * 8, int(cy) // 8 * 8)]
        for px, py in pts:
            ents.append(entity({"classname": "light", "origin": f"{px} {py} {a.top - 24}",
                                "_light": light}))  # fmt: skip
    for br in layout.bridges:
        # the deck shades the floor under it (also from the sun): lights under it along its length
        a = areas[br.area]
        lcfg, light = light_cfg(a)
        d_lo, d_hi = _bridge_boxes(br, a)[0]
        i = 0 if br.axis == "x" else 1
        n = max(1, round((d_hi[i] - d_lo[i]) / int(lcfg.get("spacing", 384))))
        for k in range(n):
            p = [(d_lo[0] + d_hi[0]) // 2, (d_lo[1] + d_hi[1]) // 2]
            p[i] = d_lo[i] + (d_hi[i] - d_lo[i]) * (2 * k + 1) // (2 * n)
            if a.inside(*p, margin=32):
                ents.append(entity({"classname": "light", "origin": f"{p[0]} {p[1]} {d_lo[2] - 16}",
                                    "_light": light}))  # fmt: skip

    # Door lights: both sides of a lit opening, DOOR_LIGHT_OUT into each area, under the
    # opening's top - a chokepoint should read clearly from both sides.
    for d in layout.doors:
        if not d.light:
            continue
        (o_lo, o_hi) = voids[d.name]
        through = 1 if (o_hi[0] - o_lo[0]) > (o_hi[1] - o_lo[1]) else 0  # the wall's thin axis
        for name, sign in zip(d.between, (-1, 1), strict=True):
            a = areas[name]
            p = [(o_lo[0] + o_hi[0]) // 2, (o_lo[1] + o_hi[1]) // 2]
            for s_ in (sign, -sign):  # the side of the opening that lies in this area
                q = list(p)
                q[through] = (o_lo[through] if s_ < 0 else o_hi[through]) + s_ * DOOR_LIGHT_OUT
                if a.inside(*q):
                    break
            else:
                continue
            z = min(o_hi[2], a.top) - 16
            ents.append(entity({"classname": "light", "origin": f"{q[0]} {q[1]} {z}",
                                "_light": light_cfg(a)[1]}))  # fmt: skip

    # Spawns face the middle of the map.
    centre = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    for team, cls in (("T", "info_player_deathmatch"), ("CT", "info_player_start")):
        sp = layout.spawns[team]
        blocked = [  # cover a player would stand in (bottom lower than a standing hull)
            ((c.pos[0] - c.size[0] // 2, c.pos[1] - c.size[1] // 2),
             (c.pos[0] + c.size[0] // 2, c.pos[1] + c.size[1] // 2))
            for c in layout.cover if c.area == sp["area"] and c.z < 80
        ]  # fmt: skip
        for p in _spawn_points(
            areas[sp["area"]], sp["count"], centre, sp.get("offset", (0, 0)), blocked
        ):
            origin, angles = p.split("|")
            ents.append(entity({"classname": cls, "origin": origin, "angles": angles}))

    # Bomb sites and buy zones are trigger brushes (tool texture, stripped by the compiler).
    for letter, area_name in sorted(layout.sites.items()):
        a = areas[area_name]
        x0, y0, x1, y1 = a.rect
        ents.append(
            entity(
                {"classname": "func_bomb_target", "targetname": f"site_{letter}"},
                [
                    box_brush(
                        (x0 + 32, y0 + 32, a.floor),
                        (x1 - 32, y1 - 32, a.floor + 128),
                        tex["trigger"],
                    )
                ],
            )
        )
    if layout.buyzones:
        for team, num in (("T", "1"), ("CT", "2")):
            a = areas[layout.spawns[team]["area"]]
            x0, y0, x1, y1 = a.rect
            ents.append(
                entity(
                    {"classname": "func_buyzone", "team": num},
                    [box_brush((x0, y0, a.floor), (x1, y1, a.floor + 128), tex["trigger"])],
                )
            )

    # Weapons on the floor and map rules.
    for wp in layout.weapons:
        item = wp["item"]
        code = ARMOURY_ITEMS.get(str(item).lower(), item)
        if not isinstance(code, int):
            raise SpecError(f"weapon {item!r}: unknown item (one of {sorted(ARMOURY_ITEMS)})")
        a = areas[wp["area"]]
        origin = f"{wp['pos'][0]} {wp['pos'][1]} {a.floor + 16}"
        count = str(int(wp.get("count", 1)))
        ents.append(entity({"classname": "armoury_entity", "item": str(code), "count": count,
                            "origin": origin}))  # fmt: skip
    if layout.map_parameters:
        mp = layout.map_parameters
        buying = BUYING.get(str(mp.get("buying", "both")).lower())
        if buying is None:
            raise SpecError(f"map_parameters.buying: one of {sorted(BUYING)}")
        props = {"classname": "info_map_parameters", "buying": str(buying),
                 "origin": f"{int(lo[0]) + 32} {int(lo[1]) + 32} {int(lo[2]) + 32}"}  # fmt: skip
        if "bombradius" in mp:
            props["bombradius"] = str(int(mp["bombradius"]))
        ents.append(entity(props))

    stats = {
        "brushes": len(world.brushes) + len(detail),
        "shell_brushes": n_shell,
        "areas": len(areas),
        "doors": len(layout.doors),
        "entities": len(ents),
    }
    mf = MapFile(entities=ents)
    used = {f.texture for b in mf.brushes() for f in b.faces}
    rad = "".join(
        f"{name} {' '.join(str(v) for v in vals)}\n"
        for name, vals in sorted(layout.texlights.items())
        if name in used
    )
    if breakables:
        stats["breakables"] = len(breakables)
    return Generated(mapfile=mf, voids=voids, stats=stats, rad=rad)


def _spawn_points(
    area: Area,
    count: int,
    facing: tuple[float, float],
    offset: tuple[int, int] = (0, 0),
    blocked: list[tuple[tuple[int, int], tuple[int, int]]] = (),
) -> list[str]:
    x0, y0, x1, y1 = area.rect
    margin, spacing = 48, 64
    cols = max(1, (x1 - x0 - 2 * margin) // spacing + 1)
    rows = max(1, (y1 - y0 - 2 * margin) // spacing + 1)
    if cols * rows < count:
        raise SpecError(f"spawn area {area.name} fits {cols * rows} spawns, needs {count}")
    pts = []
    cxm, cym = (x0 + x1) / 2 + offset[0], (y0 + y1) / 2 + offset[1]
    grid = sorted(
        (
            (x0 + margin + c * spacing, y0 + margin + r * spacing)
            for r in range(rows)
            for c in range(cols)
            if area.inside(x0 + margin + c * spacing, y0 + margin + r * spacing, margin=32)
            and not any(  # 16 (half hull) + 16 free around a spawn
                lo[0] - 32 < x0 + margin + c * spacing < hi[0] + 32
                and lo[1] - 32 < y0 + margin + r * spacing < hi[1] + 32
                for lo, hi in blocked
            )
        ),
        key=lambda p: (p[0] - cxm) ** 2 + (p[1] - cym) ** 2,
    )  # fill from the middle of the area outwards
    if len(grid) < count:
        raise SpecError(f"spawn area {area.name} fits {len(grid)} spawns, needs {count}")
    yaw = math.degrees(math.atan2(facing[1] - cym, facing[0] - cxm))
    for x, y in grid[:count]:
        # hull origin 36 above the feet + ~8 units clearance off the floor (TWHL)
        pts.append(f"{x} {y} {area.floor + 44}|0 {yaw:.0f} 0")
    return pts


def brushes_of(g: Generated) -> list[Brush]:
    return g.mapfile.brushes()
