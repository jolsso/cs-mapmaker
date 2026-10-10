import copy
import json

import pytest

from mapforge.config import Config, load_config
from mapforge.decide import run as decide
from mapforge.runs import iterations, stage_of

VALID = {"ok": True, "summary": {}, "findings": [], "stats": {}}


@pytest.fixture
def cfg(tmp_path) -> Config:
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"),
                         runs_dir=str(tmp_path / "runs"))  # fmt: skip
    build = tmp_path / "build" / "m"
    (build / "renders").mkdir(parents=True)
    (build / "renders" / "index.json").write_text("{}")
    (build / "renders" / "topdown.png").write_bytes(b"png")
    (build / "validation.json").write_text(json.dumps(VALID))
    (build / "review.json").write_text(json.dumps({"passed": False, "findings": []}))
    return Config(root=base.root, data=data)


@pytest.mark.parametrize(
    ("files", "reached", "nxt"),
    [
        ({}, "none", "validate"),
        ({"validation.json": {"ok": False}}, "validate", "fix"),
        ({"validation.json": {"ok": True}}, "validate", "review"),
        ({"validation.json": {"ok": True}, "review.json": {"passed": False}}, "review", "fix"),
        ({"validation.json": {"ok": True}, "review.json": {"passed": True}}, "review", "simulate"),
    ],
)
def test_stage(tmp_path, files, reached, nxt):
    for name, body in files.items():
        (tmp_path / name).write_text(json.dumps(body))
    s = stage_of(tmp_path)
    assert (s["reached"], s["next"]) == (reached, nxt)


def test_emit_collects_the_contract_and_numbers_runs(cfg):
    first = decide.emit(cfg, "m")
    second = decide.emit(cfg, "m")
    assert [p.name for p in iterations(cfg, "m")] == ["001", "002"]
    assert (second / "validation.json").is_file() and (second / "renders" / "topdown.png").is_file()
    stage = json.loads((first / "stage.json").read_text())
    assert stage["reached"] == "review" and stage["next"] == "fix"
    prompt = (first / "decide_prompt.md").read_text(encoding="utf-8")
    assert "add_cover" in prompt and "escalate" in prompt and "stage.json" in prompt


def test_answer_checks_the_plan_and_requires_notes(cfg):
    run = decide.emit(cfg, "m")
    move_site = {"type": "move_site", "params": {"target": "B"}, "rationale": "x"}
    plan = {"summary": "s", "expected_effect": "e", "risk": "r", "escalate": False,
            "changes": [move_site]}  # fmt: skip
    (run / "plan.json").write_text(json.dumps(plan))
    d = decide.answer(cfg, run, phase=3)
    assert not d["ok"] and "NOTES.md missing" in d["errors"]
    assert d["rejected"][0]["type"] == "move_site" and d["applied"] is False
    (run / "NOTES.md").write_text("noter")
    plan["changes"] = []
    plan.update(escalate=True, escalation_reason="site skal flyttes: uden for værktøjskassen")
    (run / "plan.json").write_text(json.dumps(plan))
    d = decide.answer(cfg, run, phase=3)
    assert d["ok"] and d["escalate"]
    assert json.loads((run / "decision.json").read_text())["escalate"] is True
