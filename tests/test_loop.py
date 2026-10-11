from pathlib import Path

import yaml

from mapforge.config import load_config
from mapforge.loop.apply import apply_plan
from mapforge.loop.run import Loop

LAYOUT = (Path(__file__).resolve().parent.parent / "maps" / "de_forge01" / "layout.yaml").read_text(
    encoding="utf-8"
)


def test_apply_keeps_comments_and_applies_valid_changes():
    new, applied, failed = apply_plan(
        LAYOUT,
        [
            {
                "type": "add_cover",
                "params": {"zone": "mid_top", "position": [0, 656], "size": [64, 64, 64]},
            },
            {"type": "adjust_opening", "params": {"target": "d_mid_b1", "width": 160}},
            {"type": "move_spawn", "params": {"team": "CT", "delta": [64, 0]}},
        ],
    )
    assert [a["type"] for a in applied] == [
        "add_cover",
        "adjust_opening",
        "move_spawn",
    ] and not failed
    assert "# chokepoint A long" in new  # comments survive the round trip
    data = yaml.safe_load(new)
    assert any(c["name"] == "mid_top_cover" for c in data["cover"])
    assert next(d for d in data["doors"] if d["name"] == "d_mid_b1")["width"] == 160
    assert data["spawns"]["CT"]["offset"] == [64, 0]


def test_apply_refuses_locked_and_ungeneratable_changes():
    _, applied, failed = apply_plan(
        LAYOUT,
        [
            {"type": "move_corridor", "params": {"target": "a_site", "delta": [16, 0]}},
            {"type": "remove_connection", "params": {"from": "long_ec_n", "to": "a_site"}},
            {"type": "move_corridor", "params": {"target": "mid_to_b", "delta": [16, 0]}},
            {"type": "adjust_opening", "params": {"target": "d_mid_b1", "width": 100}},
        ],
    )
    reasons = [f["reason"] for f in failed]
    assert not applied and len(failed) == 4
    assert "locked" in reasons[0] and "protected" in reasons[1]
    assert "wall" in reasons[2] and "grid" in reasons[3]


def _loop(tmp_path) -> Loop:
    loop = Loop(load_config(), "de_x")
    loop.root, loop.state_file = tmp_path, tmp_path / "loop.json"
    loop.state = {"iteration": "003", "first_iteration": "001", "history": [{"iteration": "003", "reached": "simulate"}],
                  "started_ts": __import__("time").time(), "rollback": False, "best": None,
                  "counters": {"hard_fail": 0, "review_fail": 0, "since_best": 0, "targets_met": 0, "measured": 0}}  # fmt: skip
    return loop


def test_evaluate_tracks_best_and_rollback(tmp_path):
    loop = _loop(tmp_path)
    loop._evaluate({"score": 0.5, "metrics": {}}, 1)
    assert loop.state["best"]["score"] == 0.5 and not loop.state["rollback"]
    loop.state["iteration"] = "004"
    loop._evaluate({"score": 0.9, "delta": {"verdict": "værre"}, "metrics": {}}, 1)
    assert loop.state["best"]["iteration"] == "003" and loop.state["rollback"]
    assert loop.state["counters"]["since_best"] == 1
    loop.state["iteration"] = "005"
    loop._evaluate(
        {"score": 0.2, "delta": {"verdict": "bedre"}, "targets_met": True, "metrics": {}}, 1
    )
    assert loop.state["best"]["iteration"] == "005" and not loop.state["rollback"]


def test_stop_reasons(tmp_path):
    loop = _loop(tmp_path)
    assert loop.stop_reason(changed=True) is None
    assert "ingen ændringer" in loop.stop_reason(changed=False)
    loop.state["counters"]["targets_met"] = 2
    assert "Gate B" in loop.stop_reason(changed=True)
    loop.state["counters"].update(targets_met=0, hard_fail=3)
    assert "hårde krav" in loop.stop_reason(changed=True)
    loop.state["counters"].update(hard_fail=0, measured=6, since_best=5)
    assert "plateau" in loop.stop_reason(changed=True)


def test_decide_stops_on_plateau_before_asking_for_a_plan(tmp_path, monkeypatch):
    monkeypatch.setattr("mapforge.site.build.refresh_site", lambda cfg=None: None)
    loop = _loop(tmp_path)
    loop.state["counters"].update(measured=6, since_best=5)
    assert loop.step_decide() == 0
    assert loop.state["status"] == "stopped" and "plateau" in loop.state["stop_reason"]
    assert not (loop.it_dir / "decide_prompt.md").exists()


def test_add_area_needs_a_shared_wall_and_no_overlap():
    room = {"name": "test_room", "rect": [-1520, 400, -976, 912], "height": 160,
            "doors": [{"to": "b_tunnel_n", "width": 128}, {"to": "mid_top", "width": 128}]}  # fmt: skip
    new, applied, failed = apply_plan(LAYOUT, [{"type": "add_area", "params": room}])
    assert len(applied) == 1 and not failed
    assert any(a["name"] == "test_room" for a in yaml.safe_load(new)["areas"])
    far = {**room, "rect": [-1264, 400, -976, 912]}  # not one wall from b_tunnel_n
    over = {**room, "rect": [-1600, 400, -976, 912]}  # overlaps b_tunnel_n
    _, applied, failed = apply_plan(
        LAYOUT, [{"type": "add_area", "params": far}, {"type": "add_area", "params": over}]
    )
    assert (
        not applied and "share a wall" in failed[0]["reason"] and "overlaps" in failed[1]["reason"]
    )


def test_policy_allows_area_changes_only_on_a_human_wish():
    from mapforge.decide.policy import check_plan, load_fitness

    plan = {"summary": "s", "expected_effect": "e", "risk": "r", "escalate": False,
            "changes": [{"type": "remove_area", "params": {"target": "mid_to_b"}, "rationale": "x"},
                        {"type": "remove_area", "params": {"target": "mid_to_b"}, "rationale": "x",
                         "addresses": ["annotation:4"]}]}  # fmt: skip
    v = check_plan(plan, load_fitness(), 6)
    assert len(v.rejected) == 1 and "human" in v.rejected[0]["reason"] and len(v.accepted) == 1
