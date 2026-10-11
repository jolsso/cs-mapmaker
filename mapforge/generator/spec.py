"""Layout spec (maps/<map>/layout.yaml): parsing and checks. Format: docs/LAYOUT_SPEC.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


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

    @property
    def top(self) -> int:
        return self.floor + self.height


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
}


def _ints(v: Any, n: int, what: str) -> tuple[int, ...]:
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(isinstance(x, int) for x in v):
        raise SpecError(f"{what}: expected {n} integers, got {v!r}")
    return tuple(v)


def parse_layout(data: dict[str, Any]) -> Layout:
    if not isinstance(data, dict) or "name" not in data:
        raise SpecError("layout needs a 'name'")
    grid = int(data.get("grid", 16))
    wall = int(data.get("wall", 16))
    areas: dict[str, Area] = {}
    for a in data.get("areas", []):
        rect = _ints(a.get("rect"), 4, f"area {a.get('name')}.rect")
        area = Area(
            name=a["name"],
            rect=rect,
            floor=int(a.get("floor", 0)),
            height=int(a.get("height", 192)),
            outdoor=bool(a.get("outdoor", False)),
            role=a.get("role", "room"),
            zone=a.get("zone"),
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
    cover = [
        Cover(
            name=c["name"],
            area=need(c["area"], c["name"]),
            pos=_ints(c["pos"], 2, f"cover {c['name']}.pos"),
            size=_ints(c["size"], 3, f"cover {c['name']}.size"),
            z=int(c.get("z", 0)),
            texture=c.get("texture"),
        )
        for c in data.get("cover", [])
    ]
    for c in cover:
        if c.z < 0 or c.z + c.size[2] > areas[c.area].height:
            raise SpecError(f"cover {c.name}: z {c.z} + height {c.size[2]} leaves its area")
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
        if not (0 < rp.rise <= rp.length):
            raise SpecError(f"ramp {rp.name}: needs 0 < rise <= length (GoldSrc walks <= ~45°)")
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
        ladders.append(lad)
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
    names = [x.name for group in (doors, stairs, cover, ramps, wedges, ladders) for x in group]
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
    )


def load_layout(path: Path) -> Layout:
    return parse_layout(yaml.safe_load(path.read_text(encoding="utf-8")))
