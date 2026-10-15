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
from mapforge.generator.spec import SpecError, expand_macros, parse_layout

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


AREA_KEYS = ("areas", "diagonals", "corridors")  # corridors: angled, from `from` to `to`


def _area(lay: Any, name: str, what: str = "area") -> Any:
    """An area by name: a plain area, a `diagonals:` or an angled `corridors:` corridor (moving
    its rect / ends also moves the wedges, ramp and doors the generator derives)."""
    for it in [x for k in AREA_KEYS for x in lay.get(k) or []]:
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


SOUL_FIELDS = (("landmarks", "element"), ("irregularities", "element"), ("chokes", "door"))


def soul_elements(lay: Any, fields: Any = SOUL_FIELDS) -> set[str]:
    """Names the layout's soul fields point at (landmarks, irregularities, chokes): the loop must
    not optimise them away (DESIGN_GUIDE.md §9, "lås sjælselementer")."""
    names = set()
    for key, field in fields:
        for item in lay.get(key, []) or []:
            if isinstance(item, dict) and item.get(field):
                names.add(str(item[field]))
    return names


def _guard_area(area: Any, lay: Any = None, bend: bool = False) -> None:
    """`bend`: bending an angled irregularity, or taking its bends out again, leaves it an
    angled corridor (the irregularity), so only landmarks and chokes stay locked against it."""
    if area.get("role") in LOCKED_ROLES or area.get("protected"):
        raise ValueError(f"area {area['name']!r} is locked (role {area.get('role')}, FITNESS)")
    if lay is None:
        return
    fields = [f for f in SOUL_FIELDS if f[0] != "irregularities"] if bend else SOUL_FIELDS
    if area["name"] in soul_elements(lay, fields):
        raise ValueError(
            f"area {area['name']!r} is a landmark/irregularity in the layout spec (locked)"
        )


def _new_name(items: Any, base: str) -> str:
    names = {it["name"] for it in items or []}
    name, n = base, 2
    while name in names:
        name, n = f"{base}_{n}", n + 1
    return name


def _guard_spawn(area: Any) -> None:
    if area.get("role") in ("t_spawn", "ct_spawn"):
        raise ValueError(f"no floor changes in spawn area {area['name']!r} (spawns stand there)")


def _apply_one(lay: CommentedMap, change: dict[str, Any]) -> str:
    """Mutate `lay` with one change; returns a short description. Raises ValueError."""
    t, p = change["type"], change.get("params", {}) or {}
    grid = int(lay.get("grid", 16))
    if t == "move_corridor":
        area = _area(lay, str(p["target"]), "area")
        _guard_area(area, lay)
        dx, dy = _vec(p["delta"], 2, grid, "delta")
        if "from" in area:  # an angled corridor: both ends and its bends
            for end in ("from", "to"):
                x, y = area[end]
                area[end] = _flow([x + dx, y + dy])
            if area.get("via"):
                area["via"] = _flow([_flow([x + dx, y + dy]) for x, y in area["via"]])
            return f"{area['name']} moved by [{dx}, {dy}]"
        if area.get("poly"):
            area["poly"] = _flow([_flow([x + dx, y + dy]) for x, y in area["poly"]])
        if area.get("rect") is not None:
            x0, y0, x1, y1 = area["rect"]
            area["rect"] = _flow([x0 + dx, y0 + dy, x1 + dx, y1 + dy])
        return f"{area['name']} moved by [{dx}, {dy}]"
    if t == "resize_corridor":
        area = _area(lay, str(p["target"]), "area")
        _guard_area(area, lay)
        (d,) = _vec(p["length_delta"], 1, grid, "length_delta")
        if "from" in area or area.get("poly"):
            raise ValueError(f"{area['name']} is angled: move it (move_corridor), not resize it")
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
        area = _area(lay, str(p["zone"]), "area")
        pos = _vec(p["position"], 2, 8, "position")
        preset = p.get("preset")
        size = _vec(p["size"], 3, 8, "size") if p.get("size") or not preset else None
        names = {c["name"] for c in lay.get("cover", [])}
        base = str(p.get("name") or f"{area['name']}_cover")
        name, n = base, 2
        while name in names:
            name, n = f"{base}_{n}", n + 1
        lay.setdefault("cover", CommentedSeq())
        item = {"name": name, "area": area["name"], "pos": _flow(pos)}
        if size:
            item["size"] = _flow(size)
        if preset:
            item["preset"] = str(preset)  # crate_stack | barrels | pallets
        if p.get("z"):
            item["z"] = _vec(p["z"], 1, 8, "z")[0]  # raised: platform, bridge, stacked crate
        if p.get("texture"):
            item["texture"] = str(p["texture"])
        if p.get("shape") and p["shape"] != "box":
            item["shape"] = str(p["shape"])
        if p.get("breakable"):
            item["breakable"] = str(p["breakable"])
        lay["cover"].append(_flow_map(item))
        z = f" raised {item['z']}" if "z" in item else ""
        what = f"{preset} {size or ''}".strip() if preset else str(size)
        return f"cover {name} {what} at {pos}{z} in {area['name']}"
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
            _area(lay, n, "area")
        kind = str(p.get("kind", "door"))
        if kind not in ("door", "vent"):
            raise ValueError("add_connection kind: door or vent (a window is add_window)")
        width = _vec(p.get("width", 128 if kind == "door" else 64), 1, grid, "width")[0]
        door = {"name": _new_name(lay["doors"], f"d_{a}_{b}"), "between": _flow([a, b]),
                "width": width}  # fmt: skip
        if kind == "vent":
            door.update(kind="vent", height=_vec(p.get("height", 48), 1, 8, "height")[0])
        if p.get("offset"):
            door["offset"] = _vec(p["offset"], 1, 8, "offset")[0]
        if p.get("arch") and kind == "door":
            door["arch"] = True
        lay["doors"].append(_flow_map(door))
        return f"{kind} {door['name']} ({width} wide) between {a} and {b}"
    if t == "add_window":
        a, b = str(p["from"]), str(p["to"])
        for n in (a, b):
            _area(lay, n, "area")
        door = {"name": _new_name(lay["doors"], f"w_{a}_{b}"), "between": _flow([a, b]),
                "width": _vec(p["width"], 1, grid, "width")[0], "kind": "window",
                "sill": _vec(p["sill"], 1, grid, "sill")[0]}  # fmt: skip
        if p.get("height"):
            door["height"] = _vec(p["height"], 1, grid, "height")[0]
        if p.get("offset"):
            door["offset"] = _vec(p["offset"], 1, 8, "offset")[0]
        if p.get("glass"):
            door["glass"] = True
        lay["doors"].append(_flow_map(door))
        dims = f"{door['width']} wide, sill {door['sill']}"
        return f"window {door['name']} ({dims}) between {a} and {b}"
    if t == "set_gate":
        door = _find(lay["doors"], str(p["target"]), "door")
        gate = str(p["gate"])
        if gate not in ("none", "sliding", "rotating"):
            raise ValueError("gate: none, sliding or rotating")
        if gate == "none":
            door.pop("gate", None)
        else:
            door["gate"] = gate
        return f"door {door['name']} gate {gate}"
    if t == "set_arch":
        door = _find(lay["doors"], str(p["target"]), "door")
        if p.get("arch", True):
            door["arch"] = True
        else:
            door.pop("arch", None)
        return f"door {door['name']} arch {'on' if door.get('arch') else 'off'}"
    if t == "add_ramp":
        area = _area(lay, str(p["zone"]), "area")
        _guard_spawn(area)
        item = {"name": _new_name(lay.get("ramps", []), f"{area['name']}_ramp"),
                "area": area["name"], "axis": str(p["axis"]),
                "rise": _vec(p["rise"], 1, grid, "rise")[0],
                "length": _vec(p["length"], 1, grid, "length")[0],
                "start": _vec(p.get("start", 0), 1, grid, "start")[0]}  # fmt: skip
        lay.setdefault("ramps", CommentedSeq()).append(_flow_map(item))
        return f"ramp {item['name']} rise {item['rise']} over {item['length']} in {area['name']}"
    if t == "add_wedge":
        area = _area(lay, str(p["zone"]), "area")
        _guard_spawn(area)
        item = {"name": _new_name(lay.get("wedges", []), f"{area['name']}_wedge"),
                "area": area["name"], "corner": str(p["corner"]),
                "size": _flow(_vec(p["size"], 2, grid, "size"))}  # fmt: skip
        lay.setdefault("wedges", CommentedSeq()).append(_flow_map(item))
        where = f"the {item['corner']} corner of {area['name']}"
        return f"angled wall {item['name']} {list(item['size'])} in {where}"
    if t == "add_ladder":
        area = _area(lay, str(p["zone"]), "area")
        item = {"name": _new_name(lay.get("ladders", []), f"{area['name']}_ladder"),
                "area": area["name"], "wall": str(p["wall"]),
                "height": _vec(p["height"], 1, 8, "height")[0],
                "pos": _vec(p.get("pos", 0), 1, 8, "pos")[0]}  # fmt: skip
        lay.setdefault("ladders", CommentedSeq()).append(_flow_map(item))
        return f"ladder {item['name']} on the {item['wall']} wall of {area['name']}"
    if t == "set_breakable":
        cover = _find(lay.get("cover", []), str(p["target"]), "cover")
        if cover.get("protected") or cover["name"] in soul_elements(lay):
            raise ValueError(f"cover {cover['name']!r} is protected (landmark/irregularity)")
        mat = str(p["material"])
        if mat == "none":
            cover.pop("breakable", None)
        else:
            cover["breakable"] = mat
        return f"cover {cover['name']} breakable: {mat}"
    if t == "add_hatch":
        lower, upper = (_area(lay, str(p[k]), "area") for k in ("lower", "upper"))
        item = {"name": _new_name(lay.get("hatches", []), f"h_{lower['name']}_{upper['name']}"),
                "lower": lower["name"], "upper": upper["name"],
                "rect": _flow(_vec(p["rect"], 4, 8, "rect"))}  # fmt: skip
        if p.get("ladder"):
            item["ladder"] = str(p["ladder"])
        lay.setdefault("hatches", CommentedSeq()).append(_flow_map(item))
        return f"hatch {item['name']} from {lower['name']} up to {upper['name']}"
    if t == "add_bridge":
        area = _area(lay, str(p["zone"]), "area")
        _guard_spawn(area)
        item = {"name": _new_name(lay.get("bridges", []), f"{area['name']}_bridge"),
                "area": area["name"], "axis": str(p["axis"]),
                "z": _vec(p["z"], 1, 8, "z")[0],
                "width": _vec(p.get("width", 96), 1, 8, "width")[0]}  # fmt: skip
        if p.get("pos"):
            item["pos"] = _vec(p["pos"], 1, 8, "pos")[0]
        if "rail" in p:
            item["rail"] = _vec(p["rail"], 1, 8, "rail")[0]
        lay.setdefault("bridges", CommentedSeq()).append(_flow_map(item))
        return f"bridge {item['name']} across {area['name']} along {item['axis']} at {item['z']}"
    if t == "bend_corridor":
        area = _area(lay, str(p["target"]), "corridor")
        if "from" not in area:
            raise ValueError(f"{area['name']} is not an angled corridor (corridors:)")
        pts = p["via"]
        if pts and not isinstance(pts[0], (list, tuple)):
            pts = [pts]  # one bend given as [x, y]
        via = [_vec(v, 2, grid, "via") for v in pts or []]
        _guard_area(area, lay, bend=True)
        if via:
            area["via"] = _flow([_flow(v) for v in via])
            return f"corridor {area['name']} bent through {via}"
        area.pop("via", None)
        return f"corridor {area['name']} straightened"
    if t == "add_water":
        area = _area(lay, str(p["zone"]), "area")
        _guard_spawn(area)
        item = {"name": _new_name(lay.get("water", []), f"{area['name']}_water"),
                "area": area["name"], "depth": _vec(p["depth"], 1, 8, "depth")[0]}  # fmt: skip
        if p.get("rect"):
            item["rect"] = _flow(_vec(p["rect"], 4, 8, "rect"))
        lay.setdefault("water", CommentedSeq()).append(_flow_map(item))
        return f"water {item['name']} {item['depth']} deep in {area['name']}"
    if t == "remove_element":
        name = str(p["target"])
        for key in ("ramps", "wedges", "ladders", "cover", "stairs", "hatches", "water", "bridges"):
            hit = next((it for it in lay.get(key, []) or [] if it.get("name") == name), None)
            if hit is not None:
                if hit.get("protected") or name in soul_elements(lay):
                    raise ValueError(f"{name!r} is protected (landmark/irregularity)")
                lay[key].remove(hit)
                what = {"ramps": "ramp", "wedges": "angled wall", "ladders": "ladder",
                        "hatches": "hatch", "bridges": "bridge"}.get(key, key)  # fmt: skip
                return f"{what} {name} removed"
        window = next((d for d in lay.get("doors", []) if d.get("name") == name), None)
        if window is not None and window.get("kind") == "window":
            if window.get("protected") or name in soul_elements(lay):
                raise ValueError(f"{name!r} is protected")
            lay["doors"].remove(window)
            return f"window {name} removed"
        raise ValueError(
            f"no ramp/wedge/ladder/cover/stairs/hatch/water/bridge/window named {name!r}"
        )
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
        if any(x["name"] == name for k in AREA_KEYS for x in lay.get(k) or []):
            raise ValueError(f"an area named {name!r} exists already")
        x0, y0, x1, y1 = _vec(p["rect"], 4, grid, "rect")
        if not (x0 < x1 and y0 < y1):
            raise ValueError("rect must be [x0, y0, x1, y1] with x0 < x1, y0 < y1")
        (h,) = _vec(p.get("height", 160), 1, grid, "height")
        fl = _vec(p.get("floor", 0), 1, grid, "floor")[0]
        expanded = expand_macros(dict(lay), grid)["areas"]  # corridors and polygons have rects
        for other in expanded:
            ox0, oy0, ox1, oy1 = other["rect"]
            of = int(other.get("floor", 0))
            above_or_below = fl >= of + int(other.get("height", 192)) + 16 or of >= fl + h + 16
            if x0 < ox1 and ox0 < x1 and y0 < oy1 and oy0 < y1 and not above_or_below:
                raise ValueError(f"rect overlaps area {other['name']!r} (areas are one wall apart)")
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
            _area(lay, to, "area")
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
        area = _area(lay, str(p["target"]), "area")
        _guard_area(area, lay)
        name = area["name"]
        next(lay[k] for k in AREA_KEYS if area in (lay.get(k) or [])).remove(area)
        for key in ("doors",):
            for d in [d for d in lay.get(key, []) if name in d["between"]]:
                if d.get("protected"):
                    raise ValueError(f"door {d['name']!r} to {name} is protected (locked topology)")
                lay[key].remove(d)
        for key in ("cover", "stairs", "ramps", "wedges", "ladders", "weapons", "water", "spots",
                    "bridges"):  # fmt: skip
            for it in [it for it in lay.get(key, []) or [] if it.get("area") == name]:
                lay[key].remove(it)
        for h in [h for h in lay.get("hatches", []) or [] if name in (h["lower"], h["upper"])]:
            lay["hatches"].remove(h)
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
