"""Layout spec (maps/<map>/layout.yaml): parsing and checks. Format: docs/LAYOUT_SPEC.md."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mapforge.generator.props import PROPS
from mapforge.generator.props import check as check_prop


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class Area:
    name: str
    rect: tuple[int, int, int, int]  # x0, y0, x1, y1
    floor: int
    height: int
    outdoor: bool = False
    role: str = "room"
    zone: str | None = None  # texture/light set from Layout.zones (identity, callouts)
    light: dict[str, Any] | None = None  # point-light override for this area (spacing/colour/...)
    sound: int | None = None  # env_sound room type (reverb); None = automatic by size if enabled
    # convex floor plan (counter-clockwise grid vertices) inside `rect` = its bounding box; the
    # rest of the box is solid (angled walls at any grid angle). None = the whole rect
    poly: tuple[tuple[int, int], ...] | None = None

    @property
    def top(self) -> int:
        return self.floor + self.height

    def side_span(self, side: str) -> tuple[int, int] | None:
        """The open stretch of the bounding-box wall on `side` (+x -x +y -y), along that wall:
        the whole side for a rect, the polygon edge lying on it for a poly (None: only a corner
        or nothing touches it, so no door can go there)."""
        x0, y0, x1, y1 = self.rect
        axis = 0 if side[1] == "x" else 1
        at = (x1 if side[0] == "+" else x0) if axis == 0 else (y1 if side[0] == "+" else y0)
        if self.poly is None:
            return (y0, y1) if axis == 0 else (x0, x1)
        on = sorted(p[1 - axis] for p in self.poly if p[axis] == at)
        return (on[0], on[-1]) if len(on) >= 2 else None

    def inside(self, x: float, y: float, margin: float = 0) -> bool:
        """(x, y) lies in the floor plan, at least `margin` from every wall."""
        x0, y0, x1, y1 = self.rect
        if not (x0 + margin <= x <= x1 - margin and y0 + margin <= y <= y1 - margin):
            return False
        pts = self.poly or ()
        for (px, py), (qx, qy) in zip(pts, pts[1:] + pts[:1], strict=True):
            ex, ey = qx - px, qy - py  # counter-clockwise: the inside is on the left
            if (ex * (y - py) - ey * (x - px)) / math.hypot(ex, ey) < margin:
                return False
        return True

    def centroid(self) -> tuple[float, float]:
        if self.poly is None:
            x0, y0, x1, y1 = self.rect
            return (x0 + x1) / 2, (y0 + y1) / 2
        n = len(self.poly)
        return sum(p[0] for p in self.poly) / n, sum(p[1] for p in self.poly) / n


DOOR_KINDS = ("door", "window", "vent")
GATES = ("none", "sliding", "rotating")


@dataclass(frozen=True)
class Door:
    """An opening in the wall between two areas. kind: door (walk through), window (a hole
    from `sill` up: see/shoot through, not a route), vent (crouch-height route)."""

    name: str
    between: tuple[str, str]
    width: int
    height: int | None = None
    offset: int = 0
    kind: str = "door"
    sill: int = 0  # bottom of the opening above the higher of the two floors
    glass: bool = False  # breakable glass pane in the opening (func_breakable)
    gate: str = "none"  # an openable door leaf in the opening (func_door / func_door_rotating)
    arch: bool = False  # rounded top corners (a plain door; full width stays >= 80 high)

    @property
    def walkable(self) -> bool:
        return self.kind != "window"


@dataclass(frozen=True)
class Stairs:
    name: str
    area: str
    axis: str  # +x -x +y -y: direction of climbing
    rise: int
    step: int = 16
    run: int = 32
    start: int = 0  # distance from the area edge where the first step begins
    clip: bool = False  # player-clip ramp over the steps: smooth movement, no step bobbing


@dataclass(frozen=True)
class Ramp:
    """Sloped floor across the whole area: rises `rise` over `length` from `start` along `axis`;
    after it the rest of the area is raised by `rise` (like Stairs). Slope <= 45 degrees."""

    name: str
    area: str
    axis: str
    rise: int
    length: int
    start: int = 0


CORNERS = ("ne", "nw", "se", "sw")


@dataclass(frozen=True)
class Wedge:
    """Solid triangular prism filling a corner of an area: its hypotenuse is an angled wall.
    Two opposite wedges turn a rectangle into a diagonal corridor; one chamfers a room."""

    name: str
    area: str
    corner: str
    size: tuple[int, int]  # legs along x and y from the corner (equal = 45 degrees)
    height: int | None = None  # default: floor to ceiling


@dataclass(frozen=True)
class Ladder:
    """A climbable ladder on one wall of an area, from the floor up `height` units."""

    name: str
    area: str
    wall: str  # +x -x +y -y: the wall it stands against
    pos: int = 0  # centre along the wall, from the wall's middle
    width: int = 32
    height: int = 128


@dataclass(frozen=True)
class Cover:
    """A solid box inside an area: crate, wall, pillar; with z > 0 a platform, bridge or a crate
    stacked on another (boost spot)."""

    name: str
    area: str
    pos: tuple[int, int]
    size: tuple[int, int, int]
    z: int = 0  # bottom above the area floor
    texture: str | None = None  # default: textures.cover (or the area zone's cover)
    shape: str = "box"  # box | octagon (chamfered) | cylinder (faceted: barrels, round pillars)
    breakable: str | None = None  # wood | metal | glass | concrete: a func_breakable
    preset: str | None = None  # a preset or themed prop (mapforge.generator.props.PROPS)


SHAPES = ("box", "octagon", "cylinder")
# Default footprint [w, d, h] of each preset / themed prop (`size` may override it).
PRESETS = {name: p.size for name, p in PROPS.items()}
MATERIALS = {"glass": 0, "wood": 1, "metal": 2, "concrete": 4}  # func_breakable "material"


@dataclass(frozen=True)
class Hatch:
    """A vertical opening between an area and the one directly above it (stacked levels):
    a hole through the slab, optionally with a ladder up through it."""

    name: str
    lower: str
    upper: str
    rect: tuple[int, int, int, int]
    ladder: str | None = None  # +x -x +y -y: the hatch side the ladder stands on; None = drop only
    lift: str | None = None  # auto (func_plat: step on below) | button (func_button on both floors)


@dataclass(frozen=True)
class Water:
    """A water volume (texture !WATER: liquid contents) in an area, from the floor up `depth`."""

    name: str
    area: str
    rect: tuple[int, int, int, int]
    depth: int


@dataclass(frozen=True)
class Ambient:
    """A looping ambient sound (ambient_generic) in an area: a path under sound/ that the game
    ships (cstrike or valve, e.g. ambience/industrial1.wav)."""

    name: str
    area: str
    sound: str
    pos: tuple[int, int] | None = None  # default: the area's middle
    z: int = 64  # above the area floor
    volume: int = 6  # 1-10 (the entity's "health")
    radius: str = "medium"  # small | medium | large | everywhere


AMBIENT_RADIUS = {"everywhere": 1, "small": 2, "medium": 4, "large": 8}  # spawnflags


@dataclass(frozen=True)
class Model:
    """A model the game ships (models/*.mdl in cstrike or valve), shown with env_sprite: not
    solid on its own; `clip` [w, d, h] adds a player-clip box around it so it blocks."""

    name: str
    area: str
    model: str  # e.g. models/conveyor1.mdl
    pos: tuple[int, int]
    z: int = 0  # above the area floor
    yaw: int = 0
    clip: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class Spot:
    """A spot light (light_spot) in an area."""

    name: str
    area: str
    pos: tuple[int, int]
    z: int  # above the area floor
    pitch: int = -90  # -90 = straight down
    yaw: int = 0
    cone: tuple[int, int] = (30, 45)  # inner, outer half-angle in degrees
    brightness: int = 300
    color: tuple[int, int, int] = (255, 240, 220)


@dataclass(frozen=True)
class Bridge:
    """A walkable deck across an area from wall to wall along `axis`, its top `z` above the
    floor, with railings on both long sides: one level crossing over another in a tall room."""

    name: str
    area: str
    axis: str  # x | y: the direction the bridge runs (it spans the whole area that way)
    z: int
    width: int = 96
    pos: int = 0  # centreline offset across the bridge, from the area's middle
    thickness: int = 16
    rail: int = 40  # railing height above the deck (0 = none)


BRIDGE_CLEARANCE = 80  # under the deck and over it: a standing player (72) + margin


@dataclass
class Layout:
    name: str
    grid: int
    wall: int
    textures: dict[str, str]
    areas: dict[str, Area]
    doors: list[Door]
    stairs: list[Stairs]
    cover: list[Cover]
    sites: dict[str, str]  # site letter -> area name
    spawns: dict[str, dict[str, Any]]  # T/CT -> {area, count}
    buyzones: bool = True
    sky: dict[str, Any] = field(default_factory=dict)
    lights: dict[str, Any] = field(default_factory=dict)
    ramps: list[Ramp] = field(default_factory=list)
    wedges: list[Wedge] = field(default_factory=list)
    ladders: list[Ladder] = field(default_factory=list)
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> textures + light
    weapons: list[dict[str, Any]] = field(default_factory=list)  # armoury_entity
    map_parameters: dict[str, Any] = field(default_factory=dict)  # info_map_parameters
    detail: bool = False  # cover/wedges/ramps as func_detail (no vis splits; SDHLT)
    hatches: list[Hatch] = field(default_factory=list)
    water: list[Water] = field(default_factory=list)
    spots: list[Spot] = field(default_factory=list)
    texlights: dict[str, list[int]] = field(default_factory=dict)  # texture -> [r, g, b, intensity]
    sounds: bool = False  # env_sound per area: reverb from its size (unless area.sound is set)
    bridges: list[Bridge] = field(default_factory=list)
    ambient: list[Ambient] = field(default_factory=list)
    models: list[Model] = field(default_factory=list)


DEFAULT_TEXTURES = {
    "floor": "DEV_FLOOR",
    "wall": "DEV_WALL",
    "ceiling": "DEV_CEIL",
    "cover": "DEV_CRATE",
    "sky": "SKY",
    "trigger": "AAATRIGGER",
    "clip": "CLIP",  # tool textures: names the compiler treats specially
    "origin": "ORIGIN",
    "glass": "DEV_GLASS",
    "door": "DEV_DOOR",
    "ladder": "DEV_LADDER",
    "water": "!WATER",  # '!' = liquid contents for the compiler
}

DEFAULT_TEXLIGHTS = {"DEV_LIGHT": [255, 236, 200, 900], "DEV_LIGHT_BLUE": [190, 215, 255, 900]}


def expand_diagonals(data: dict[str, Any], grid: int) -> dict[str, Any]:
    """`diagonals:` -> an area + two wedges each: a 45° corridor of at least `width` across a
    square `rect`. dir nw: from the south-east corner to the north-west one (wedges ne + sw);
    dir ne: from south-west to north-east (wedges nw + se). Doors go on the free wall ends."""
    diags = data.get("diagonals") or []
    if not diags:
        return data
    data = dict(data)
    areas, wedges = list(data.get("areas", [])), list(data.get("wedges", []))
    for d in diags:
        x0, y0, x1, y1 = _ints(d.get("rect"), 4, f"diagonal {d.get('name')}.rect")
        side = x1 - x0
        if y1 - y0 != side:
            raise SpecError(f"diagonal {d['name']}: rect must be square")
        width = int(d["width"])
        leg = (side - math.ceil(width / math.sqrt(2) / grid) * grid) // grid * grid
        if leg <= 0:
            raise SpecError(f"diagonal {d['name']}: width {width} does not fit in {side}")
        area = {k: v for k, v in d.items() if k not in ("dir", "width")}
        area.setdefault("role", "corridor")
        areas.append(area)
        corners = ("ne", "sw") if d.get("dir", "nw") == "nw" else ("nw", "se")
        for c in corners:
            wedges.append({"name": f"{d['name']}_{c}", "area": d["name"], "corner": c,
                           "size": [leg, leg]})  # fmt: skip
    data["areas"], data["wedges"] = areas, wedges
    return data


def corridor_poly(c: dict[str, Any], grid: int) -> tuple[list[list[int]], str, int, int]:
    """An angled corridor's floor plan: a parallelogram from `from` to `to` (the middles of its
    two ends) whose ends are square to the main axis, so they sit on ordinary walls and take
    ordinary doors. The end width is the corridor `width` measured across the slant, rounded up
    to the grid. Returns (polygon, main axis x|y, half end width, length along the axis)."""
    fx, fy = _ints(c.get("from"), 2, f"corridor {c.get('name')}.from")
    tx, ty = _ints(c.get("to"), 2, f"corridor {c.get('name')}.to")
    if any(v % grid for v in (fx, fy, tx, ty)):
        raise SpecError(f"corridor {c['name']}: from/to must be on the {grid}-unit grid")
    along = "y" if abs(ty - fy) >= abs(tx - fx) else "x"
    length, drift = (abs(ty - fy), abs(tx - fx)) if along == "y" else (abs(tx - fx), abs(ty - fy))
    if length == 0:
        raise SpecError(f"corridor {c['name']}: from and to are the same point")
    width = int(c["width"])
    half = math.ceil(width / 2 * math.hypot(length, drift) / length / grid) * grid
    if along == "y":
        poly = [[fx - half, fy], [fx + half, fy], [tx + half, ty], [tx - half, ty]]
    else:
        poly = [[fx, fy - half], [tx, ty - half], [tx, ty + half], [fx, fy + half]]
    return poly, along, half, length


def corridor_chain(
    points: list[list[int]],
    name: str,
    grid: int = 16,
    width: int = 128,
    height: int = 192,
    first_plain: bool = False,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], int]], list[dict[str, Any]]]:
    """A corridor through bends: a square knee room on every inner point and an angled stretch
    between them, its ends one wall from the knees. Returns (knees, [(stretch, half end width)],
    doors stretch <-> knee). Stretches are named <name>_1, _2, ... (with `first_plain` the first
    one is <name> itself, so a `corridors:` entry keeps its name), knees <name>_knee1, ..."""
    vs = [list(p) for p in points]
    n = len(vs) - 1
    seg_names = [name if first_plain and k == 0 else f"{name}_{k + 1}" for k in range(n)]
    # knee rooms: wide enough for the end of every stretch that meets them
    side = {i: 2 * (width // 2 // grid + 2) * grid for i in range(1, n)}
    for _ in range(3):  # the stretch ends depend on the knee sizes and the other way round
        cors = []
        for k in range(n):
            (ax, ay), (bx, by) = vs[k], vs[k + 1]
            along_y = abs(by - ay) >= abs(bx - ax)
            sgn = 1 if (by - ay if along_y else bx - ax) > 0 else -1
            fx, fy, tx, ty = ax, ay, bx, by
            if k > 0:  # start on the knee's wall (one wall away from it)
                off = sgn * (side[k] // 2 + 16)
                fy, fx = (ay + off, ax) if along_y else (ay, ax + off)
            if k < n - 1:
                off = sgn * (side[k + 1] // 2 + 16)
                ty, tx = (by - off, bx) if along_y else (by, bx - off)
            c = {"name": seg_names[k], "from": [fx, fy], "to": [tx, ty], "width": width,
                 "height": height}  # fmt: skip
            try:
                _, along, half, _ = corridor_poly(c, grid)
            except SpecError as exc:
                raise SpecError(f"{name}: bends too close together ({exc})") from exc
            if (along == "y") != along_y:  # moving the ends onto the knees tipped it past 45
                raise SpecError(f"{name}: stretch {k + 1} is too close to 45 degrees for its "
                                "knees; move the bend, or use `diagonals:`")  # fmt: skip
            cors.append((c, half))
        grown = False
        for k, (_, half) in enumerate(cors):
            for i in (k, k + 1):
                if i in side and side[i] < 2 * half + 2 * grid:
                    side[i], grown = 2 * half + 2 * grid, True
        if not grown:
            break
    knees = [
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
                doors.append({"name": f"d_{c['name']}_knee{i}", "between": [c["name"], knee],
                              "width": 2 * half})  # fmt: skip
    return knees, cors, doors


CARRY = ("zone", "light", "sound", "outdoor", "protected")  # corridor keys its pieces keep


def expand_corridors(data: dict[str, Any], grid: int) -> dict[str, Any]:
    """`corridors:` -> a polygon area each (any grid angle), plus a ramp along it with `rise`
    and the doors at both ends with `between: [from_area, to_area]`. `height` is the head room
    over the (sloped) floor, so a rising corridor is `rise` taller than that. With `between`,
    `floor` (at the `from` end) and `rise` default to the floors of the two areas it joins.
    `via: [[x, y], ...]` bends it: a knee room at every via point, the rise spread over the
    stretches by length; the end doors keep their names <name>_from / <name>_to."""
    cors = data.get("corridors") or []
    if not cors:
        return data
    data = dict(data)
    areas, ramps = list(data.get("areas", [])), list(data.get("ramps", []))
    doors = list(data.get("doors", []))
    floors = {a.get("name"): int(a.get("floor", 0)) for a in areas}
    skip = ("from", "to", "width", "rise", "between", "door_width", "via")

    def one(c: dict[str, Any], floor: int, rise: int, ends: dict[str, str]) -> None:
        poly, along, half, length = corridor_poly(c, grid)
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        area = {k: v for k, v in c.items() if k not in skip}
        area.update(rect=[min(xs), min(ys), max(xs), max(ys)], poly=poly,
                    floor=floor + min(rise, 0),
                    height=int(c.get("height", 192)) + abs(rise))  # fmt: skip
        area.setdefault("role", "corridor")
        areas.append(area)
        if rise:
            i = 1 if along == "y" else 0
            up = (c["to"][i] > c["from"][i]) == (rise > 0)  # uphill towards `to`
            ramps.append({"name": f"{c['name']}_ramp", "area": c["name"],
                          "axis": ("+" if up else "-") + along, "rise": abs(rise),
                          "length": length})  # fmt: skip
        for door, other in ends.items():
            doors.append({"name": door, "between": [other, c["name"]],
                          "width": int(c.get("door_width", 2 * half))})  # fmt: skip

    for c in cors:
        ends = list(c.get("between") or ())
        f0, f1 = (floors.get(n, 0) for n in ends) if len(ends) == 2 else (0, 0)
        floor = int(c.get("floor", f0))
        rise = int(c.get("rise", f1 - floor))
        names = dict(zip((f"{c['name']}_from", f"{c['name']}_to"), ends, strict=False))
        if not c.get("via"):
            one(c, floor, rise, names)
            continue
        pts = [list(_ints(p, 2, f"corridor {c['name']}.via"))
               for p in (c["from"], *c["via"], c["to"])]  # fmt: skip
        if any(v % grid for p in pts for v in p):
            raise SpecError(f"corridor {c['name']}: via points must be on the {grid}-unit grid")
        width, height = int(c["width"]), int(c.get("height", 192))
        knees, segs, inner = corridor_chain(pts, c["name"], grid, width, height, first_plain=True)
        dist = [0.0]
        for p, q in zip(pts, pts[1:], strict=False):
            dist.append(dist[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))

        def floor_at(i: int, dist=dist, floor=floor, rise=rise) -> int:  # rise spread by length
            return floor + round(rise * dist[i] / dist[-1] / grid) * grid

        carry = {k: c[k] for k in CARRY if k in c}
        for i, knee in enumerate(knees, 1):
            areas.append({**knee, **carry, "floor": floor_at(i)})
        for k, (seg, _) in enumerate(segs):
            seg = {**carry, **seg}
            if "door_width" in c:
                seg["door_width"] = c["door_width"]
            seg_ends = {}
            if k == 0 and ends:
                seg_ends[f"{c['name']}_from"] = ends[0]
            if k == len(segs) - 1 and len(ends) == 2:
                seg_ends[f"{c['name']}_to"] = ends[1]
            one(seg, floor_at(k), floor_at(k + 1) - floor_at(k), seg_ends)
        doors.extend(inner)
    data["areas"], data["ramps"], data["doors"] = areas, ramps, doors
    return data


def expand_macros(data: dict[str, Any], grid: int) -> dict[str, Any]:
    """All shorthand in a layout (diagonals, corridors) as plain areas, wedges, ramps, doors;
    polygon areas get their bounding box as `rect` (tools that read rects see that)."""
    data = expand_corridors(expand_diagonals(data, grid), grid)
    if any(a.get("poly") and not a.get("rect") for a in data.get("areas", [])):
        data = dict(data)
        data["areas"] = [
            {**a, "rect": [min(p[0] for p in a["poly"]), min(p[1] for p in a["poly"]),
                           max(p[0] for p in a["poly"]), max(p[1] for p in a["poly"])]}
            if a.get("poly") and not a.get("rect") else a
            for a in data["areas"]
        ]  # fmt: skip
    return data


def _convex_ccw(points: Any, grid: int, what: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise SpecError(f"{what}: a polygon needs >= 3 points")
    pts = [_ints(p, 2, what) for p in points]
    if any(v % grid for p in pts for v in p):
        raise SpecError(f"{what}: vertices must be on the {grid}-unit grid")
    area2 = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1], strict=True))
    if area2 < 0:
        pts.reverse()
    n = len(pts)
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        if (bx - ax) * (cy - by) - (by - ay) * (cx - bx) <= 0:
            raise SpecError(f"{what}: polygon must be convex without collinear points")
    return tuple(pts)


def _ints(v: Any, n: int, what: str) -> tuple[int, ...]:
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(isinstance(x, int) for x in v):
        raise SpecError(f"{what}: expected {n} integers, got {v!r}")
    return tuple(v)


def parse_layout(data: dict[str, Any]) -> Layout:
    if not isinstance(data, dict) or "name" not in data:
        raise SpecError("layout needs a 'name'")
    grid = int(data.get("grid", 16))
    wall = int(data.get("wall", 16))
    data = expand_macros(data, grid)
    areas: dict[str, Area] = {}
    for a in data.get("areas", []):
        poly = None
        if a.get("poly") is not None:
            poly = _convex_ccw(a["poly"], grid, f"area {a.get('name')}.poly")
            bbox = (min(p[0] for p in poly), min(p[1] for p in poly),
                    max(p[0] for p in poly), max(p[1] for p in poly))  # fmt: skip
            if a.get("rect") is not None and tuple(a["rect"]) != bbox:
                raise SpecError(f"area {a.get('name')}: rect must be the bounding box of poly")
            if len(poly) == 4 and all(p[0] in bbox[::2] and p[1] in bbox[1::2] for p in poly):
                poly = None  # an axis-aligned rectangle: a plain area
            rect = bbox
        else:
            rect = _ints(a.get("rect"), 4, f"area {a.get('name')}.rect")
        area = Area(
            name=a["name"],
            rect=rect,
            floor=int(a.get("floor", 0)),
            height=int(a.get("height", 192)),
            outdoor=bool(a.get("outdoor", False)),
            role=a.get("role", "room"),
            zone=a.get("zone"),
            light=a.get("light"),
            sound=a.get("sound"),
            poly=poly,
        )
        if area.name in areas:
            raise SpecError(f"duplicate area {area.name}")
        x0, y0, x1, y1 = rect
        if not (x0 < x1 and y0 < y1):
            raise SpecError(f"area {area.name}: rect must have x0 < x1 and y0 < y1")
        for v in (*rect, area.floor, area.height):
            if v % grid:
                raise SpecError(f"area {area.name}: {v} is off the {grid}-unit grid")
        areas[area.name] = area

    def need(name: str, what: str) -> str:
        if name not in areas:
            raise SpecError(f"{what}: unknown area {name!r}")
        return name

    doors = []
    for d in data.get("doors", []):
        a, b = d.get("between", [None, None])
        doors.append(
            Door(
                name=d["name"],
                between=(need(a, d["name"]), need(b, d["name"])),
                width=int(d["width"]),
                height=d.get("height"),
                offset=int(d.get("offset", 0)),
                kind=str(d.get("kind", "door")),
                sill=int(d.get("sill", 0)),
                glass=bool(d.get("glass", False)),
                gate=str(d.get("gate", "none")),
                arch=bool(d.get("arch", False)),
            )
        )
        dr = doors[-1]
        if dr.kind not in DOOR_KINDS:
            raise SpecError(f"door {dr.name}: kind must be one of {DOOR_KINDS}")
        if dr.gate not in GATES:
            raise SpecError(f"door {dr.name}: gate must be one of {GATES}")
        if dr.sill % grid or dr.sill < 0:
            raise SpecError(f"door {dr.name}: sill {dr.sill} must be >= 0 on the {grid}-unit grid")
        if dr.kind == "window" and dr.sill < 64:
            raise SpecError(f"door {dr.name}: a window needs sill >= 64 (lower is a door/jump)")
        if dr.kind == "vent" and not (dr.height and 40 <= int(dr.height) <= 64):
            raise SpecError(f"door {dr.name}: a vent needs height 40..64 (crouch hull 36)")
        if dr.glass and dr.gate != "none":
            raise SpecError(f"door {dr.name}: glass and gate exclude each other")
        if dr.arch and (dr.kind != "door" or dr.glass or dr.gate != "none"):
            raise SpecError(f"door {dr.name}: an arch is only for a plain door (no gate/glass)")
    stairs = []
    for s in data.get("stairs", []):
        st = Stairs(
            name=s["name"],
            area=need(s["area"], s["name"]),
            axis=s["axis"],
            rise=int(s["rise"]),
            step=int(s.get("step", 16)),
            run=int(s.get("run", 32)),
            start=int(s.get("start", 0)),
            clip=bool(s.get("clip", False)),
        )
        if st.axis not in ("+x", "-x", "+y", "-y"):
            raise SpecError(f"stairs {st.name}: axis must be +x/-x/+y/-y")
        if st.step > 18:
            raise SpecError(f"stairs {st.name}: step {st.step} > 18 (GoldSrc step height)")
        if st.rise % st.step:
            raise SpecError(f"stairs {st.name}: rise must be a multiple of step")
        stairs.append(st)
    cover = []
    for c in data.get("cover", []):
        preset = c.get("preset")
        if preset is not None and preset not in PRESETS:
            raise SpecError(f"cover {c['name']}: preset must be one of {sorted(PRESETS)}")
        if "size" not in c and preset is None:
            raise SpecError(f"cover {c['name']}: size is required (or a preset)")
        size = c["size"] if "size" in c else PRESETS[preset]
        cover.append(
            Cover(
                name=c["name"],
                area=need(c["area"], c["name"]),
                pos=_ints(c["pos"], 2, f"cover {c['name']}.pos"),
                size=_ints(size, 3, f"cover {c['name']}.size"),
                z=int(c.get("z", 0)),
                texture=c.get("texture"),
                shape=str(c.get("shape", "box")),
                breakable=c.get("breakable"),
                preset=preset,
            )
        )
    for c in cover:
        if c.shape not in SHAPES:
            raise SpecError(f"cover {c.name}: shape must be one of {SHAPES}")
        if c.preset and c.shape != "box":
            raise SpecError(f"cover {c.name}: a preset sets its own shapes (drop shape)")
        if c.preset and (why := check_prop(c.preset, c.size)):
            raise SpecError(f"cover {c.name}: {why}")
        if c.shape == "cylinder" and min(c.size[:2]) < 32:
            raise SpecError(f"cover {c.name}: a cylinder needs >= 32 units across")
        if c.breakable is not None and c.breakable not in MATERIALS:
            raise SpecError(f"cover {c.name}: breakable must be one of {sorted(MATERIALS)}")
        if c.shape == "octagon" and min(c.size[:2]) < 32:
            raise SpecError(f"cover {c.name}: an octagon needs >= 32 units across")
        if c.z < 0 or c.z + c.size[2] > areas[c.area].height:
            raise SpecError(f"cover {c.name}: z {c.z} + height {c.size[2]} leaves its area")
        corners = (c.pos[0] - c.size[0] / 2, c.pos[1] - c.size[1] / 2, c.pos[0] + c.size[0] / 2)
        if any(v % 8 for v in (*corners, c.pos[1] + c.size[1] / 2, c.z, c.size[2])):
            raise SpecError(
                f"cover {c.name}: its corners must be on the 8-unit grid (pos +- size/2)"
            )
        if not areas[c.area].inside(*c.pos):
            raise SpecError(f"cover {c.name}: pos {list(c.pos)} is outside the floor of {c.area}")
    ramps = []
    for r in data.get("ramps", []):
        rp = Ramp(
            name=r["name"],
            area=need(r["area"], r["name"]),
            axis=r["axis"],
            rise=int(r["rise"]),
            length=int(r["length"]),
            start=int(r.get("start", 0)),
        )
        if rp.axis not in ("+x", "-x", "+y", "-y"):
            raise SpecError(f"ramp {rp.name}: axis must be +x/-x/+y/-y")
        if not (rp.rise > 0 and 2 * rp.rise <= rp.length):
            # players walk up to ~45°, but YaPB's graph analyser leaves steeper ramps unmapped
            # (de_cistern01: 192 over 256 = 37° cut B off from the bots; CALIBRATION.md)
            raise SpecError(f"ramp {rp.name}: needs 0 < rise <= length / 2 (<= 26.6°: YaPB bots)")
        for v in (rp.rise, rp.length, rp.start):
            if v % grid:
                raise SpecError(f"ramp {rp.name}: {v} is off the {grid}-unit grid")
        a = areas[rp.area]
        span = a.rect[2] - a.rect[0] if rp.axis[1] == "x" else a.rect[3] - a.rect[1]
        if rp.start + rp.length > span:
            raise SpecError(f"ramp {rp.name}: start + length {rp.start + rp.length} > area {span}")
        ramps.append(rp)
    wedges = []
    for w in data.get("wedges", []):
        wd = Wedge(
            name=w["name"],
            area=need(w["area"], w["name"]),
            corner=w["corner"],
            size=_ints(w["size"], 2, f"wedge {w['name']}.size"),
            height=w.get("height"),
        )
        if wd.corner not in CORNERS:
            raise SpecError(f"wedge {wd.name}: corner must be one of {CORNERS}")
        a = areas[wd.area]
        if not (
            0 < wd.size[0] <= a.rect[2] - a.rect[0] and 0 < wd.size[1] <= a.rect[3] - a.rect[1]
        ):
            raise SpecError(f"wedge {wd.name}: legs {wd.size} do not fit in area {wd.area}")
        if any(v % grid for v in wd.size):
            raise SpecError(f"wedge {wd.name}: legs {wd.size} are off the {grid}-unit grid")
        wedges.append(wd)
    ladders = []
    for ld in data.get("ladders", []):
        lad = Ladder(
            name=ld["name"],
            area=need(ld["area"], ld["name"]),
            wall=ld["wall"],
            pos=int(ld.get("pos", 0)),
            width=int(ld.get("width", 32)),
            height=int(ld.get("height", 128)),
        )
        if lad.wall not in ("+x", "-x", "+y", "-y"):
            raise SpecError(f"ladder {lad.name}: wall must be +x/-x/+y/-y")
        if lad.height > areas[lad.area].height:
            raise SpecError(f"ladder {lad.name}: taller than its area")
        la = areas[lad.area]
        span = la.side_span(lad.wall)
        x0, y0, x1, y1 = la.rect
        c = ((y0 + y1) // 2 if lad.wall[1] == "x" else (x0 + x1) // 2) + lad.pos
        if span is None or not span[0] <= c - lad.width // 2 < c + lad.width // 2 <= span[1]:
            raise SpecError(f"ladder {lad.name}: not on the {lad.wall} wall of {lad.area}")
        ladders.append(lad)
    hatches = []
    for h in data.get("hatches", []) or []:
        ht = Hatch(
            name=h["name"],
            lower=need(h["lower"], h["name"]),
            upper=need(h["upper"], h["name"]),
            rect=_ints(h["rect"], 4, f"hatch {h['name']}.rect"),
            ladder=h.get("ladder"),
            lift=h.get("lift"),
        )
        lo, up = areas[ht.lower], areas[ht.upper]
        hx0, hy0, hx1, hy1 = ht.rect
        for a in (lo, up):
            ax0, ay0, ax1, ay1 = a.rect
            if not (ax0 <= hx0 < hx1 <= ax1 and ay0 <= hy0 < hy1 <= ay1):
                raise SpecError(
                    f"hatch {ht.name}: rect must lie inside both {lo.name} and {up.name}"
                )
        if up.floor < lo.top + 8:
            raise SpecError(
                f"hatch {ht.name}: {up.name} must sit above {lo.name} (floor >= its top + 8)"
            )
        if min(hx1 - hx0, hy1 - hy0) < 48:
            raise SpecError(f"hatch {ht.name}: needs >= 48 units across (a player is 32)")
        if ht.ladder not in (None, "+x", "-x", "+y", "-y"):
            raise SpecError(f"hatch {ht.name}: ladder must be +x/-x/+y/-y or absent")
        if ht.lift not in (None, "auto", "button"):
            raise SpecError(f"hatch {ht.name}: lift must be auto, button or absent")
        if ht.lift and ht.ladder:
            raise SpecError(f"hatch {ht.name}: a lift and a ladder exclude each other")
        if ht.lift and min(hx1 - hx0, hy1 - hy0) < 64:
            raise SpecError(f"hatch {ht.name}: a lift needs >= 64 units across")
        if ht.lift and up.floor - lo.floor > 512:
            raise SpecError(f"hatch {ht.name}: a lift travels at most 512 units")
        hatches.append(ht)
    water = []
    for w in data.get("water", []) or []:
        a = areas[need(w["area"], w["name"])]
        wt = Water(name=w["name"], area=a.name,
                   rect=_ints(w.get("rect", list(a.rect)), 4, f"water {w['name']}.rect"),
                   depth=int(w["depth"]))  # fmt: skip
        if not (0 < wt.depth <= a.height):
            raise SpecError(f"water {wt.name}: depth must be 1..{a.height}")
        water.append(wt)
    spots = []
    for sp in data.get("spots", []) or []:
        spots.append(Spot(
            name=sp["name"], area=need(sp["area"], sp["name"]),
            pos=_ints(sp["pos"], 2, f"spot {sp['name']}.pos"), z=int(sp.get("z", 0)),
            pitch=int(sp.get("pitch", -90)), yaw=int(sp.get("yaw", 0)),
            cone=_ints(sp.get("cone", [30, 45]), 2, f"spot {sp['name']}.cone"),
            brightness=int(sp.get("brightness", 300)),
            color=_ints(sp.get("color", [255, 240, 220]), 3, f"spot {sp['name']}.color"),
        ))  # fmt: skip
    ambient = []
    for am in data.get("ambient", []) or []:
        amb = Ambient(
            name=am["name"], area=need(am["area"], am["name"]), sound=str(am["sound"]),
            pos=_ints(am["pos"], 2, f"ambient {am['name']}.pos") if "pos" in am else None,
            z=int(am.get("z", 64)), volume=int(am.get("volume", 6)),
            radius=str(am.get("radius", "medium")),
        )  # fmt: skip
        if amb.radius not in AMBIENT_RADIUS:
            raise SpecError(f"ambient {amb.name}: radius must be one of {sorted(AMBIENT_RADIUS)}")
        if not 1 <= amb.volume <= 10:
            raise SpecError(f"ambient {amb.name}: volume must be 1-10")
        if not amb.sound.lower().endswith(".wav") or amb.sound.startswith(("/", "sound/")):
            raise SpecError(f"ambient {amb.name}: sound is a .wav path under sound/, e.g. "
                            "ambience/industrial1.wav")  # fmt: skip
        if amb.pos is not None and not areas[amb.area].inside(*amb.pos):
            raise SpecError(f"ambient {amb.name}: pos is outside {amb.area}")
        ambient.append(amb)
    models = []
    for md in data.get("models", []) or []:
        mo = Model(
            name=md["name"], area=need(md["area"], md["name"]), model=str(md["model"]),
            pos=_ints(md["pos"], 2, f"model {md['name']}.pos"), z=int(md.get("z", 0)),
            yaw=int(md.get("yaw", 0)),
            clip=_ints(md["clip"], 3, f"model {md['name']}.clip") if md.get("clip") else None,
        )  # fmt: skip
        if not (mo.model.startswith("models/") and mo.model.lower().endswith(".mdl")):
            raise SpecError(f"model {mo.name}: model is a path like models/conveyor1.mdl")
        if not areas[mo.area].inside(*mo.pos):
            raise SpecError(f"model {mo.name}: pos is outside {mo.area}")
        if mo.clip and any(v % 8 or v <= 0 for v in mo.clip):
            raise SpecError(f"model {mo.name}: clip [w, d, h] must be positive and on the 8 grid")
        models.append(mo)
    bridges = []
    for b in data.get("bridges", []) or []:
        br = Bridge(
            name=b["name"], area=need(b["area"], b["name"]), axis=str(b["axis"]), z=int(b["z"]),
            width=int(b.get("width", 96)), pos=int(b.get("pos", 0)),
            thickness=int(b.get("thickness", 16)), rail=int(b.get("rail", 40)),
        )  # fmt: skip
        if br.axis not in ("x", "y"):
            raise SpecError(f"bridge {br.name}: axis must be x or y (the way it runs)")
        if any(v % 8 for v in (br.z, br.width, br.pos, br.thickness, br.rail)):
            raise SpecError(f"bridge {br.name}: z/width/pos/thickness/rail must be on the 8 grid")
        a = areas[br.area]
        if br.width < 64 or br.thickness < 8 or br.rail < 0:
            raise SpecError(f"bridge {br.name}: width >= 64, thickness >= 8, rail >= 0")
        if br.z - br.thickness < BRIDGE_CLEARANCE or a.height - br.z < BRIDGE_CLEARANCE:
            raise SpecError(
                f"bridge {br.name}: needs {BRIDGE_CLEARANCE} units free under the deck and over "
                f"it (z - thickness and height - z; area {a.name} is {a.height} high)"
            )
        x0, y0, x1, y1 = a.rect
        lo, hi = (y0, y1) if br.axis == "x" else (x0, x1)
        c = (lo + hi) // 2 + br.pos
        if c - br.width // 2 < lo or c + br.width // 2 > hi:
            raise SpecError(f"bridge {br.name}: pos/width put it outside {a.name}")
        bridges.append(br)
    zones = data.get("zones", {}) or {}
    for a in areas.values():
        if a.zone is not None and a.zone not in zones:
            raise SpecError(f"area {a.name}: unknown zone {a.zone!r} (define it under zones:)")
    weapons = []
    for wp in data.get("weapons", []) or []:
        need(wp["area"], f"weapon {wp.get('item')}")
        _ints(wp["pos"], 2, f"weapon {wp.get('item')}.pos")
        weapons.append(dict(wp))
    sites = {
        k: need(v["area"] if isinstance(v, dict) else v, f"site {k}")
        for k, v in data.get("sites", {}).items()
    }
    spawns = {}
    for team in ("T", "CT"):
        sp = data.get("spawns", {}).get(team)
        if sp is None:
            raise SpecError(f"spawns.{team} missing")
        spawns[team] = {
            "area": need(sp["area"], f"spawns.{team}"),
            "count": int(sp.get("count", 16)),  # 16 per team is the game maximum (DESIGN_GUIDE §4)
            # shift of the spawn cluster inside its area (Decide: move_spawn); spawns fill the
            # grid outwards from area centre + offset
            "offset": _ints(sp.get("offset", [0, 0]), 2, f"spawns.{team}.offset"),
        }
    groups = (doors, stairs, cover, ramps, wedges, ladders, hatches, water, spots, bridges, ambient,
              models)  # fmt: skip
    names = [x.name for group in groups for x in group]
    dup = {n for n in names if names.count(n) > 1 or n in areas}
    if dup:
        raise SpecError(f"names must be unique across areas/doors/stairs/cover: {sorted(dup)}")
    return Layout(
        name=data["name"],
        grid=grid,
        wall=wall,
        textures={**DEFAULT_TEXTURES, **data.get("textures", {})},
        areas=areas,
        doors=doors,
        stairs=stairs,
        cover=cover,
        sites=sites,
        spawns=spawns,
        buyzones=bool(data.get("buyzones", True)),
        sky=data.get("sky", {}) or {},
        lights=data.get("lights", {}) or {},
        ramps=ramps,
        wedges=wedges,
        ladders=ladders,
        zones=zones,
        weapons=weapons,
        map_parameters=data.get("map_parameters", {}) or {},
        detail=bool(data.get("detail", False)),
        hatches=hatches,
        water=water,
        spots=spots,
        texlights={**DEFAULT_TEXLIGHTS, **(data.get("texlights") or {})},
        sounds=bool(data.get("sounds", False)),
        bridges=bridges,
        ambient=ambient,
        models=models,
    )


def load_layout(path: Path) -> Layout:
    return parse_layout(yaml.safe_load(path.read_text(encoding="utf-8")))
