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

    @property
    def top(self) -> int:
        return self.floor + self.height


@dataclass(frozen=True)
class Door:
    name: str
    between: tuple[str, str]
    width: int
    height: int | None = None
    offset: int = 0


@dataclass(frozen=True)
class Stairs:
    name: str
    area: str
    axis: str  # +x -x +y -y: direction of climbing
    rise: int
    step: int = 16
    run: int = 32
    start: int = 0  # distance from the area edge where the first step begins


@dataclass(frozen=True)
class Cover:
    name: str
    area: str
    pos: tuple[int, int]
    size: tuple[int, int, int]


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


DEFAULT_TEXTURES = {
    "floor": "DEV_FLOOR",
    "wall": "DEV_WALL",
    "ceiling": "DEV_CEIL",
    "cover": "DEV_CRATE",
    "sky": "SKY",
    "trigger": "AAATRIGGER",
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
            )
        )
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
        )
        for c in data.get("cover", [])
    ]
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
        }
    names = [d.name for d in doors] + [s.name for s in stairs] + [c.name for c in cover]
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
    )


def load_layout(path: Path) -> Layout:
    return parse_layout(yaml.safe_load(path.read_text(encoding="utf-8")))
