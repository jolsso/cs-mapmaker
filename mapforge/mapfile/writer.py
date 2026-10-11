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


def _tex_axes(n: tuple[float, float, float]) -> tuple[tuple, tuple]:
    """Valve 220 texture axes for a face with normal n: floors/ramps project from above,
    walls (also slanted ones) run their u axis along the wall so textures are not stretched."""
    nx, ny, nz = n
    if abs(nz) >= max(abs(nx), abs(ny)):
        return (1, 0, 0, 0), (0, -1, 0, 0)
    h = (nx * nx + ny * ny) ** 0.5
    u = (round(-ny / h, 6), round(nx / h, 6), 0)
    return (*u, 0), (0, 0, -1, 0)


def polyhedron_brush(
    faces: list[list[tuple[float, float, float]]],
    textures: str | dict[str, str],
    entity_index: int = 0,
) -> Brush:
    """Convex brush from its faces, each a list of >= 3 vertices (any order on the face).

    The plane points are three of the face's own vertices, wound so the normal points out of
    the brush (Quake: normal = (p3 - p1) x (p2 - p1)); grid vertices give exact planes.
    `textures`: one name or {"top", "bottom", "side"} chosen by the face's normal.
    """
    verts = [v for f in faces for v in f]
    cx, cy, cz = (sum(v[i] for v in verts) / len(verts) for i in range(3))
    out = []
    for f in faces:
        p1 = f[0]
        best = None
        for i in range(1, len(f)):  # the pair spanning the largest triangle (robust winding)
            for j in range(i + 1, len(f)):
                a = [f[i][k] - p1[k] for k in range(3)]
                b = [f[j][k] - p1[k] for k in range(3)]
                n = (
                    b[1] * a[2] - b[2] * a[1],
                    b[2] * a[0] - b[0] * a[2],
                    b[0] * a[1] - b[1] * a[0],
                )
                size = sum(c * c for c in n)
                if best is None or size > best[0]:
                    best = (size, f[i], f[j], n)
        if best is None or best[0] == 0:
            raise ValueError(f"degenerate face {f}")
        _, p2, p3, n = best
        fc = [sum(v[k] for v in f) / len(f) for k in range(3)]
        if sum(n[k] * (fc[k] - (cx, cy, cz)[k]) for k in range(3)) < 0:
            p2, p3, n = p3, p2, tuple(-c for c in n)
        if isinstance(textures, str):
            tex = textures
        else:
            m = max(abs(c) for c in n)
            named = "top" if n[2] == m else "bottom" if -n[2] == m else "side"
            tex = textures.get(named) or textures["side"]
        u, v = _tex_axes(n)
        out.append(Face(points=(tuple(p1), tuple(p2), tuple(p3)), texture=tex, u_axis=u,
                        v_axis=v, rotation=0, scale=(1, 1), line=0))  # fmt: skip
    return Brush(faces=out, line=0, entity_index=entity_index, brush_index=0)


def prism_brush(
    polygon: list[tuple[float, float]],
    z0: float,
    z1: float,
    textures: str | dict[str, str],
) -> Brush:
    """Vertical prism: a convex x/y polygon (a triangle = an angled wall) from z0 to z1."""
    bottom = [(x, y, z0) for x, y in polygon]
    top = [(x, y, z1) for x, y in polygon]
    sides = [
        [bottom[i], bottom[(i + 1) % len(polygon)], top[(i + 1) % len(polygon)], top[i]]
        for i in range(len(polygon))
    ]
    return polyhedron_brush([bottom, top, *sides], textures)


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
