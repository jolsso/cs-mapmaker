import numpy as np

from mapforge.analyze.delta import compare
from mapforge.analyze.metrics import (
    bootstrap_median,
    compute,
    dead_zones,
    distance,
    first_contacts,
    kill_concentration,
)

ACFG = {"dead_zone_cell": 64, "dead_zone_min_frac": 0.02, "kill_cell": 128, "bootstrap": 200}
FITNESS = {
    "targets": {"t_winrate": [0.45, 0.55], "site_split_a": [0.35, 0.65], "first_contact_s": [15, 25],
                "dead_zone_share": [0, 0.05], "max_kill_cell_share": [0, 0.10],
                "round_length_median_s": [50, 100]},
    "weights": {"t_winrate": 0.4, "site_split_a": 0.2, "first_contact_s": 0.15,
                "dead_zone_share": 0.15, "max_kill_cell_share": 0.1},
    "min_rounds": 4,
}  # fmt: skip


def test_distance_is_zero_inside_and_scaled_outside():
    assert distance(0.5, [0.45, 0.55]) == 0
    assert round(distance(0.35, [0.45, 0.55]), 6) == 1.0  # one range width below
    assert distance(None, [0, 1]) is None


def test_bootstrap_median_is_reproducible():
    a = bootstrap_median([10, 12, 14, 30], 500)
    assert a == bootstrap_median([10, 12, 14, 30], 500)
    assert a[0] == 13 and a[1][0] <= 13 <= a[1][1]


def test_first_contact_uses_event_or_enemy_damage():
    rounds = [{"run_id": "r", "round": 1}, {"run_id": "r", "round": 2}]
    ev = [
        {"run_id": "r", "round": 1, "type": "damage", "t": 5.0, "actor_team": "T", "target_team": "T"},
        {"run_id": "r", "round": 1, "type": "first_contact", "t": 18.0, "actor_team": "T", "target_team": "CT"},
        {"run_id": "r", "round": 2, "type": "damage", "t": 21.0, "actor_team": "CT", "target_team": "T"},
    ]  # fmt: skip
    assert first_contacts(ev, rounds) == [18.0, 21.0]


def test_dead_zones_ignore_thin_wall_strips():
    # a 128x128 floor of 16-unit nodes = four 64-cells; traffic only in the left half
    xs, ys = np.meshgrid(np.arange(0, 128, 16), np.arange(0, 128, 16))
    walk = np.column_stack([xs.ravel(), ys.ravel()]).astype(float)
    strip = np.array([[200.0, 0.0], [200.0, 16.0]])  # 2 nodes in another cell: too thin
    pos = np.array([[10.0, 10.0]] * 50 + [[10.0, 90.0]] * 50)
    dz = dead_zones(np.vstack([walk, strip]), pos, 64, 0.02)
    assert dz["walkable_cells"] == 4 and dz["share"] == 0.5


def test_kill_concentration():
    kills = np.array([[10.0, 10.0]] * 3 + [[1000.0, 1000.0]])
    kc = kill_concentration(kills, 128)
    assert kc["share"] == 0.75 and kc["top"][0]["kills"] == 3


def _data(t_wins: int, n: int):
    rounds = [{"run_id": "r", "round": i, "winner": "T" if i < t_wins else "CT", "reason": "elimination",
               "plant_site": "A" if i % 2 else "B", "start_time": 0.0, "end_time": 70.0}
              for i in range(n)]  # fmt: skip
    events = [{"run_id": "r", "round": i, "type": "first_contact", "t": 20.0, "actor_team": "T",
               "target_team": "CT", "tx": float(i * 300), "ty": 0.0} for i in range(n)]  # fmt: skip
    events += [{**e, "type": "kill"} for e in events]
    positions = [{"run_id": "r", "round": i, "alive": 1, "x": float(x), "y": 0.0}
                 for i in range(n) for x in range(0, 640, 16)]  # fmt: skip
    return {"rounds": rounds, "events": events, "positions": positions}, rounds


def test_compute_scores_and_delta_needs_more_than_noise():
    walk = np.array([[x, y] for x in range(0, 640, 16) for y in range(0, 64, 16)], dtype=float)
    data, valid = _data(5, 10)
    m = compute(data, valid, walk, FITNESS, ACFG)
    assert m["metrics"]["t_winrate"]["value"] == 0.5 and m["metrics"]["t_winrate"]["distance"] == 0
    assert m["metrics"]["first_contact_s"]["value"] == 20 and m["enough_rounds"]
    assert m["metrics"]["max_kill_cell_share"]["value"] == 0.1  # 10 kills in 10 cells: on the bound
    assert m["score_parts"]["max_kill_cell_share"] == 0
    lop = compute(*_data(0, 10), walk, FITNESS, ACFG)
    assert lop["score"] > m["score"]
    assert compare(lop, m)["metrics"]["t_winrate"]["verdict"] == "støj"  # n=10: intervals overlap
    big, big_lop = (
        compute(*_data(20, 40), walk, FITNESS, ACFG),
        compute(*_data(2, 40), walk, FITNESS, ACFG),
    )
    d = compare(big_lop, big)
    assert d["metrics"]["t_winrate"]["verdict"] == "værre"
    assert compare(m, m)["verdict"] == "støj"
