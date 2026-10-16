"""Graph wishes (drawn in the editor): stored with ops, shown to Decide as requests, allowed past
the per-iteration limits, carried out with add_corridor / set_level."""

import copy
from pathlib import Path

from mapforge import annotations
from mapforge.decide.policy import check_plan, load_fitness
from mapforge.generator.spec import expand_macros
from mapforge.loop.apply import apply_plan, load
from mapforge.topology import extract

ROOT = Path(__file__).resolve().parents[1]
FITNESS = load_fitness()
FITNESS["locked"]["geometry_frozen"] = False


def _graph(extra_edge=None) -> dict:
    n = lambda i, r, p: {"id": i, "role": r, "pos": p}  # noqa: E731
    g = {"nodes": [n("t", "T", [0, -2000]), n("ct", "CT", [0, 2000]), n("a", "A", [1500, 0]),
                   n("b", "B", [-1500, 0])],
         "edges": [{"a": "t", "b": "a"}, {"a": "t", "b": "b"}, {"a": "ct", "b": "a"},
                   {"a": "ct", "b": "b"}]}  # fmt: skip
    if extra_edge:
        g["edges"].append(extra_edge)
    return g


def test_graph_wish_stored_with_ops(tmp_path):
    w = annotations.add_graph_wish(tmp_path, "de_x", _graph(), _graph({"a": "a", "b": "b"}), False)
    assert w["kind"] == "graph" and w["status"] == "open" and w["id"] == 1
    assert w["ops"][0]["type"] == "add_corridor" and "connected" in w["text"]
    assert annotations.load(tmp_path, "de_x")[0]["graph"]["after"]["edges"][-1]["a"] == "a"


def test_graph_wish_on_frozen_map_needs_human(tmp_path):
    w = annotations.add_graph_wish(tmp_path, "de_x", _graph(), _graph({"a": "a", "b": "b"}), True)
    assert w["status"] == "needs_human"
    same = annotations.add_graph_wish(tmp_path, "de_x", _graph(), _graph(), True)
    assert same["status"] == "open"  # nothing structural to wait for


def test_prompt_text_lists_graph_ops(tmp_path):
    annotations.add_graph_wish(tmp_path, "de_x", _graph(), _graph({"a": "a", "b": "b"}), False)
    text = annotations.prompt_text(tmp_path, "de_x", None)
    assert "annotation:1" in text and "REQUESTED" in text and '"add_corridor"' in text


def _plan(*changes):
    return {"summary": "s", "changes": list(changes), "expected_effect": "e", "risk": "r",
            "escalate": False}  # fmt: skip


def _ch(t, addresses=(), **params):
    return {"type": t, "params": params, "rationale": "r", "addresses": list(addresses)}


def test_policy_lifts_limits_for_graph_wish():
    changes = [_ch("add_connection", ["annotation:7"], **{"from": "a", "to": "b"}),
               _ch("add_connection", ["annotation:7"], **{"from": "c", "to": "d"}),
               _ch("move_corridor", ["annotation:7"], target="mid", delta=[800, 0])]  # fmt: skip
    ok = check_plan(_plan(*changes), FITNESS, graph_wishes={"annotation:7"})
    assert ok.ok and len(ok.accepted) == 3
    no = check_plan(_plan(*copy.deepcopy(changes)), FITNESS)
    assert len(no.rejected) == 2  # the second connection and the 800 move


def test_policy_frozen_still_rejects_graph_wish():
    frozen = copy.deepcopy(FITNESS)
    frozen["locked"]["geometry_frozen"] = True
    change = _ch("add_corridor", ["annotation:7"], from_area="a", to_area="b", width=160)
    v = check_plan(_plan(change), frozen, graph_wishes={"annotation:7"})
    assert not v.accepted and "frozen" in v.rejected[0]["reason"]


def _nasa() -> str:
    return (ROOT / "maps" / "de_nasa" / "layout.yaml").read_text(encoding="utf-8")


def test_add_corridor_generates():
    change = _ch("add_corridor", ["annotation:1"], from_area="b_tunnels_s", to_area="t_spawn",
                 width=160)  # fmt: skip
    text, applied, failed = apply_plan(_nasa(), [change])
    assert not failed and applied[0]["effect"].startswith("corridor c_b_tunnels_s_t_spawn")
    topo = extract(dict(load(text)))
    pairs = {frozenset((e["a"], e["b"])) for e in topo["edges"]}
    assert any("c_b_tunnels_s_t_spawn" in p and "t_spawn" in p for p in pairs)


def test_set_level_changes_floor():
    text, applied, failed = apply_plan(_nasa(), [_ch("set_level", target="hangar", floor=32)])
    assert not failed, failed
    hangar = next(a for a in expand_macros(dict(load(text)), 16)["areas"] if a["name"] == "hangar")
    assert hangar["floor"] == 32
