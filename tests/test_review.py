import copy
import json

import pytest

from mapforge.config import Config, load_config
from mapforge.review import run as review

VALID = {
    "ok": True,
    "summary": {"errors": 0, "warnings": 1, "info": 0},
    "findings": [{"rule": "limit", "severity": "warning", "message": "planes 80 %"}],
    "stats": {"reachability": {"sites": []}, "entities": {"spawns": {"T": 2, "CT": 2}}},
}
INDEX = {
    "images": [{"file": "topdown.png", "purpose": "overview"}],
    "brightness": {"dark_luma": 10, "dark_zones": []},
    "missing_textures": [],
}


@pytest.fixture
def cfg(tmp_path) -> Config:
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"]["build_dir"] = str(tmp_path / "build")
    data["paths"]["maps_dir"] = str(tmp_path / "maps")
    renders = tmp_path / "build" / "m" / "renders"
    renders.mkdir(parents=True)
    (renders / "index.json").write_text(json.dumps(INDEX))
    return Config(root=base.root, data=data)


def _write_validation(cfg, v):
    (cfg.path("build_dir") / "m" / "validation.json").write_text(json.dumps(v))


def _answer(cfg, findings, summary="s"):
    path = cfg.path("build_dir") / "m" / "review_answer.json"
    path.write_text(json.dumps({"summary": summary, "findings": findings}))
    return path


def test_validation_errors_fail_without_calling_claude(cfg, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("claude must not be called")

    monkeypatch.setattr(review, "call_claude", boom)
    leak = {"rule": "leak", "severity": "error", "message": "map leaks", "location": [0, 1, 2]}
    _write_validation(cfg, {**VALID, "ok": False, "findings": [leak]})
    for mode in ("emit", "headless"):
        r = review.review_map(cfg, "m", mode)
        assert r["passed"] is False and r["stage"] == "deterministic"
        assert r["findings"][0]["severity"] == "critical" and "leak" in r["findings"][0]["what"]


@pytest.mark.parametrize(
    ("severities", "passed"),
    [([], True), (["minor", "minor"], True), (["minor", "major"], False), (["critical"], False)],
)
def test_session_answer_pass_is_decided_by_severity(cfg, severities, passed):
    findings = [
        {"severity": s, "where": "x", "what": "y", "image": "topdown.png"} for s in severities
    ]
    _write_validation(cfg, VALID)
    _answer(cfg, findings)
    r = review.review_map(cfg, "m", "answer")
    assert r["passed"] is passed and r["executor"] == "session"
    assert json.loads((cfg.path("build_dir") / "m" / "review.json").read_text())["passed"] is passed


def test_headless_uses_the_same_rule(cfg, monkeypatch):
    findings = [{"severity": "major", "where": "x", "what": "y", "image": "topdown.png"}]
    monkeypatch.setattr(
        review, "call_claude",
        lambda *a, **k: {"answer": {"summary": "s", "findings": findings}, "envelope": {}},
    )  # fmt: skip
    _write_validation(cfg, VALID)
    r = review.review_map(cfg, "m", "headless")
    assert r["passed"] is False and r["executor"] == "headless"


@pytest.mark.parametrize(
    "bad",
    [{"findings": []}, {"summary": "s", "findings": [{"severity": "huge", "where": "x",
     "what": "y", "image": "i"}]}, {"summary": "s", "findings": [{"severity": "minor"}]}],
)  # fmt: skip
def test_invalid_answers_are_rejected(cfg, bad):
    _write_validation(cfg, VALID)
    (cfg.path("build_dir") / "m" / "review_answer.json").write_text(json.dumps(bad))
    with pytest.raises(RuntimeError):
        review.review_map(cfg, "m", "answer")


def test_emit_writes_prompt_and_schema(cfg):
    _write_validation(cfg, VALID)
    r = review.review_map(cfg, "m", "emit")
    assert r["passed"] is None
    build = cfg.path("build_dir") / "m"
    prompt = (build / "review_prompt.md").read_text(encoding="utf-8")
    assert "topdown.png" in prompt and "planes 80 %" in prompt
    assert "Review-tjekliste" in prompt and "ingen layout-spec" in prompt
    assert json.loads((build / "review_schema.json").read_text())["required"] == [
        "summary", "findings",
    ]  # fmt: skip
    assert not (build / "review.json").exists()  # nothing decided yet
