import numpy as np

from mapforge.validate.design import design_findings, layout_graph

CFG = {"rotation_s": [8, 20], "territory_max_share": 0.85, "spawn_to_spawn": "error",
       "t_spawn_to_site": "warning", "long_sightline_units": 1500, "close_sightline_units": 500,
       "min_share_long": 0.02, "min_share_close": 0.05, "site_entrances": [2, 3], "four_way": "warning"}  # fmt: skip

LAYOUT = {
    "areas": [{"name": n, "rect": [0, 0, 16, 16], "role": r} for n, r in
              [("t", "t_spawn"), ("ct", "ct_spawn"), ("a", "site"), ("b", "site"), ("mid", "mid"),
               ("l", "corridor"), ("r", "corridor")]],
    "doors": [{"between": p} for p in [("t", "l"), ("t", "r"), ("t", "mid"), ("mid", "l"), ("mid", "r"),
                                       ("l", "a"), ("r", "b"), ("ct", "a"), ("ct", "b"), ("mid", "ct")]],
    "sites": {"A": "a", "B": "b"},
}  # fmt: skip


def test_layout_graph_counts_entrances_and_junctions():
    g = layout_graph(LAYOUT)
    assert g["site_entrances"] == {"A": 2, "B": 2}
    assert g["site_ct_entrance"] == {"A": True, "B": True}
    assert g["four_way"] == ["mid"]  # t, l, r, ct


def test_design_findings_severities():
    stats = {
        "rotation": [{"sites": "A-B", "seconds": 25.0}],
        "spawn_sightlines": {"spawn_to_spawn": [[[0, 0, 0], [1, 1, 1]]], "spawn_to_spawn_pairs": 3,
                             "t_spawn_to_site": {"A": 2, "B": 0}},
        "territory": {"t_share": 0.9, "ct_share": 0.1},
        "sightlines": {"spots": 100, "share_long": 0.0, "share_close": 0.5},
        "layout_graph": layout_graph(LAYOUT),
    }  # fmt: skip
    own = {f.rule: f.severity for f in design_findings(stats, CFG, reference=False)}
    assert own["spawn_sightline"] == "error" and own["territory"] == "error"
    assert own["rotation_time"] == "warning" and own["spawn_sees_site"] == "warning"
    assert own["no_long_sightline"] == "warning" and own["four_way_junction"] == "warning"
    assert "no_close_quarters" not in own
    ref = design_findings(stats, CFG, reference=True)
    assert {f.severity for f in ref} == {"info"}


def test_bfs_distances():
    from mapforge.validate.design import _dists

    class G:
        feet = np.zeros((4, 3))
        edges = np.array([[0, 1], [1, 2], [2, 3], [1, 0], [2, 1], [3, 2]])

    d = _dists(G(), [0])
    assert d.tolist() == [0, 1, 2, 3]
