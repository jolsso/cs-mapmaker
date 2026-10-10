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


def test_validation_errors_fail_without_calling_claude(cfg, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("claude must not be called")

    monkeypatch.setattr(review, "call_claude", boom)
    leak = {"rule": "leak", "severity": "error", "message": "map leaks", "location": [0, 1, 2]}
    bad = {**VALID, "ok": False, "findings": [leak]}
    _write_validation(cfg, bad)
    r = review.review_map(cfg, "m", model=None, dry_run=False)
    assert r["passed"] is False and r["stage"] == "deterministic"
    assert r["findings"][0]["severity"] == "critical" and "leak" in r["findings"][0]["what"]


@pytest.mark.parametrize(
    ("severities", "passed"),
    [([], True), (["minor", "minor"], True), (["minor", "major"], False), (["critical"], False)],
)
def test_pass_is_decided_by_severity_not_by_the_model(cfg, monkeypatch, severities, passed):
    findings = [
        {"severity": s, "where": "x", "what": "y", "image": "topdown.png"} for s in severities
    ]
    monkeypatch.setattr(
        review, "call_claude",
        lambda *a, **k: {"answer": {"summary": "s", "findings": findings}, "envelope": {}},
    )  # fmt: skip
    _write_validation(cfg, VALID)
    r = review.review_map(cfg, "m", model=None, dry_run=False)
    assert r["passed"] is passed and r["stage"] == "visual"
    assert json.loads((cfg.path("build_dir") / "m" / "review.json").read_text())["passed"] is passed


def test_prompt_lists_images_validation_and_checklist(cfg):
    _write_validation(cfg, VALID)
    review.review_map(cfg, "m", model=None, dry_run=True)
    prompt = (cfg.path("build_dir") / "m" / "review_prompt.md").read_text(encoding="utf-8")
    assert "topdown.png" in prompt and "planes 80 %" in prompt
    assert "Review-tjekliste" in prompt and "ingen layout-spec" in prompt
