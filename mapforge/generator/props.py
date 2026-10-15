"""Cover presets and themed props: several solids inside one cover footprint.

A prop is placed like any cover item (`cover:` with `preset: <name>`, pos = centre, size =
footprint [w, d, h] or the prop's default). Its solids stay inside the footprint, so spawns, the
walk check and the toolbox treat it as one box. Props may change gameplay (a rail wagon is as
much cover as the train on de_train); after Gate B they are still free, only the layout is
frozen (FITNESS.md).

Theme props carry their own textures from the game's standard WADs (referenced, never
embedded: mapforge.wad.catalog), e.g. tswad.wad (as_oilrig) and cs_bdog.wad (de_train).
Generic presets (theme None) use the zone's cover texture.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Tex = str | dict[str, str] | None


@dataclass(frozen=True)
class Solid:
    shape: str  # box | octagon | cylinder (vertical) | pipe (horizontal, along the long side)
    lo: tuple[int, int, int]
    hi: tuple[int, int, int]
    tex: Tex = None  # None: the cover's own texture
    fit: tuple[int, int] | None = None  # texture size: each face shows exactly one whole tile


@dataclass(frozen=True)
class Prop:
    size: tuple[int, int, int]  # default footprint [w, d, h]
    theme: str | None  # None = any theme
    build: Callable[[Box2, int, int], list[Solid]]
    min_size: tuple[int, int, int] = (32, 32, 16)
    note: str = ""


@dataclass(frozen=True)
class Box2:
    """A footprint with its long side: u along it, v across (for oriented props)."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def along_x(self) -> bool:
        return self.x1 - self.x0 >= self.y1 - self.y0

    def part(self, u0: int, u1: int, v0: int | None = None, v1: int | None = None) -> tuple:
        """(x0, y0), (x1, y1) of the slice u0..u1 along the long side (v0..v1 across, from the
        low edge; default: the whole width)."""
        if self.along_x:
            vy0 = self.y0 if v0 is None else self.y0 + v0
            vy1 = self.y1 if v1 is None else self.y0 + v1
            return (self.x0 + u0, vy0), (self.x0 + u1, vy1)
        vx0 = self.x0 if v0 is None else self.x0 + v0
        vx1 = self.x1 if v1 is None else self.x0 + v1
        return (vx0, self.y0 + u0), (vx1, self.y0 + u1)

    @property
    def length(self) -> int:
        return max(self.x1 - self.x0, self.y1 - self.y0)

    @property
    def width(self) -> int:
        return min(self.x1 - self.x0, self.y1 - self.y0)

    def ends(self, tex: str) -> dict[str, str]:
        """Texture keys for the two faces across the long side."""
        return {"-x": tex, "+x": tex} if self.along_x else {"-y": tex, "+y": tex}


def _box(b: Box2, u0: int, u1: int, z0: int, z1: int, tex: Tex = None, v0=None, v1=None):
    (x0, y0), (x1, y1) = b.part(u0, u1, v0, v1)
    return Solid("box", (x0, y0, z0), (x1, y1, z1), tex)


# --- generic presets (the zone's cover texture) ------------------------------------------------


def _crate_stack(b: Box2, z0: int, h: int) -> list[Solid]:
    """Two crates side by side, a third on one of them (boost)."""
    half, m = h // 2, b.length // 2
    return [_box(b, 0, m, z0, z0 + half), _box(b, m, b.length, z0, z0 + half),
            _box(b, 0, m, z0 + half, z0 + h)]  # fmt: skip


def _barrels(b: Box2, z0: int, h: int) -> list[Solid]:
    """Two barrels in a row along the long side, a third in front of the gap between them."""
    dia = b.width // 2
    cells = [(0, 0), (dia, 0), (dia // 2 // 8 * 8, dia)]
    out = []
    for u, v in cells:
        (x0, y0), (x1, y1) = b.part(u, u + dia, v, v + dia)
        out.append(Solid("cylinder", (x0, y0, z0), (x1, y1, z0 + h)))
    return out


def _pallets(b: Box2, z0: int, h: int) -> list[Solid]:
    """A low stack to step on (<= 18) or crouch behind."""
    return [_box(b, 0, b.length, z0, z0 + h)]


# --- industrial props (textures from the game's WADs) ------------------------------------------

STEEL = {"side": "TSHULL5", "top": "TSHULL7"}  # tswad.wad: worn steel plates
RUST = {"side": "TSPLAINRED", "top": "TSOILY"}


def _container(b: Box2, z0: int, h: int) -> list[Solid]:
    """A shipping container: one block, green container sides and a ribbed roof."""
    # the side texture is one crate stack with a dark pallet gap at its foot: tiled, the gap
    # shows halfway up as a black seam, so every face is stretched to one whole tile
    s = _box(b, 0, b.length, z0, z0 + h, {"side": "TSCRTESD", "top": "TSCRTETP"})
    return [Solid(s.shape, s.lo, s.hi, s.tex, fit=(64, 64))]


def _rail_wagon(b: Box2, z0: int, h: int) -> list[Solid]:
    """A slag wagon on rails (like the train on de_train): two bogies at the ends, a dark
    underframe between them (no gap to get stuck in) and the body on top; rails run under it
    the whole length (8 high: a step, not a wall)."""
    bogie, inset, frame = 64, 16, 32
    w = b.width
    out = [
        _box(b, 0, b.length, z0, z0 + 8, "TSIBEAM", v0=inset, v1=inset + 8),
        _box(b, 0, b.length, z0, z0 + 8, "TSIBEAM", v0=w - inset - 8, v1=w - inset),
        _box(b, 0, bogie, z0 + 8, z0 + frame, "WHEELSIDE01", v0=inset, v1=w - inset),
        _box(b, b.length - bogie, b.length, z0 + 8, z0 + frame, "WHEELSIDE01", v0=inset,
             v1=w - inset),
        _box(b, bogie, b.length - bogie, z0 + 8, z0 + frame, "CONNECTOR", v0=inset,
             v1=w - inset),
        _box(b, 0, b.length, z0 + frame, z0 + h,
             {"side": "TRAINSIDE02-1", "top": "TRAINTOP01", **b.ends("TRAINEND01")}),
    ]  # fmt: skip
    return out


def _ladle(b: Box2, z0: int, h: int) -> list[Solid]:
    """A casting ladle: a big rusty drum."""
    (x0, y0), (x1, y1) = b.part(0, b.length)
    return [Solid("cylinder", (x0, y0, z0), (x1, y1, z0 + h), RUST)]


def _forklift(b: Box2, z0: int, h: int) -> list[Solid]:
    """A forklift: a low body with a striped mast at the front end."""
    body = min(h, 64)
    return [_box(b, 0, b.length - 16, z0, z0 + body, {"side": "TSCAUTION", "top": "TSHULL7"}),
            _box(b, b.length - 16, b.length, z0, z0 + h, "TSIBEAM")]  # fmt: skip


def _ingot_stack(b: Box2, z0: int, h: int) -> list[Solid]:
    """Steel ingots cooling off: a long bottom layer, a shorter one on top."""
    half = h // 2
    inset = b.length // 4 // 16 * 16
    return [_box(b, 0, b.length, z0, z0 + half, RUST),
            _box(b, inset, b.length - inset, z0 + half, z0 + h, RUST)]  # fmt: skip


def _pipe_run(b: Box2, z0: int, h: int) -> list[Solid]:
    """A horizontal pipe along the long side (an octagon in cross-section); put it high or
    against a wall with `z` for dressing, low for cover."""
    (x0, y0), (x1, y1) = b.part(0, b.length)
    return [Solid("pipe", (x0, y0, z0), (x1, y1, z0 + h), STEEL)]


PROPS: dict[str, Prop] = {
    "crate_stack": Prop((128, 64, 128), None, _crate_stack, (64, 32, 32), "boost spot"),
    "barrels": Prop((96, 96, 48), None, _barrels, (64, 64, 16)),
    "pallets": Prop((64, 64, 16), None, _pallets, note="step (<= 18) or crouch cover"),
    "container": Prop((256, 112, 128), "industrial", _container, (128, 64, 64)),
    "rail_wagon": Prop((384, 128, 144), "industrial", _rail_wagon, (192, 96, 64),
                       "like the train on de_train; rails 8 high"),
    "ladle": Prop((128, 128, 96), "industrial", _ladle, (64, 64, 32)),
    "forklift": Prop((128, 64, 128), "industrial", _forklift, (64, 48, 64)),
    "ingot_stack": Prop((128, 64, 48), "industrial", _ingot_stack, (64, 32, 32)),
    "pipe_run": Prop((256, 32, 32), "industrial", _pipe_run, (64, 32, 32),
                     "horizontal pipe; with z along a wall for dressing"),
}  # fmt: skip


def check(name: str, size: tuple[int, int, int]) -> str | None:
    """Why a prop cannot have this size, or None."""
    p = PROPS[name]
    length, width, h = max(size[:2]), min(size[:2]), size[2]
    if length < p.min_size[0] or width < p.min_size[1] or h < p.min_size[2]:
        return f"{name} needs at least {list(p.min_size)} (long side, short side, height)"
    if name == "crate_stack" and (length % 32 or h % 16):
        return "crate_stack needs a long side / 32 and height / 16"
    if name == "barrels" and width % 16:
        return "barrels need a short side divisible by 16"
    if name in ("ingot_stack",) and h % 16:
        return f"{name} needs a height divisible by 16"
    return None


def solids(name: str, lo: tuple[int, int], hi: tuple[int, int], z0: int, h: int) -> list[Solid]:
    return PROPS[name].build(Box2(lo[0], lo[1], hi[0], hi[1]), z0, h)


def catalog() -> list[dict[str, Any]]:
    """The props for prompts and docs: name, default size, theme, note."""
    return [{"name": n, "size": list(p.size), "theme": p.theme, "note": p.note}
            for n, p in PROPS.items()]  # fmt: skip
