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

import math
from dataclasses import dataclass

import numpy as np

from mapforge.generator.spec import Area, Door, Layout, SpecError
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


def _solid_cells(
    voids: list[Box], sky_over: list[Area], shell: Box, owners: list[tuple[Area, int]]
) -> tuple[list, np.ndarray]:
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


def _face_textures(lo: tuple, hi: tuple, voids: list[tuple[Box, Area]], tex_of) -> dict[str, str]:
    """Per side of a shell box: the texture of the area it faces (largest touching overlap)."""
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
    owners = [(a, zone_names.index(a.zone) + 1 if a.zone else 0) for a in areas.values()]
    (xs, ys, zs), label = _solid_cells(list(voids.values()), outdoor, shell, owners)
    door_area = {d.name: areas[d.between[0]] for d in layout.doors}
    void_areas = [(b, areas.get(n) or door_area[n]) for n, b in voids.items()]

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
        elif layout.zones:
            t = _face_textures(b_lo, b_hi, void_areas, tex_of)
        else:
            t = surf(None)
        world.brushes.append(box_brush(b_lo, b_hi, t))
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
    for c in layout.cover:
        a = areas[c.area]
        (px, py), (w, d, h) = c.pos, c.size
        z0 = a.floor + c.z
        brush = box_brush(
            (px - w // 2, py - d // 2, z0),
            (px + w // 2, py + d // 2, z0 + h),
            c.texture or tex_of(a)["cover"],
        )
        inner.append((brush, c.z + h))
    ents = [world]
    detail = [b for b, top in inner if layout.detail and top <= DETAIL_MAX_H]
    world.brushes += walls + [b for b, top in inner if not (layout.detail and top <= DETAIL_MAX_H)]
    if detail:
        ents.append(entity({"classname": "func_detail", "zhlt_detaillevel": "1"}, detail))
    world.brushes += _stair_clips(layout, tex["clip"])

    # Openings: glass panes and door leaves fill the opening's box.
    for d in layout.doors:
        (o_lo, o_hi) = voids[d.name]
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
    for a in areas.values():
        if a.outdoor:
            continue
        lcfg = {**layout.lights, **((layout.zones.get(a.zone) or {}).get("light") or {})}
        spacing = int(lcfg.get("spacing", 384))
        lr, lg, lb = lcfg.get("color", [255, 236, 210])
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
        for p in _spawn_points(areas[sp["area"]], sp["count"], centre, sp.get("offset", (0, 0))):
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
    return Generated(mapfile=MapFile(entities=ents), voids=voids, stats=stats)


def _spawn_points(
    area: Area, count: int, facing: tuple[float, float], offset: tuple[int, int] = (0, 0)
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
        ),
        key=lambda p: (p[0] - cxm) ** 2 + (p[1] - cym) ** 2,
    )  # fill from the middle of the area outwards
    yaw = math.degrees(math.atan2(facing[1] - cym, facing[0] - cxm))
    for x, y in grid[:count]:
        # hull origin 36 above the feet + ~8 units clearance off the floor (TWHL)
        pts.append(f"{x} {y} {area.floor + 44}|0 {yaw:.0f} 0")
    return pts


def brushes_of(g: Generated) -> list[Brush]:
    return g.mapfile.brushes()
