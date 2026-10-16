"""The skip flag (maps/<map>/skip.json): the human asks the loop to skip the current iteration."""

from mapforge import skip


def test_request_pending_clear(tmp_path):
    (tmp_path / "de_x").mkdir()
    assert skip.pending(tmp_path, "de_x") is None
    req = skip.request(tmp_path, "de_x", "apply my change now")
    assert req["reason"] == "apply my change now" and req["time"]
    assert skip.pending(tmp_path, "de_x") == req
    skip.clear(tmp_path, "de_x")
    assert skip.pending(tmp_path, "de_x") is None
    skip.clear(tmp_path, "de_x")  # clearing twice is fine


# ---------------------------------------------------------------- the loop acts on it
import copy  # noqa: E402
import json  # noqa: E402

from mapforge.config import Config, load_config  # noqa: E402
from mapforge.loop.run import Loop  # noqa: E402


def _loop(tmp_path, step: str) -> Loop:
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    (tmp_path / "maps" / "de_x").mkdir(parents=True)
    loop = Loop(Config(root=base.root, data=data), "de_x")
    loop.root, loop.state_file = tmp_path / "runs", tmp_path / "runs" / "loop.json"
    loop.state = {"iteration": "003", "first_iteration": "001", "step": step, "status": "running",
                  "history": [{"iteration": "003", "reached": step}], "started": "x",
                  "started_ts": __import__("time").time(), "rollback": False, "best": None,
                  "counters": {"hard_fail": 0, "review_fail": 0, "since_best": 0,
                               "targets_met": 0, "measured": 0}}  # fmt: skip
    loop.save = lambda: None  # no site rebuild in tests
    return loop


def test_skip_in_build_goes_to_decide(tmp_path):
    loop = _loop(tmp_path, "build")
    assert not loop.check_skip()
    skip.request(tmp_path / "maps", "de_x", "now please")
    assert loop.check_skip()
    assert loop.state["step"] == "decide" and skip.pending(tmp_path / "maps", "de_x") is None
    h = loop.state["history"][-1]
    assert h["skipped"] and h["at"] == "build" and h["reason"] == "now please"
    assert "skipped by the human at build" in (loop.it_dir / "NOTES.md").read_text(encoding="utf-8")
    assert "skipped by the human" in loop.loop_context()


def test_skip_while_awaiting_review(tmp_path, monkeypatch):
    loop = _loop(tmp_path, "review")
    loop.state["awaiting"] = {"step": "review", "prompt": "p", "answer": "a"}
    skip.request(tmp_path / "maps", "de_x")
    monkeypatch.setattr(Loop, "_closed", lambda self: False)
    monkeypatch.setattr(
        Loop, "step_review", lambda self: (_ for _ in ()).throw(AssertionError("reviewed"))
    )
    monkeypatch.setattr(Loop, "step_decide", lambda self: 3)  # waits for a plan
    assert loop.run() == 3
    assert loop.state["step"] == "decide" and loop.state["history"][-1]["skipped"]
    assert skip.pending(tmp_path / "maps", "de_x") is None


def test_skip_during_sim_is_not_scored(tmp_path, monkeypatch):
    import mapforge.simulate.run as sim_run

    loop = _loop(tmp_path, "sim")

    def fake_simulate(argv):
        out = __import__("pathlib").Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "simulation.json").write_text(json.dumps({"stop_reason": "skipped", "summary": {}}))
        skip.request(tmp_path / "maps", "de_x")  # (the flag is still there when sim stops)
        return 1

    monkeypatch.setattr(sim_run, "main", fake_simulate)
    monkeypatch.setattr(
        Loop, "_evaluate", lambda self, m, s: (_ for _ in ()).throw(AssertionError("scored"))
    )
    assert loop.step_sim() == "decide"
    assert loop.state["best"] is None and loop.state["counters"]["hard_fail"] == 0
    assert loop.state["history"][-1]["skipped"] and loop.state["history"][-1]["at"] == "sim"


def test_cancel_between_batches(tmp_path, monkeypatch):
    import mapforge.simulate.run as sim_run

    s = object.__new__(sim_run.Simulation)
    s.out, s.map_name, s.distance, s.log = tmp_path, "de_x", 64, lambda m: None
    s.sim = {"cvars": {}, "confidence": 0.95, "batch_rounds": 20}
    s.graph = tmp_path / "x.graph"
    s.graph.write_text("g")
    s.bsp, s.bsp_sha, s.tag, s.build_info = "b", "sha", "t", {}
    s.timescale, s.servers, s.per_team = 4.0, 2, 5
    s.targets = {"t_winrate": [0.35, 0.65], "site_split_a": [0.35, 0.65]}
    s.min_rounds, s.max_rounds = 100, 400
    s.checkpoint = lambda *a, **k: None
    ran = []
    s.run_group = lambda *a, **k: ran.append(a) or []
    monkeypatch.setattr(sim_run, "CANCEL", lambda: True)
    resume = {"smoke": {"ok": True}, "graph_attempts": [], "groups": [], "batches": []}
    report = s.run(False, False, resume)
    assert not ran and report["stop_reason"] == "skipped" and not report["ok"]
