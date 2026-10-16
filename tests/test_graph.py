"""The editor's graph model (mapforge.graph): schema, folding a layout, diff -> Decide ops."""

from pathlib import Path

import pytest
import yaml

from mapforge import graph as gr

ROOT = Path(__file__).resolve().parents[1]


def _layout(name: str) -> dict:
    return yaml.safe_load((ROOT / "maps" / name / "layout.yaml").read_text(encoding="utf-8"))


def _node(i, role="room", pos=(0, 0), **kw):
    return {"id": i, "name": i, "role": role, "level": 0, "pos": list(pos), **kw}


def _minimal() -> dict:
    nodes = [
        _node("t", "T", (0, -2000)), _node("ct", "CT", (0, 2000)),
        _node("a", "A", (1500, 1500)), _node("b", "B", (-1500, 1500)),
        _node("mid", pos=(0, 0)), _node("tun", pos=(-1500, -500)),
    ]  # fmt: skip
    edges = [
        {"a": "t", "b": "mid", "kind": "corridor"}, {"a": "mid", "b": "a", "kind": "choke"},
        {"a": "t", "b": "tun", "kind": "corridor"}, {"a": "tun", "b": "b", "kind": "choke"},
        {"a": "ct", "b": "a", "kind": "corridor"}, {"a": "ct", "b": "b", "kind": "corridor"},
    ]  # fmt: skip
    return {"version": 1, "map": "de_x", "nodes": nodes, "edges": edges}


def test_validate_accepts_a_minimal_graph():
    g = gr.validate(_minimal())
    assert [n["id"] for n in g["nodes"]] == ["t", "ct", "a", "b", "mid", "tun"]
    assert g["nodes"][4]["size"] == "M" and g["edges"][0]["width"] == "normal"
    assert g["edges"][1]["kind"] == "choke" and g["status"] == "draft"


def test_validate_rejects_missing_spawn():
    g = _minimal()
    g["nodes"] = [n for n in g["nodes"] if n["role"] != "CT"]
    g["edges"] = [e for e in g["edges"] if "ct" not in (e["a"], e["b"])]
    with pytest.raises(ValueError, match="CT"):
        gr.validate(g)


def test_validate_rejects_duplicate_site():
    g = _minimal()
    g["nodes"][3]["role"] = "A"
    with pytest.raises(ValueError, match="A"):
        gr.validate(g)


def test_validate_rejects_dangling_edge_and_self_loop():
    g = _minimal()
    g["edges"].append({"a": "mid", "b": "nope", "kind": "corridor"})
    with pytest.raises(ValueError, match="nope"):
        gr.validate(g)
    g = _minimal()
    g["edges"].append({"a": "mid", "b": "mid", "kind": "corridor"})
    with pytest.raises(ValueError, match="itself"):
        gr.validate(g)


def test_validate_rejects_out_of_bounds_and_long_text():
    g = _minimal()
    g["nodes"][4]["pos"] = [5000, 0]
    with pytest.raises(ValueError, match="4096"):
        gr.validate(g)
    g = _minimal()
    g["nodes"][4]["desc"] = "x" * 2001
    with pytest.raises(ValueError, match="2000"):
        gr.validate(g)


def test_save_and_load_roundtrip(tmp_path):
    saved = gr.save(tmp_path, "de_x", _minimal())
    assert gr.load(tmp_path, "de_x") == saved
    assert gr.path_of(tmp_path, "de_x").read_text(encoding="utf-8").endswith("\n")
    assert gr.load(tmp_path, "de_none") is None


def _connected(g: dict) -> bool:
    nb = {n["id"]: set() for n in g["nodes"]}
    for e in g["edges"]:
        nb[e["a"]].add(e["b"])
        nb[e["b"]].add(e["a"])
    seen, todo = set(), [g["nodes"][0]["id"]]
    while todo:
        k = todo.pop()
        if k not in seen:
            seen.add(k)
            todo += nb[k]
    return seen == set(nb)


def test_fold_keeps_angled_corridor_and_bridge():
    from mapforge.generator.spec import expand_macros

    lay = _layout("de_viaduct01")
    g = gr.from_layout(lay)
    names = {a["name"] for a in expand_macros(lay, 16)["areas"]}
    plain = {n["id"].split("/")[0] for n in g["nodes"]}
    assert plain <= names
    assert _connected(g)
    assert {"T", "CT", "A", "B"} <= {n["role"] for n in g["nodes"]}
    assert any(e.get("via_area") for e in g["edges"])
    assert all(n["role"] in gr.ROLES for n in g["nodes"])
    gr.validate(g)


def test_fold_forge01_has_four_chokes():
    g = gr.from_layout(_layout("de_forge01"))
    assert sum(e["kind"] == "choke" for e in g["edges"]) == 4


def _rects(**r):
    return {k: {"rect": v} for k, v in r.items()}


def test_diff_add_far_connection_is_add_corridor():
    before = gr.validate(_minimal())
    after = gr.validate(_minimal())
    after["edges"].append({"a": "mid", "b": "tun", "kind": "corridor"})
    ops = gr.diff_ops(before, after)
    assert ops == [{"type": "add_corridor",
                    "params": {"from_area": "mid", "to_area": "tun", "width": 160},
                    "why": ops[0]["why"]}]  # fmt: skip


def test_diff_add_near_connection_is_add_connection():
    before = gr.validate(_minimal())
    before["nodes"][4]["rect"] = [-384, -384, 384, 384]
    before["nodes"][5]["rect"] = [400, -384, 1000, 384]  # one wall (16) apart
    after = gr.validate(before)
    after["edges"].append({"a": "mid", "b": "tun", "kind": "corridor"})
    ops = gr.diff_ops(before, after)
    assert [o["type"] for o in ops] == ["add_connection"]
    assert ops[0]["params"] == {"from": "mid", "to": "tun", "width": 160}


def test_diff_remove_folded_corridor_is_remove_area():
    before = gr.validate(_minimal())
    before["edges"][0]["via_area"] = "mid_s"
    after = gr.validate(before)
    after["edges"] = after["edges"][1:]
    ops = gr.diff_ops(before, after)
    assert ops[0]["type"] == "remove_area" and ops[0]["params"]["target"] == "mid_s"
    plain = gr.validate(_minimal())
    gone = gr.validate(_minimal())
    gone["edges"] = gone["edges"][1:]
    assert gr.diff_ops(plain, gone)[0]["type"] == "remove_connection"


def test_diff_moves_and_levels():
    before = gr.validate(_minimal())
    after = gr.validate(_minimal())
    after["nodes"][4]["pos"] = [805, 3]  # mid moved ~800 east
    after["nodes"][0]["pos"] = [0, -2208]  # T spawn moved
    after["nodes"][5]["level"] = 1
    ops = {o["type"]: o for o in gr.diff_ops(before, after)}
    assert ops["move_corridor"]["params"] == {"target": "mid", "delta": [800, 0]}
    assert ops["move_spawn"]["params"]["team"] == "T"
    assert ops["move_spawn"]["params"]["delta"] == [0, -208]
    assert ops["set_level"]["params"] == {"target": "tun", "floor": 160}


def test_diff_rename_and_desc_are_notes_only():
    before = gr.validate(_minimal())
    after = gr.validate(_minimal())
    after["nodes"][4]["name"] = "Mid yard"
    after["nodes"][4]["desc"] = "between the hangars"
    assert gr.diff_ops(before, after) == []
    assert "Mid yard" in gr.summary(gr.diff_ops(before, after), before, after)


def test_diff_width_change_names_the_layout_door():
    g = gr.from_layout(_layout("de_forge01"))
    before = gr.validate(g)
    after = gr.validate(g)
    e = next(x for x in after["edges"] if x["kind"] == "corridor" and x.get("doors"))
    e["width"] = "wide"
    ops = gr.diff_ops(before, after)
    assert ops and all(o["type"] == "adjust_opening" for o in ops)
    assert {o["params"]["target"] for o in ops} <= set(e["doors"]) and ops[0]["params"][
        "width"
    ] == 256
