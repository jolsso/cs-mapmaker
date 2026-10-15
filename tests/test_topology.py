"""mapforge.topology: the graph agrees with layout_graph() and carries the schema fields."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mapforge.topology import extract, stats, to_yaml_dict
from mapforge.validate.design import layout_graph

MAPS = sorted(Path("maps").glob("*/layout.yaml"))
KINDS = {"door", "vent", "window", "ramp", "stairs", "ladder", "hatch", "drop"}
ROLES = {"t_spawn", "ct_spawn", "site", "mid", "corridor", "room", "choke", "connector"}


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.parent.name)
def test_same_numbers_as_layout_graph(path: Path) -> None:
    layout = yaml.safe_load(path.read_text(encoding="utf-8"))
    s, g = stats(extract(layout)), layout_graph(layout)
    assert s["site_entrances"] == g["site_entrances"]
    assert s["site_ct_entrance"] == g["site_ct_entrance"]
    assert s["three_way"] == g["three_way"]
    assert len(s["four_way"]) == len(g["four_way"])


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.parent.name)
def test_schema(path: Path) -> None:
    topo = extract(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = {n["id"] for n in topo["nodes"]}
    assert len(ids) == len(topo["nodes"])
    assert {n["role"] for n in topo["nodes"]} <= ROLES
    assert sum(1 for n in topo["nodes"] if n.get("site")) == 2
    for e in topo["edges"]:
        assert e["a"] in ids and e["b"] in ids and e["kind"] in KINDS
        assert ("length" in e) == (e["kind"] != "window")
    clean = to_yaml_dict(topo)
    assert not any(k.startswith("_") for n in clean["nodes"] for k in n)
    assert set(clean["pos"]) == ids


def _topo(name: str) -> dict:
    return extract(yaml.safe_load(Path(f"maps/{name}/layout.yaml").read_text(encoding="utf-8")))


def test_cistern() -> None:
    topo = _topo("de_cistern01")
    nodes = {n["id"]: n for n in topo["nodes"]}
    assert len(nodes) == 20 and len(topo["edges"]) == 23
    assert nodes["b_site"]["level"] == -1 and nodes["b_site"]["site"] == "B"
    assert "b_tunnel_nook" not in nodes  # the nook is part of the tunnel
    kinds = [e["kind"] for e in topo["edges"]]
    assert kinds.count("hatch") == 1 and kinds.count("window") == 1 and kinds.count("ramp") == 5
    assert {e["choke"] for e in topo["edges"] if e.get("choke")} == {
        "Long-porten", "Short-trappen", "Tunnel-mundingen"
    }  # fmt: skip


def test_bridge_is_its_own_node() -> None:
    topo = _topo("de_viaduct01")
    deck = "canal/canal_bridge"
    assert deck in {n["id"] for n in topo["nodes"]}
    assert {e["a"] for e in topo["edges"] if e["b"] == deck} | {
        e["b"] for e in topo["edges"] if e["a"] == deck
    } == {"b_gallery", "a_gallery"}  # fmt: skip


def test_lift_is_a_hatch_edge_marked_for_humans() -> None:
    topo = _topo("de_cistern02")
    lift = next(e for e in topo["edges"] if e["id"] == "h_lift")
    assert lift["kind"] == "hatch" and lift["lift"] == "button"
    # the office is still a dead end: two openings to the site are no extra entrance
    assert stats(topo)["site_entrances"]["B"] == stats(_topo("de_cistern01"))["site_entrances"]["B"]
