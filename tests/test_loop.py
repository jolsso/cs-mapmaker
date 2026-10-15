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


def test_apply_new_geometry_change_types():
    changes = [
        {"type": "add_cover", "params": {"zone": "mid_top", "position": [0, 656],
                                         "size": [128, 128, 16], "z": 96}},
        {"type": "add_window", "params": {"from": "mid", "to": "mid_top", "width": 96,
                                          "sill": 96, "height": 64, "offset": 256, "glass": True}},
        {"type": "add_connection", "params": {"from": "mid_to_b", "to": "t_b_cut", "kind": "vent",
                                              "width": 64, "offset": 64}},
        {"type": "set_gate", "params": {"target": "d_t_mid", "gate": "sliding"}},
        {"type": "add_ramp", "params": {"zone": "mid_s", "axis": "+y", "rise": 32, "length": 64,
                                        "start": 256}},
        {"type": "add_wedge", "params": {"zone": "mid_top", "corner": "sw", "size": [128, 128]}},
        {"type": "add_ladder", "params": {"zone": "mid_top", "wall": "+y", "height": 112,
                                          "pos": -400}},
        {"type": "remove_element", "params": {"target": "mid_top_wedge"}},
        {"type": "add_ramp", "params": {"zone": "t_spawn", "axis": "+y", "rise": 32,
                                        "length": 64}},
    ]  # fmt: skip
    new, applied, failed = apply_plan(LAYOUT, changes)
    assert [f["type"] for f in failed] == ["add_ramp"] and "spawn" in failed[0]["reason"]
    assert len(applied) == 8
    data = yaml.safe_load(new)
    win = next(d for d in data["doors"] if d["name"] == "w_mid_mid_top")
    assert win["kind"] == "window" and win["glass"] and win["sill"] == 96
    assert next(d for d in data["doors"] if d["name"] == "d_t_mid")["gate"] == "sliding"
    assert not data.get("wedges") and data["ramps"][0]["area"] == "mid_s"
    assert next(c for c in data["cover"] if c.get("z") == 96)["area"] == "mid_top"


def test_apply_shapes_breakables_water_and_hatch_checks():
    changes = [
        {"type": "add_cover", "params": {"zone": "mid_top", "position": [0, 656],
                                         "size": [64, 64, 128], "shape": "octagon"}},
        {"type": "add_cover", "params": {"zone": "mid", "position": [128, 128],
                                         "size": [64, 64, 64], "breakable": "wood"}},
        {"type": "set_breakable", "params": {"target": "mid_top_cover", "material": "metal"}},
        {"type": "add_water", "params": {"zone": "mid", "depth": 24, "rect": [-256, -256, 0, 0]}},
        {"type": "add_hatch", "params": {"lower": "mid", "upper": "mid_top",
                                         "rect": [0, 0, 64, 64], "ladder": "+x"}},
    ]  # fmt: skip
    new, applied, failed = apply_plan(LAYOUT, changes)
    assert [a["type"] for a in applied] == ["add_cover", "add_cover", "set_breakable", "add_water"]
    assert failed[0]["type"] == "add_hatch" and "inside both" in failed[0]["reason"]
    data = yaml.safe_load(new)
    assert any(c.get("shape") == "octagon" for c in data["cover"])
    assert next(c for c in data["cover"] if c["name"] == "mid_top_cover")["breakable"] == "metal"
    assert data["water"][0]["depth"] == 24


def test_policy_counts_windows_per_iteration_and_uses_per_map_locks():
    from mapforge.decide.policy import check_plan, load_fitness, locked_for

    f = load_fitness()
    w = {"type": "add_window", "rationale": "r",
         "params": {"from": "a", "to": "b", "width": 96, "sill": 80}}  # fmt: skip
    plan = {"summary": "s", "changes": [w, w], "expected_effect": "e", "risk": "r",
            "escalate": False}  # fmt: skip
    v = check_plan(plan, f)
    assert len(v.accepted) == 1 and "at most 1" in v.rejected[0]["reason"]
    assert locked_for(f, "de_vault01")["topology"] == ""
    assert locked_for(f, "de_forge01") == f["locked"]


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


def test_review_is_reused_for_an_identical_map(tmp_path, monkeypatch):
    import json

    loop = _loop(tmp_path)
    loop.map = "de_x"
    dirs = [tmp_path / n for n in ("001", "002", "003")]
    for d in dirs:
        d.mkdir()
    (dirs[0] / "de_x.map").write_text("A")
    (dirs[1] / "de_x.map").write_text("B")
    (dirs[2] / "de_x.map").write_text("B")
    for d, passed in ((dirs[0], True), (dirs[1], True)):
        (d / "review_answer.json").write_text("{}")
        (d / "review.json").write_text(json.dumps({"passed": passed}))
    monkeypatch.setattr("mapforge.loop.run.iterations", lambda cfg, m: dirs)
    loop.state["iteration"] = "003"
    monkeypatch.setattr(type(loop), "it_dir", property(lambda self: dirs[2]))
    assert loop._reusable_review() == dirs[1] / "review_answer.json"
    (dirs[1] / "review.json").write_text(json.dumps({"passed": False}))
    assert loop._reusable_review() is None


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


def test_apply_moves_angled_areas_and_adds_bridges():
    from test_generator_angled import ANGLED

    text = yaml.safe_dump(ANGLED, sort_keys=False)
    changes = [
        {"type": "move_corridor", "params": {"target": "hex", "delta": [0, 16]}},
        {"type": "resize_corridor", "params": {"target": "t_long", "length_delta": 64}},
        {"type": "add_bridge", "params": {"zone": "street", "axis": "y", "z": 176,
                                          "width": 96, "pos": -512}},
        {"type": "add_bridge", "params": {"zone": "street", "axis": "y", "z": 48}},
        {"type": "remove_element", "params": {"target": "deck"}},
        {"type": "move_corridor", "params": {"target": "t_long", "delta": [16, 0]}},
        {"type": "bend_corridor", "params": {"target": "t_long", "via": [-1088, 576]}},
        {"type": "bend_corridor", "params": {"target": "street", "via": [0, 0]}},
    ]  # fmt: skip
    new, applied, failed = apply_plan(text, changes)
    assert [f["type"] for f in failed] == [
        "move_corridor", "resize_corridor", "add_bridge", "bend_corridor"
    ]  # fmt: skip
    assert "not an angled corridor" in failed[3]["reason"]
    assert "share a wall" in failed[0]["reason"]  # the hex no longer sits one wall from CT
    assert "angled" in failed[1]["reason"] and "free under" in failed[2]["reason"]
    data = yaml.safe_load(new)
    assert [b["name"] for b in data["bridges"]] == ["street_bridge"]
    t_long = next(c for c in data["corridors"] if c["name"] == "t_long")
    assert t_long["to"] == [-944, 960] and t_long["via"] == [[-1088, 576]]


def test_budget_counts_active_run_time_only(tmp_path, monkeypatch):
    import time

    loop = _loop(tmp_path)
    monkeypatch.setattr("mapforge.site.build.refresh_site", lambda cfg=None: None)
    loop.state["started_ts"] = time.time() - 3 * 24 * 3600  # started three days ago, then cut off
    assert loop.stop_reason(changed=True) is None
    loop._mark = time.time() - 2 * 3600  # this run has been busy for two hours
    loop.save()
    assert 7100 < loop.state["active_s"] < 7300
    loop.state["active_s"] = 13 * 3600
    assert "aktiv køretid" in loop.stop_reason(changed=True)


def test_loop_refuses_to_start_without_docker(tmp_path, monkeypatch, capsys):
    import mapforge.loop.run as loop_run

    monkeypatch.setattr(loop_run, "docker_problem", lambda: "Docker svarer ikke")
    monkeypatch.setattr(
        loop_run.Loop, "init", lambda self, force: (_ for _ in ()).throw(AssertionError)
    )
    assert loop_run.main(["--map", "de_nothing", "--init"]) == 1
    assert "Docker svarer ikke" in capsys.readouterr().err


def test_stop_says_why_proposed_changes_did_not_apply(tmp_path, monkeypatch):
    import json

    loop = _loop(tmp_path)
    monkeypatch.setattr(type(loop), "it_dir", property(lambda self: tmp_path))
    (tmp_path / "applied.json").write_text(json.dumps({"failed": [
        {"type": "bend_corridor", "reason": "area 'b_long' is a landmark/irregularity (locked)"}
    ], "rejected_by_policy": []}))  # fmt: skip
    reason = loop.stop_reason(changed=False)
    assert "kunne anvendes" in reason and "irregularity" in reason


def test_bend_is_allowed_on_an_irregularity_but_not_a_straightening():
    from test_generator_angled import ANGLED

    lay = {**ANGLED, "irregularities": [{"element": "t_long", "purpose": "skrå korridor"}]}
    text = yaml.safe_dump(lay, sort_keys=False)
    bend = {"type": "bend_corridor", "params": {"target": "t_long", "via": [-1088, 576]}}
    move = {"type": "move_corridor", "params": {"target": "t_long", "delta": [16, 0]}}
    _, applied, failed = apply_plan(text, [move])
    assert not applied and "irregularity" in failed[0]["reason"]  # other changes stay locked
    new, _, _ = apply_plan(yaml.safe_dump(ANGLED, sort_keys=False), [move])  # where a bend fits
    lay = {**yaml.safe_load(new), "irregularities": lay["irregularities"]}
    new, applied, failed = apply_plan(yaml.safe_dump(lay, sort_keys=False), [bend])
    assert not failed and yaml.safe_load(new)["corridors"][0]["via"] == [[-1088, 576]]
    straighten = {"type": "bend_corridor", "params": {"target": "t_long", "via": []}}
    _, applied, failed = apply_plan(new, [straighten])
    assert not applied and "irregularity" in failed[0]["reason"]
    lay["landmarks"] = [{"name": "Langbanen", "element": "t_long"}]
    _, applied, failed = apply_plan(yaml.safe_dump(lay, sort_keys=False), [bend])
    assert not applied and "landmark" in failed[0]["reason"]


def test_decide_hears_why_the_smoke_test_failed(tmp_path, monkeypatch):
    import json

    loop = _loop(tmp_path)
    monkeypatch.setattr(type(loop), "it_dir", property(lambda self: tmp_path))
    (tmp_path / "sim").mkdir()
    (tmp_path / "sim" / "simulation.json").write_text(json.dumps({"ok": False, "smoke": {
        "ok": False, "checks": {"bots_move": {"ok": True},
                                "sites_reached": {"ok": False, "samples_per_site": {"A": 38, "B": 0}}}},
        "graph_attempts": [{"distance": 80, "samples_per_site": {"A": 0, "B": 0}}]}))  # fmt: skip
    loop.state["started"] = "2026-10-15 08:00:00"
    text = loop.loop_context()
    assert "Smoke-testen fejlede" in text and '"B": 0' in text and "80 units" in text
    assert "bots_move" not in text
