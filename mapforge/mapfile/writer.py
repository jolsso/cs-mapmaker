"""Write Valve 220 .map files, and build axis-aligned box brushes."""

from __future__ import annotations

from pathlib import Path

from mapforge.mapfile.parser import Brush, Entity, Face, MapFile

# Face order and texture axes of an axis-aligned box (Quake winding, normals point out),
# as written by TrenchBroom: -X, -Y, -Z (bottom), +Z (top), +Y, +X.
_AXES = {
    "-x": ((0, -1, 0, 0), (0, 0, -1, 0)),
    "-y": ((1, 0, 0, 0), (0, 0, -1, 0)),
    "-z": ((-1, 0, 0, 0), (0, -1, 0, 0)),
    "+z": ((1, 0, 0, 0), (0, -1, 0, 0)),
    "+y": ((-1, 0, 0, 0), (0, 0, -1, 0)),
    "+x": ((0, 1, 0, 0), (0, 0, -1, 0)),
}


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def box_brush(
    lo: tuple[float, float, float],
    hi: tuple[float, float, float],
    textures: str | dict[str, str],
    entity_index: int = 0,
) -> Brush:
    """Axis-aligned box. `textures` is one name, or per side: keys top, bottom, side (or
    -x/+x/-y/+y/-z/+z), e.g. {"top": "FLOOR", "bottom": "CEIL", "side": "WALL"}."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    if not (x0 < x1 and y0 < y1 and z0 < z1):
        raise ValueError(f"empty box {lo} {hi}")

    def tex(side: str) -> str:
        if isinstance(textures, str):
            return textures
        named = {"-z": "bottom", "+z": "top"}.get(side, "side")
        return textures.get(side) or textures.get(named) or textures["side"]

    d = 16  # in-plane offset for the 2nd/3rd plane point (any non-zero value works)
    pts = {
        "-x": ((x0, y0, z0), (x0, y0 + d, z0), (x0, y0, z0 + d)),
        "-y": ((x0, y0, z0), (x0, y0, z0 + d), (x0 + d, y0, z0)),
        "-z": ((x0, y0, z0), (x0 + d, y0, z0), (x0, y0 + d, z0)),
        "+z": ((x1, y1, z1), (x1, y1 + d, z1), (x1 + d, y1, z1)),
        "+y": ((x1, y1, z1), (x1 + d, y1, z1), (x1, y1, z1 + d)),
        "+x": ((x1, y1, z1), (x1, y1, z1 + d), (x1, y1 + d, z1)),
    }
    faces = [
        Face(
            points=pts[s],
            texture=tex(s),
            u_axis=_AXES[s][0],
            v_axis=_AXES[s][1],
            rotation=0,
            scale=(1, 1),
            line=0,
        )  # fmt: skip
        for s in ("-x", "-y", "-z", "+z", "+y", "+x")
    ]
    return Brush(faces=faces, line=0, entity_index=entity_index, brush_index=0)


def _face_line(f: Face) -> str:
    p = " ".join("( " + " ".join(_num(c) for c in pt) + " )" for pt in f.points)
    u = "[ " + " ".join(_num(c) for c in f.u_axis) + " ]"
    v = "[ " + " ".join(_num(c) for c in f.v_axis) + " ]"
    return f"{p} {f.texture} {u} {v} {_num(f.rotation)} {_num(f.scale[0])} {_num(f.scale[1])}"


def format_map(m: MapFile, header: str = "") -> str:
    out = [f"// {line}\n" for line in header.splitlines()]
    for ent in m.entities:
        out.append("{\n")
        for k, v in ent.properties.items():
            if '"' in k or '"' in v:
                raise ValueError(f"quote in key/value: {k!r}={v!r}")
            out.append(f'"{k}" "{v}"\n')
        for b in ent.brushes:
            out.append("{\n" + "".join(_face_line(f) + "\n" for f in b.faces) + "}\n")
        out.append("}\n")
    return "".join(out)


def write_map(m: MapFile, path: Path, header: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_map(m, header), encoding="utf-8", newline="\n")


def entity(props: dict[str, str], brushes: list[Brush] | None = None) -> Entity:
    return Entity(properties=dict(props), brushes=list(brushes or []))
