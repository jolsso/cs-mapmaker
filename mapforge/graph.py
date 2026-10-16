"""The editor's graph: maps/<map>/graph.json (spec: docs/superpowers/specs/, graph editor).

A map drawn as rooms (nodes) and connections (edges) in world units. The editor on the local
website writes it (new map) or loads it from the layout (change mode, `from_layout`); a change to
a running map is the difference between two graphs, turned into Decide operators (`diff_ops`).

Nodes: {id, name, role T|CT|A|B|room, level -1|0|1, size S|M|L|XL, outdoor, desc, pos [x, y]}
(+ rect [x0, y0, x1, y1] when the node is a layout area). Edges: {a, b, kind corridor|choke|drop|
ladder, width narrow|normal|wide, len (units) or null, desc, via_area [layout areas it folds]}.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

ROLES = ("T", "CT", "A", "B", "room")
UNIQUE = ("T", "CT", "A", "B")
KINDS = ("corridor", "choke", "drop", "ladder")
SIZES = {"S": 384, "M": 640, "L": 896, "XL": 1152}
WIDTHS = {"narrow": 96, "normal": 160, "wide": 256}
LEVEL_FLOOR = 160  # one level up/down in units
ID = re.compile(r"^[a-z][a-z0-9_/]{0,47}$")
MAX_NODES, MAX_EDGES, MAX_TEXT, BOUND = 200, 400, 2000, 4096
NEAR = 48  # two areas this close (one wall apart + slack) can share a door


def _text(v: Any, what: str) -> str:
    s = str(v or "").strip()
    if len(s) > MAX_TEXT:
        raise ValueError(f"{what}: at most {MAX_TEXT} characters")
    return s


def validate(graph: dict[str, Any]) -> dict[str, Any]:
    """A clean graph from user input (raises ValueError with a readable message)."""
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    nodes_in, edges_in = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes_in, list) or not isinstance(edges_in, list):
        raise ValueError("graph needs nodes and edges lists")
    if len(nodes_in) > MAX_NODES or len(edges_in) > MAX_EDGES:
        raise ValueError(f"at most {MAX_NODES} nodes and {MAX_EDGES} edges")
    nodes, ids = [], set()
    for n in nodes_in:
        nid = str(n.get("id", ""))
        if not ID.match(nid) or nid in ids:
            raise ValueError(f"node id {nid!r}: unique, lower case letters, digits, _ or /")
        role = n.get("role", "room")
        if role not in ROLES:
            raise ValueError(f"node {nid}: role must be one of {', '.join(ROLES)}")
        try:
            x, y = (float(v) for v in n.get("pos", [0, 0]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"node {nid}: pos must be [x, y]") from exc
        if abs(x) > BOUND or abs(y) > BOUND:
            raise ValueError(f"node {nid}: pos outside ±{BOUND}")
        level = int(n.get("level", 0))
        if level not in (-1, 0, 1):
            raise ValueError(f"node {nid}: level must be -1, 0 or 1")
        size = n.get("size") or "M"
        if size not in SIZES:
            raise ValueError(f"node {nid}: size must be one of {', '.join(SIZES)}")
        clean = {
            "id": nid,
            "name": _text(n.get("name") or nid, "name")[:48] or nid,
            "role": role,
            "level": level,
            "size": size,
            "outdoor": bool(n.get("outdoor")),
            "desc": _text(n.get("desc"), f"node {nid} description"),
            "pos": [round(x), round(y)],
        }
        if n.get("rect") is not None:
            clean["rect"] = [int(v) for v in n["rect"]][:4]
        nodes.append(clean)
        ids.add(nid)
    for r in UNIQUE:
        count = sum(n["role"] == r for n in nodes)
        if count != 1:
            raise ValueError(f"the graph needs exactly one {r} ({count} found)")
    edges = []
    for e in edges_in:
        a, b = str(e.get("a", "")), str(e.get("b", ""))
        for end in (a, b):
            if end not in ids:
                raise ValueError(f"edge {a}-{b}: unknown node {end!r}")
        if a == b:
            raise ValueError(f"edge {a}-{b}: a node cannot connect to itself")
        kind = e.get("kind", "corridor")
        if kind not in KINDS:
            raise ValueError(f"edge {a}-{b}: kind must be one of {', '.join(KINDS)}")
        width = e.get("width") or "normal"
        if width not in WIDTHS:
            raise ValueError(f"edge {a}-{b}: width must be one of {', '.join(WIDTHS)}")
        length = e.get("len")
        if length not in (None, ""):
            length = int(float(length))
            if not 64 <= length <= 16384:
                raise ValueError(f"edge {a}-{b}: len 64..16384 units")
        else:
            length = None
        via = e.get("via_area") or []
        via = [via] if isinstance(via, str) else [str(v) for v in via]
        clean = {
            "a": a,
            "b": b,
            "kind": kind,
            "width": width,
            "len": length,
            "desc": _text(e.get("desc"), f"edge {a}-{b} description"),
        }
        if via:
            clean["via_area"] = via
        if e.get("doors"):  # the layout's door names (change mode): what Decide edits
            clean["doors"] = [str(d) for d in e["doors"]][:8]
        edges.append(clean)
    out = {
        "version": 1,
        "map": str(graph.get("map", "")),
        "status": graph.get("status") or "draft",
        "nodes": nodes,
        "edges": edges,
    }
    if out["status"] not in ("draft", "approved"):
        raise ValueError("status must be draft or approved")
    for k in ("suggestions", "estimate"):  # the editor's log and its numbers: kept as given
        if graph.get(k) is not None:
            out[k] = graph[k]
    return out


def path_of(maps_dir: Path, map_name: str) -> Path:
    return maps_dir / map_name / "graph.json"


def load(maps_dir: Path, map_name: str) -> dict[str, Any] | None:
    p = path_of(maps_dir, map_name)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save(maps_dir: Path, map_name: str, graph: dict[str, Any]) -> dict[str, Any]:
    clean = validate({**graph, "map": map_name})
    p = path_of(maps_dir, map_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)
    return clean


# ---------- a layout as a graph (change mode for maps without graph.json) ----------

TOPO_ROLE = {"t_spawn": "T", "ct_spawn": "CT"}
TOPO_KIND = {"hatch": "ladder", "ladder": "ladder", "drop": "drop"}


def _bbox(shapes: list[list[list[float]]]) -> list[int]:
    xs = [p[0] for s in shapes for p in s]
    ys = [p[1] for s in shapes for p in s]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def from_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """The editor's graph of a layout: topology rooms as nodes, plain corridor areas (exactly two
    neighbours) folded into the connection between those neighbours."""
    from mapforge.topology import extract

    topo = extract(layout)
    nodes: dict[str, dict[str, Any]] = {}
    for n in topo["nodes"]:
        role = n.get("site") if n["role"] == "site" else TOPO_ROLE.get(n["role"], "room")
        node = {
            "id": n["id"],
            "name": n["id"],
            "role": role,
            "level": max(-1, min(1, n["level"])),
            "size": n.get("size", "M"),
            "outdoor": any(m.get("outdoor") for m in n["_members"]),
            "desc": "",
            "pos": [int(v) for v in n["_c"]],
            "_topo_role": n["role"],
        }
        if n["_members"]:
            node["rect"] = _bbox([m["shape"] for m in n["_members"]])
        nodes[n["id"]] = node
    # one edge per pair of rooms (two doors between the same rooms are one connection)
    edges: dict[frozenset, dict[str, Any]] = {}
    for e in topo["edges"]:
        if e["kind"] == "window" or e["a"] == e["b"]:
            continue
        k = frozenset((e["a"], e["b"]))
        kind = "choke" if e.get("choke") else TOPO_KIND.get(e["kind"], "corridor")
        w = int(e.get("_w", 160))
        width = "narrow" if w < 128 else "normal" if w <= 192 else "wide"
        if k in edges:
            edges[k]["kind"] = "choke" if kind == "choke" else edges[k]["kind"]
            edges[k]["doors"].append(e["id"])
            continue
        edges[k] = {
            "a": e["a"],
            "b": e["b"],
            "kind": kind,
            "width": width,
            "len": None,
            "desc": "",
            "via_area": [],
            "doors": [e["id"]],
        }
    changed = True
    while changed:  # fold corridor areas between exactly two rooms into one edge
        changed = False
        for nid, node in list(nodes.items()):
            if node["_topo_role"] != "corridor" or node["role"] != "room":
                continue
            mine = [e for k, e in edges.items() if nid in k]
            others = {x for e in mine for x in (e["a"], e["b"]) if x != nid}
            if len(mine) != 2 or len(others) != 2:
                continue
            x, y = sorted(others)
            if frozenset((x, y)) in edges:
                continue  # already connected directly: keep the corridor as a room
            kinds = {e["kind"] for e in mine}
            kind = (
                "choke"
                if "choke" in kinds
                else "drop"
                if "drop" in kinds
                else ("ladder" if "ladder" in kinds else "corridor")
            )
            via = [*mine[0]["via_area"], nid, *mine[1]["via_area"]]
            for e in mine:
                del edges[frozenset((e["a"], e["b"]))]
            doors = [d for e in mine for d in e["doors"]]
            edges[frozenset((x, y))] = {
                "a": x,
                "b": y,
                "kind": kind,
                "width": mine[0]["width"],
                "len": None,
                "desc": "",
                "via_area": via,
                "doors": doors,
            }
            del nodes[nid]
            changed = True
    for n in nodes.values():
        n.pop("_topo_role")
    return {
        "version": 1,
        "map": str(layout.get("name", "")),
        "status": "approved",
        "nodes": list(nodes.values()),
        "edges": [{k: v for k, v in e.items() if k != "via_area" or v} for e in edges.values()],
    }


# ---------- the difference between two graphs as Decide operators ----------


def _snap(v: float, grid: int = 16) -> int:
    return int(math.floor(v / grid + 0.5)) * grid


def _near(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if "rect" not in a or "rect" not in b:
        return False
    ax0, ay0, ax1, ay1 = a["rect"]
    bx0, by0, bx1, by1 = b["rect"]
    gx = max(bx0 - ax1, ax0 - bx1, 0)
    gy = max(by0 - ay1, ay0 - by1, 0)
    overlap_x, overlap_y = min(ax1, bx1) > max(ax0, bx0), min(ay1, by1) > max(ay0, by0)
    return (gx <= NEAR and overlap_y) or (gy <= NEAR and overlap_x)


def diff_ops(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Decide changes that turn `before` into `after` (renames and descriptions are not changes)."""
    before, after = validate(before), validate(after)
    bn = {n["id"]: n for n in before["nodes"]}
    an = {n["id"]: n for n in after["nodes"]}
    key = lambda e: frozenset((e["a"], e["b"]))  # noqa: E731
    be = {key(e): e for e in before["edges"]}
    ae = {key(e): e for e in after["edges"]}
    ops: list[dict[str, Any]] = []

    def op(t: str, why: str, **params: Any) -> None:
        ops.append({"type": t, "params": params, "why": why})

    for nid, n in an.items():  # new rooms first: connections may lead to them
        if nid not in bn:
            half = SIZES[n["size"]] // 2
            x, y = (_snap(v) for v in n["pos"])
            doors = [
                {"to": (e["b"] if e["a"] == nid else e["a"]), "width": WIDTHS[e["width"]]}
                for e in after["edges"]
                if nid in (e["a"], e["b"]) and (e["b"] if e["a"] == nid else e["a"]) in bn
            ]
            op(
                "add_area",
                f"the human added room {n['name']}",
                name=nid,
                rect=[x - half, y - half, x + half, y + half],
                floor=n["level"] * LEVEL_FLOOR,
                outdoor=n["outdoor"],
                doors=doors,
            )
    for k, e in ae.items():
        if k in be or e["a"] not in bn or e["b"] not in bn:
            continue
        a, b = bn[e["a"]], bn[e["b"]]
        why = f"the human connected {a['name']} and {b['name']}"
        if _near(a, b):
            op("add_connection", why, **{"from": e["a"], "to": e["b"], "width": WIDTHS[e["width"]]})
        else:
            op("add_corridor", why, from_area=e["a"], to_area=e["b"], width=WIDTHS[e["width"]])
    for k, e in be.items():
        if k in ae:
            continue
        why = f"the human removed the connection {bn[e['a']]['name']} - {bn[e['b']]['name']}"
        if e.get("via_area"):
            for area in e["via_area"]:
                op("remove_area", why, target=area)
        else:
            op("remove_connection", why, **{"from": e["a"], "to": e["b"]})
    for nid, n in bn.items():
        if nid not in an:
            op("remove_area", f"the human removed {n['name']}", target=nid)
            continue
        m = an[nid]
        dx, dy = _snap(m["pos"][0] - n["pos"][0]), _snap(m["pos"][1] - n["pos"][1])
        if dx or dy:
            if n["role"] in ("T", "CT"):
                op(
                    "move_spawn",
                    f"the human moved the {n['role']} spawn",
                    team=n["role"],
                    delta=[dx, dy],
                )
            else:
                op("move_corridor", f"the human moved {n['name']}", target=nid, delta=[dx, dy])
        if m["level"] != n["level"]:
            op(
                "set_level",
                f"the human put {n['name']} on level {m['level']}",
                target=nid,
                floor=m["level"] * LEVEL_FLOOR,
            )
    for k, e in ae.items():
        old = be.get(k)
        if not old or (old["kind"], old["width"]) == (e["kind"], e["width"]):
            continue
        width = 128 if e["kind"] == "choke" else WIDTHS[e["width"]]
        why = f"the human changed {e['a']} - {e['b']} to {e['kind']}, {e['width']}"
        for door in old.get("doors") or []:
            op("adjust_opening", why, target=door, width=width)
    return ops


def summary(ops: list[dict[str, Any]], before: dict[str, Any], after: dict[str, Any]) -> str:
    """The wish text: one line per change, plus renames and new descriptions (≤ 500 chars)."""
    lines = [o["why"] for o in ops]
    bn = {n["id"]: n for n in before["nodes"]}
    for n in after["nodes"]:
        old = bn.get(n["id"])
        if old and old["name"] != n["name"]:
            lines.append(f"rename {old['name']} to {n['name']}")
        if old and n["desc"] and old.get("desc") != n["desc"]:
            lines.append(f"{n['name']}: {n['desc']}")
    text = "; ".join(lines) or "no change"
    return text if len(text) <= 500 else text[:497] + "..."
