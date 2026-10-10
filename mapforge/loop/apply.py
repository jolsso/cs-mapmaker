"""Apply the accepted changes of a Decide plan to maps/<map>/layout.yaml (phase 6).

Each change type of the toolbox (config/fitness.yaml -> allowed_changes) maps onto the layout
spec (docs/LAYOUT_SPEC.md -> "Hvad Decide kan ændre"). Every change is applied on its own and
then tried: the layout must still parse and generate (doors still share a wall, spawns fit, ...).
A change that fails is skipped with a reason; the others still apply. The YAML is edited
round-trip (ruamel), so comments and the hand layout of the file stay.

Protected (never moved, resized or removed by the loop, FITNESS "låste beslutninger"):
areas with role site / t_spawn / ct_spawn, and anything marked `protected: true` in the layout.
"""

from __future__ import annotations

import copy
import io
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from mapforge.generator.build import generate
from mapforge.generator.spec import SpecError, parse_layout

LOCKED_ROLES = {"site", "t_spawn", "ct_spawn"}


def yaml_rt() -> YAML:
    y = YAML()  # round-trip
    y.preserve_quotes = True
    y.width = 120
    y.indent(mapping=2, sequence=4, offset=2)  # "  - {...}" as in the hand-written layouts
    return y


def load(text: str) -> CommentedMap:
    return yaml_rt().load(text)


def dump(data: CommentedMap) -> str:
    buf = io.StringIO()
    yaml_rt().dump(data, buf)
    return buf.getvalue()


def _flow(values: list) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def _flow_map(d: dict) -> CommentedMap:
    m = CommentedMap(d)
    m.fa.set_flow_style()
    return m


def _find(items: list, name: str, what: str) -> Any:
    for it in items or []:
        if it.get("name") == name:
            return it
    raise ValueError(f"no {what} named {name!r}")


def _vec(v: Any, n: int, grid: int, what: str) -> list[int]:
    vals = list(v) if isinstance(v, (list, tuple)) else [v]
    if len(vals) != n or not all(isinstance(x, (int, float)) for x in vals):
        raise ValueError(f"{what}: expected {n} numbers, got {v!r}")
    out = [int(x) for x in vals]
    if any(x != y for x, y in zip(out, vals, strict=True)) or any(x % grid for x in out):
        raise ValueError(f"{what}: {vals} must be integers on the {grid}-unit grid")
    return out


def soul_elements(lay: Any) -> set[str]:
    """Names the layout's soul fields point at (landmarks, irregularities, chokes): the loop must
    not optimise them away (DESIGN_GUIDE.md §9, "lås sjælselementer")."""
    names = set()
    for key, field in (("landmarks", "element"), ("irregularities", "element"), ("chokes", "door")):
        for item in lay.get(key, []) or []:
            if isinstance(item, dict) and item.get(field):
                names.add(str(item[field]))
    return names


def _guard_area(area: Any, lay: Any = None) -> None:
    if area.get("role") in LOCKED_ROLES or area.get("protected"):
        raise ValueError(f"area {area['name']!r} is locked (role {area.get('role')}, FITNESS)")
    if lay is not None and area["name"] in soul_elements(lay):
        raise ValueError(
            f"area {area['name']!r} is a landmark/irregularity in the layout spec (locked)"
        )


def _apply_one(lay: CommentedMap, change: dict[str, Any]) -> str:
    """Mutate `lay` with one change; returns a short description. Raises ValueError."""
    t, p = change["type"], change.get("params", {}) or {}
    grid = int(lay.get("grid", 16))
    if t == "move_corridor":
        area = _find(lay["areas"], str(p["target"]), "area")
        _guard_area(area, lay)
        dx, dy = _vec(p["delta"], 2, grid, "delta")
        x0, y0, x1, y1 = area["rect"]
        area["rect"] = _flow([x0 + dx, y0 + dy, x1 + dx, y1 + dy])
        return f"{area['name']} moved by [{dx}, {dy}]"
    if t == "resize_corridor":
        area = _find(lay["areas"], str(p["target"]), "area")
        _guard_area(area, lay)
        (d,) = _vec(p["length_delta"], 1, grid, "length_delta")
        x0, y0, x1, y1 = area["rect"]
        along_x = (x1 - x0) >= (y1 - y0)
        at_start = str(p.get("end", "end")) in ("start", "min", "west", "south")
        if along_x:
            x0, x1 = (x0 - d, x1) if at_start else (x0, x1 + d)
        else:
            y0, y1 = (y0 - d, y1) if at_start else (y0, y1 + d)
        area["rect"] = _flow([x0, y0, x1, y1])
        return f"{area['name']} {'longer' if d > 0 else 'shorter'} by {abs(d)}"
    if t == "add_cover":
        area = _find(lay["areas"], str(p["zone"]), "area")
        pos = _vec(p["position"], 2, 8, "position")
        size = _vec(p["size"], 3, 8, "size")
        names = {c["name"] for c in lay.get("cover", [])}
        base = str(p.get("name") or f"{area['name']}_cover")
        name, n = base, 2
        while name in names:
            name, n = f"{base}_{n}", n + 1
        lay.setdefault("cover", CommentedSeq())
        lay["cover"].append(_flow_map({"name": name, "area": area["name"], "pos": _flow(pos),
                                       "size": _flow(size)}))  # fmt: skip
        return f"cover {name} {size} at {pos} in {area['name']}"
    if t == "remove_cover":
        cover = _find(lay.get("cover", []), str(p["target"]), "cover")
        if cover.get("protected") or cover["name"] in soul_elements(lay):
            raise ValueError(f"cover {cover['name']!r} is protected (landmark/irregularity)")
        lay["cover"].remove(cover)
        return f"cover {cover['name']} removed"
    if t == "adjust_opening":
        door = _find(lay["doors"], str(p["target"]), "door")
        (w,) = _vec(p["width"], 1, grid, "width")
        door["width"] = w
        if "height" in p:
            (h,) = _vec(p["height"], 1, grid, "height")
            door["height"] = h
        return f"door {door['name']} width {w}" + (
            f", height {p['height']}" if "height" in p else ""
        )
    if t == "move_spawn":
        team = str(p["team"]).upper()
        sp = lay["spawns"][team]
        dx, dy = _vec(p["delta"], 2, 8, "delta")
        ox, oy = list(sp["offset"]) if "offset" in sp else [0, 0]
        sp["offset"] = _flow([ox + dx, oy + dy])
        return f"{team} spawns shifted by [{dx}, {dy}] inside {sp['area']}"
    if t == "add_connection":
        a, b = str(p["from"]), str(p["to"])
        for n in (a, b):
            _find(lay["areas"], n, "area")
        width = _vec(p.get("width", 128), 1, grid, "width")[0]
        names = {d["name"] for d in lay["doors"]}
        name, n = f"d_{a}_{b}", 2
        while name in names:
            name, n = f"d_{a}_{b}_{n}", n + 1
        lay["doors"].append(_flow_map({"name": name, "between": _flow([a, b]), "width": width}))
        return f"door {name} ({width} wide) between {a} and {b}"
    if t == "remove_connection":
        a, b = str(p["from"]), str(p["to"])
        hits = [d for d in lay["doors"] if set(d["between"]) == {a, b}]
        if not hits:
            raise ValueError(f"no door between {a!r} and {b!r}")
        door = hits[0]
        if door.get("protected") or door["name"] in soul_elements(lay):
            raise ValueError(f"door {door['name']!r} is protected (locked topology)")
        lay["doors"].remove(door)
        return f"door {door['name']} between {a} and {b} removed"
    if t == "add_area":
        name = str(p["name"])
        if any(x["name"] == name for x in lay["areas"]):
            raise ValueError(f"an area named {name!r} exists already")
        x0, y0, x1, y1 = _vec(p["rect"], 4, grid, "rect")
        if not (x0 < x1 and y0 < y1):
            raise ValueError("rect must be [x0, y0, x1, y1] with x0 < x1, y0 < y1")
        for other in lay["areas"]:
            ox0, oy0, ox1, oy1 = other["rect"]
            if x0 < ox1 and ox0 < x1 and y0 < oy1 and oy0 < y1:
                raise ValueError(f"rect overlaps area {other['name']!r} (areas are one wall apart)")
        (h,) = _vec(p.get("height", 160), 1, grid, "height")
        area = {"name": name, "rect": _flow([x0, y0, x1, y1]), "height": h,
                "role": str(p.get("role", "corridor"))}  # fmt: skip
        if p.get("floor"):
            area["floor"] = _vec(p["floor"], 1, grid, "floor")[0]
        if p.get("outdoor"):
            area["outdoor"] = True
        lay["areas"].append(_flow_map(area))
        doors = p.get("doors") or []
        if not doors:
            raise ValueError("add_area needs doors: [{to, width}] (a closed room is unreachable)")
        names = {d["name"] for d in lay["doors"]}
        for d in doors:
            to = str(d["to"])
            _find(lay["areas"], to, "area")
            w = _vec(d.get("width", 128), 1, grid, "width")[0]
            dn, k = f"d_{name}_{to}", 2
            while dn in names:
                dn, k = f"d_{name}_{to}_{k}", k + 1
            names.add(dn)
            door = {"name": dn, "between": _flow([name, to]), "width": w}
            if d.get("offset"):
                door["offset"] = _vec(d["offset"], 1, 8, "offset")[0]
            lay["doors"].append(_flow_map(door))
        to = ", ".join(str(d["to"]) for d in doors)
        return f"area {name} {[x0, y0, x1, y1]} added with doors to {to}"
    if t == "remove_area":
        area = _find(lay["areas"], str(p["target"]), "area")
        _guard_area(area, lay)
        name = area["name"]
        lay["areas"].remove(area)
        for key in ("doors",):
            for d in [d for d in lay.get(key, []) if name in d["between"]]:
                if d.get("protected"):
                    raise ValueError(f"door {d['name']!r} to {name} is protected (locked topology)")
                lay[key].remove(d)
        for key in ("cover", "stairs"):
            for it in [it for it in lay.get(key, []) if it.get("area") == name]:
                lay[key].remove(it)
        return f"area {name} removed (now solid), with its doors, cover and stairs"
    raise ValueError(f"change type {t!r} cannot be applied to a layout (phase 6)")


def try_generate(lay: CommentedMap) -> None:
    """Raises SpecError/ValueError if the layout no longer builds."""
    generate(parse_layout(copy.deepcopy(dict(lay))))


def apply_plan(
    layout_text: str, changes: list[dict[str, Any]]
) -> tuple[str, list[dict], list[dict]]:
    """-> (new layout text, applied [change + effect], failed [change + reason])."""
    lay = load(layout_text)
    applied, failed = [], []
    for change in changes:
        trial = load(dump(lay))
        try:
            effect = _apply_one(trial, change)
            try_generate(trial)
        except (ValueError, SpecError, KeyError, TypeError) as exc:
            failed.append({**change, "reason": str(exc)})
            continue
        lay = trial
        applied.append({**change, "effect": effect})
    return dump(lay), applied, failed
