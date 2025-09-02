from pathlib import Path
from typing import Iterable, List, Tuple


def write_empty_map(map_path: Path, wads: Iterable[str] | None = None) -> None:
    """Write a minimal Valve 220 .map with only worldspawn.

    This yields a valid, empty map Hammer can open. Solids will be added by the
    generation pipeline later.
    """
    map_path = Path(map_path)
    map_path.parent.mkdir(parents=True, exist_ok=True)
    wad_value = ";".join(wads or [])

    content = (
        'worldspawn\n'
        '{\n'
        '"mapversion" "220"\n'
        '"classname" "worldspawn"\n'
        + (f'"wad" "{wad_value}"\n' if wad_value else "")
        + '}\n'
    )
    map_path.write_text(content, encoding="utf-8")


def _side_line(p1: Tuple[float, float, float], p2: Tuple[float, float, float], p3: Tuple[float, float, float], texture: str,
               uaxis: Tuple[float, float, float, float] = (1, 0, 0, 0),
               vaxis: Tuple[float, float, float, float] = (0, 1, 0, 0),
               rotation: float = 0.0,
               scale_u: float = 1.0,
               scale_v: float = 1.0) -> str:
    def fmt_pt(pt: Tuple[float, float, float]) -> str:
        x, y, z = pt
        return f"( {x:.3f} {y:.3f} {z:.3f} )"

    ux, uy, uz, uo = uaxis
    vx, vy, vz, vo = vaxis
    return (
        f"{fmt_pt(p1)} {fmt_pt(p2)} {fmt_pt(p3)} {texture} "
        f"[ {ux:.3f} {uy:.3f} {uz:.3f} {uo:.3f} ] "
        f"[ {vx:.3f} {vy:.3f} {vz:.3f} {vo:.3f} ] "
        f"{rotation:.0f} {scale_u:.3f} {scale_v:.3f}\n"
    )


def write_boxes_map(
    map_path: Path,
    boxes: List[Tuple[float, float, float, float, float, float]],
    *,
    wads: Iterable[str] | None = None,
    wall_texture: str = "BRICK/BRICK01",
    roof_texture: str = "ROOF/ROOF01",
) -> None:
    """Write a Valve 220 .map with axis-aligned box solids.

    Each box tuple is (minx, miny, maxx, maxy, z0, z1) in Hammer units.
    """
    map_path = Path(map_path)
    map_path.parent.mkdir(parents=True, exist_ok=True)
    wad_value = ";".join(wads or [])

    lines: List[str] = []
    # Worldspawn
    lines.append("worldspawn\n")
    lines.append("{\n")
    lines.append("\"mapversion\" \"220\"\n")
    lines.append("\"classname\" \"worldspawn\"\n")
    if wad_value:
        lines.append(f"\"wad\" \"{wad_value}\"\n")
    lines.append("}\n")

    for (minx, miny, maxx, maxy, z0, z1) in boxes:
        x0, y0, x1, y1 = minx, miny, maxx, maxy
        # Faces defined with outward normals via point winding
        # Top (+Z)
        top = _side_line((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), roof_texture,
                         uaxis=(1, 0, 0, 0), vaxis=(0, -1, 0, 0))
        # Bottom (-Z)
        bottom = _side_line((x1, y1, z0), (x1, y0, z0), (x0, y0, z0), wall_texture,
                            uaxis=(1, 0, 0, 0), vaxis=(0, 1, 0, 0))
        # +X
        posx = _side_line((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), wall_texture,
                          uaxis=(0, 1, 0, 0), vaxis=(0, 0, -1, 0))
        # -X
        negx = _side_line((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), wall_texture,
                          uaxis=(0, -1, 0, 0), vaxis=(0, 0, -1, 0))
        # +Y
        posy = _side_line((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), wall_texture,
                          uaxis=(1, 0, 0, 0), vaxis=(0, 0, -1, 0))
        # -Y
        negy = _side_line((x1, y0, z0), (x0, y0, z0), (x0, y0, z1), wall_texture,
                          uaxis=(-1, 0, 0, 0), vaxis=(0, 0, -1, 0))

        lines.append("{\n")
        lines.append(top)
        lines.append(bottom)
        lines.append(posx)
        lines.append(negx)
        lines.append(posy)
        lines.append(negy)
        lines.append("}\n")

    map_path.write_text("".join(lines), encoding="utf-8")
