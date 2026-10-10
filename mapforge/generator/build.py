"""Layout spec -> Valve 220 .map.

Geometry: the spec only describes empty space (areas + doors). Everything else inside an
outer shell (the bounding box of all empty space, grown by `wall`) is solid: the coordinate
axes are compressed to the boundaries that occur, each resulting cell is marked empty or
solid, and solid cells are greedily merged into boxes. The map is therefore sealed by
construction (no leaks) and every vertex lies on the spec's grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from mapforge.generator.spec import Area, Door, Layout, SpecError
from mapforge.mapfile.parser import Brush, MapFile
from mapforge.mapfile.writer import box_brush, entity

WORLD_LIMIT = 4096
EMPTY, SOLID, SKY = 0, 1, 2

Box = tuple[tuple[int, int, int], tuple[int, int, int]]


@dataclass
class Generated:
    mapfile: MapFile
    voids: dict[str, Box]  # area/door name -> empty box
    stats: dict[str, int]


def door_box(door: Door, areas: dict[str, Area], wall: int) -> Box:
    """The empty box cut through the wall between the two areas of a door.

    The areas must be exactly `wall` units apart on one axis and overlap by at least the door
    width on the other; the door is centred on that overlap (+ offset).
    """
    a, b = (areas[n] for n in door.between)
    ax0, ay0, ax1, ay1 = a.rect
    bx0, by0, bx1, by1 = b.rect
    floor = max(a.floor, b.floor)
    height = door.height or min(a.top, b.top) - floor
    if min(a.top, b.top) < floor + height:
        raise SpecError(f"door {door.name}: taller than the lower of its two areas")
    # (gap between the areas, axis the door goes through, wall start, wall end)
    sides = (
        (bx0 - ax1, "x", ax1, bx0),  # b east of a
        (ax0 - bx1, "x", bx1, ax0),  # b west of a
        (by0 - ay1, "y", ay1, by0),  # b north of a
        (ay0 - by1, "y", by1, ay0),  # b south of a
    )
    for gap, axis, w_lo, w_hi in sides:
        s0, s1 = (max(ay0, by0), min(ay1, by1)) if axis == "x" else (max(ax0, bx0), min(ax1, bx1))
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
        f"(they must be exactly {wall} units apart with >= {door.width} units of overlap)"
    )


def _solid_cells(voids: list[Box], sky_over: list[Area], shell: Box) -> tuple[list, np.ndarray]:
    (sx0, sy0, sz0), (sx1, sy1, sz1) = shell
    axes = []
    for i, (lo, hi) in enumerate(((sx0, sx1), (sy0, sy1), (sz0, sz1))):
        cuts = {lo, hi}
        for b in voids:
            cuts |= {b[0][i], b[1][i]}
        for a in sky_over:  # split at outdoor area edges so sky cells line up with them
            if i < 2:
                cuts |= {a.rect[i], a.rect[i + 2]}
            else:
                cuts.add(a.top)
        axes.append(sorted(c for c in cuts if lo <= c <= hi))
    xs, ys, zs = axes
    cx = (np.array(xs[:-1]) + np.array(xs[1:])) / 2
    cy = (np.array(ys[:-1]) + np.array(ys[1:])) / 2
    cz = (np.array(zs[:-1]) + np.array(zs[1:])) / 2
    gx, gy, gz = np.meshgrid(cx, cy, cz, indexing="ij")
    label = np.full(gx.shape, SOLID, dtype=np.int8)
    for a in sky_over:
        x0, y0, x1, y1 = a.rect
        label[(gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > a.top)] = SKY
    for (x0, y0, z0), (x1, y1, z1) in voids:
        label[(gx > x0) & (gx < x1) & (gy > y0) & (gy < y1) & (gz > z0) & (gz < z1)] = EMPTY
    return axes, label


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


def _stair_boxes(layout: Layout) -> list[Box]:
    out = []
    for st in layout.stairs:
        a = layout.areas[st.area]
        x0, y0, x1, y1 = a.rect
        n = st.rise // st.step
        along = st.axis[1]
        sign = 1 if st.axis[0] == "+" else -1
        lo, hi = (x0, x1) if along == "x" else (y0, y1)
        begin = lo + st.start if sign > 0 else hi - st.start
        end = hi if sign > 0 else lo
        for i in range(1, n + 1):
            # step i reaches from its front edge to the far end of the area (a solid flight)
            front = begin + sign * (i - 1) * st.run
            s0, s1 = sorted((front, end))
            z1 = a.floor + i * st.step
            if along == "x":
                out.append(((s0, y0, a.floor), (s1, y1, z1)))
            else:
                out.append(((x0, s0, a.floor), (x1, s1, z1)))
    return out


def _spawn_points(area: Area, count: int, facing: tuple[float, float]) -> list[str]:
    x0, y0, x1, y1 = area.rect
    margin, spacing = 48, 64
    cols = max(1, (x1 - x0 - 2 * margin) // spacing + 1)
    rows = max(1, (y1 - y0 - 2 * margin) // spacing + 1)
    if cols * rows < count:
        raise SpecError(f"spawn area {area.name} fits {cols * rows} spawns, needs {count}")
    pts = []
    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
    grid = sorted(
        (
            (x0 + margin + c * spacing, y0 + margin + r * spacing)
            for r in range(rows)
            for c in range(cols)
        ),
        key=lambda p: (p[0] - cxm) ** 2 + (p[1] - cym) ** 2,
    )  # fill from the middle of the area outwards
    yaw = math.degrees(math.atan2(facing[1] - cym, facing[0] - cxm))
    for x, y in grid[:count]:
        # hull origin 36 above the feet + ~8 units clearance off the floor (TWHL)
        pts.append(f"{x} {y} {area.floor + 44}|0 {yaw:.0f} 0")
    return pts


def generate(layout: Layout) -> Generated:
    tex = layout.textures
    areas = layout.areas
    voids: dict[str, Box] = {
        a.name: ((a.rect[0], a.rect[1], a.floor), (a.rect[2], a.rect[3], a.top))
        for a in areas.values()
    }
    for d in layout.doors:
        voids[d.name] = door_box(d, areas, layout.wall)
    lo = np.min([b[0] for b in voids.values()], axis=0) - layout.wall
    hi = np.max([b[1] for b in voids.values()], axis=0) + layout.wall
    if np.any(np.abs(lo) > WORLD_LIMIT) or np.any(np.abs(hi) > WORLD_LIMIT):
        raise SpecError(f"map exceeds ±{WORLD_LIMIT} units: {lo.tolist()} .. {hi.tolist()}")
    shell: Box = (tuple(int(v) for v in lo), tuple(int(v) for v in hi))
    outdoor = [a for a in areas.values() if a.outdoor]
    (xs, ys, zs), label = _solid_cells(list(voids.values()), outdoor, shell)

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
    surf = {"top": tex["floor"], "bottom": tex["ceiling"], "side": tex["wall"]}
    for lab, si, sj, sk in _greedy_boxes(label):
        b_lo = (xs[si.start], ys[sj.start], zs[sk.start])
        b_hi = (xs[si.stop], ys[sj.stop], zs[sk.stop])
        world.brushes.append(box_brush(b_lo, b_hi, tex["sky"] if lab == SKY else surf))
    n_shell = len(world.brushes)
    for b_lo, b_hi in _stair_boxes(layout):
        world.brushes.append(box_brush(b_lo, b_hi, surf))
    for c in layout.cover:
        a = areas[c.area]
        (px, py), (w, d, h) = c.pos, c.size
        world.brushes.append(
            box_brush(
                (px - w // 2, py - d // 2, a.floor),
                (px + w // 2, py + d // 2, a.floor + h),
                tex["cover"],
            )
        )
    ents = [world]

    # Lights: sun for outdoor areas, a grid of point lights in indoor areas (and doors).
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
    lcfg = layout.lights
    spacing = int(lcfg.get("spacing", 384))
    lr, lg, lb = lcfg.get("color", [255, 236, 210])
    for a in areas.values():
        if a.outdoor:
            continue
        x0, y0, x1, y1 = a.rect
        nx, ny = max(1, round((x1 - x0) / spacing)), max(1, round((y1 - y0) / spacing))
        for i in range(nx):
            for j in range(ny):
                ents.append(
                    entity(
                        {
                            "classname": "light",
                            "origin": f"{x0 + (x1 - x0) * (2 * i + 1) // (2 * nx)} "
                            f"{y0 + (y1 - y0) * (2 * j + 1) // (2 * ny)} {a.top - 24}",
                            "_light": f"{lr} {lg} {lb} {lcfg.get('brightness', 220)}",
                        }
                    )
                )

    # Spawns face the middle of the map.
    centre = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    for team, cls in (("T", "info_player_deathmatch"), ("CT", "info_player_start")):
        sp = layout.spawns[team]
        for p in _spawn_points(areas[sp["area"]], sp["count"], centre):
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

    stats = {
        "brushes": len(world.brushes),
        "shell_brushes": n_shell,
        "areas": len(areas),
        "doors": len(layout.doors),
        "entities": len(ents),
    }
    return Generated(mapfile=MapFile(entities=ents), voids=voids, stats=stats)


def brushes_of(g: Generated) -> list[Brush]:
    return g.mapfile.brushes()
