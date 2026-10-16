"""An approved editor graph becomes a layout.yaml (mapforge.fromgraph)."""

import json
from collections import deque

import pytest

from mapforge import fromgraph
from mapforge.generator.spec import expand_macros
from mapforge.loop.apply import try_generate
from mapforge.topology import extract


def _n(i, role, pos, **kw):
    return {"id": i, "name": i, "role": role, "pos": list(pos), **kw}


def graph() -> dict:
    """A small three-lane-ish map that is not de_forge01's grid."""
    return {
        "version": 1, "map": "de_fg", "status": "approved",
        "nodes": [
            _n("t", "T", (0, -2400)), _n("ct", "CT", (800, 2200)),
            _n("a", "A", (2000, 1200), size="L", outdoor=True), _n("b", "B", (-1800, 1400)),
            _n("mid", "room", (0, 0), size="L", outdoor=True), _n("tun", "room", (-1900, -900)),
            _n("long", "room", (2100, -900), level=1),
        ],
        "edges": [
            {"a": "t", "b": "mid"}, {"a": "mid", "b": "a", "kind": "choke"},
            {"a": "mid", "b": "b", "kind": "choke"}, {"a": "t", "b": "tun"},
            {"a": "tun", "b": "b", "kind": "choke"}, {"a": "t", "b": "long"},
            {"a": "long", "b": "a", "kind": "choke"}, {"a": "ct", "b": "a"},
            {"a": "ct", "b": "b", "len": 4000},
        ],
    }  # fmt: skip


def _route(topo: dict, a: str, b: str) -> bool:
    nb: dict[str, set] = {}
    for e in topo["edges"]:
        if e["kind"] != "window":
            nb.setdefault(e["a"], set()).add(e["b"])
            nb.setdefault(e["b"], set()).add(e["a"])
    seen, todo = {a}, deque([a])
    while todo:
        k = todo.popleft()
        if k == b:
            return True
        for m in nb.get(k, ()):
            if m not in seen and (m == b or m.startswith("c_")):  # only through corridors
                seen.add(m)
                todo.append(m)
    return False


def test_minimal_graph_builds():
    lay, report = fromgraph.build_layout(graph())
    try_generate(lay)
    assert lay["sites"] == {"A": "a", "B": "b"}
    assert lay["spawns"]["T"] == {"area": "t", "count": 16} and lay["spawns"]["CT"]["count"] == 16
    long_ = next(a for a in lay["areas"] if a["name"] == "long")
    assert long_["floor"] == 160 and next(a for a in lay["areas"] if a["name"] == "a")["outdoor"]


def test_every_edge_becomes_a_route():
    lay, _ = fromgraph.build_layout(graph())
    topo = extract(lay)
    for e in graph()["edges"]:
        assert _route(topo, e["a"], e["b"]), (e["a"], e["b"])


def test_overlapping_rooms_are_pushed_apart():
    g = graph()
    g["nodes"][5]["pos"] = [-1700, -800]  # tun nearly on top of ...
    g["nodes"].append(_n("tun2", "room", (-1750, -850)))
    g["edges"].append({"a": "tun", "b": "tun2"})
    lay, report = fromgraph.build_layout(g)
    assert report["moved"]
    try_generate(lay)
    rects = [a["rect"] for a in expand_macros(lay, 16)["areas"] if a["name"] in ("tun", "tun2")]
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = rects
    assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0


def test_choke_becomes_a_narrow_door():
    lay, _ = fromgraph.build_layout(graph())
    chokes = {c["door"] for c in lay["chokes"]}
    assert len(chokes) == 4
    doors = {d["name"]: d for d in expand_macros(lay, 16)["doors"]}
    assert all(doors[c]["width"] == 128 for c in chokes)


def test_edge_lengths_within_tolerance():
    _, report = fromgraph.build_layout(graph())
    assert len(report["edges"]) == len(graph()["edges"])
    off = [e for e in report["edges"] if not e["ok"]]
    for e in off:  # whatever Fit could not bring within 10 % is named in the report
        assert any(f"c_{e['a']}_{e['b']} is" in n for n in report["notes"]), e
    assert len(off) <= 3


def test_descriptions_are_kept_as_notes():
    g = graph()
    g["nodes"][3]["desc"] = "the satellite in a clean-room lab"
    lay, _ = fromgraph.build_layout(g, {"concept": "Stop the launch"})
    assert lay["notes"]["b"] == "the satellite in a clean-room lab"
    assert lay["concept"] == "Stop the launch"
    try_generate(lay)


def test_refuses_to_overwrite_layout(tmp_path, monkeypatch):
    from mapforge.config import load_config

    cfg = load_config()
    monkeypatch.setitem(cfg.data["paths"], "maps_dir", str(tmp_path / "maps"))
    monkeypatch.setitem(cfg.data["paths"], "build_dir", str(tmp_path / "build"))
    monkeypatch.setattr(fromgraph, "load_config", lambda: cfg)
    d = tmp_path / "maps" / "de_fg"
    d.mkdir(parents=True)
    (d / "graph.json").write_text(json.dumps(graph()), encoding="utf-8")
    assert fromgraph.main(["--map", "de_fg"]) == 0
    assert (d / "layout.yaml").is_file()
    assert (tmp_path / "build" / "de_fg" / "fromgraph_report.json").is_file()
    assert fromgraph.main(["--map", "de_fg"]) == 1  # exists: needs --force
    assert fromgraph.main(["--map", "de_fg", "--force"]) == 0


def test_draft_graph_is_refused():
    g = graph()
    g["status"] = "draft"
    with pytest.raises(ValueError, match="approved"):
        fromgraph.build_layout(g)


def test_ct_reaches_both_sites_through_bent_corridors():
    from mapforge.topology import stats

    lay, _ = fromgraph.build_layout(graph())
    assert stats(extract(lay))["site_ct_entrance"] == {"A": True, "B": True}


def test_a_short_corridor_between_levels_is_not_too_steep():
    g = graph()
    g["nodes"].append(_n("loft", "room", (0, 900), level=1))  # 900 above mid: a short corridor
    g["edges"].append({"a": "mid", "b": "loft"})
    lay, report = fromgraph.build_layout(g)
    try_generate(lay)  # no "ramp needs rise <= length / 2"
    c = next(c for c in lay["corridors"] if c["name"] == "c_mid_loft")
    pts = [c["from"], *c.get("via", []), c["to"]]
    length = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(pts, pts[1:], strict=False))
    assert c.get("rise") == 0 or length >= 2 * 160


def test_no_free_route_still_avoids_rooms():
    # x and y straight across each other with a room in between and a corridor around it taken
    rects = {"x": [0, 0, 640, 640], "y": [2000, 0, 2640, 640], "wall": [900, -400, 1700, 1100]}
    placed = [[640, -4000, 2000, 4000]]  # corridors fill the whole gap between x and y
    route, free = fromgraph._route({"a": "x", "b": "y"}, rects, 160, {}, placed)
    assert not free
    pts = route[4]
    boxes = [fromgraph._seg_box(p, q, 160) for p, q in zip(pts, pts[1:], strict=False)]
    assert not any(fromgraph._overlap(b, rects["wall"], 16) for b in boxes)
