import contextlib
import json

import pytest
from conftest import needs_compilers

from mapforge.compile.run import CompileError, compile_map
from mapforge.config import load_config
from mapforge.validate.run import validate_map
from mapforge.wad.dev_textures import main as make_dev_wad

# fixture -> (expected ok, rules that must be reported, severity of those rules)
EXPECTED = {
    "broken_leak": (False, {"leak"}, "error"),
    "broken_flipped": (False, {"invalid_brush"}, "error"),
    "broken_offgrid": (False, {"off_grid"}, "error"),
    "broken_nospawn": (False, {"spawn_count"}, "error"),
    "broken_stuck": (False, {"spawn_stuck"}, "error"),
    "de_onebomb": (False, {"bomb_targets"}, "error"),
    "narrow_gap": (True, {"narrow_passage"}, "warning"),
    "de_split": (False, {"unreachable_site"}, "error"),
    "de_twosites": (True, set(), "error"),
}


def _compile_and_validate(cfg, name):
    make_dev_wad()
    with contextlib.suppress(CompileError):  # the validator must explain the failure
        compile_map(cfg, name)
    return validate_map(cfg, name)


@pytest.mark.slow
@needs_compilers
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_is_caught_with_the_right_reason(fixture_cfg, name):
    ok, rules, severity = EXPECTED[name]
    result = _compile_and_validate(fixture_cfg, name)

    assert result["ok"] is ok
    found = {f["rule"]: f for f in result["findings"] if f["severity"] == severity}
    assert rules <= set(found), result["findings"]
    if not ok:
        # Only the intended defect is an error (plus compile_failed where CSG rejects the map).
        error_rules = {f["rule"] for f in result["findings"] if f["severity"] == "error"}
        assert error_rules - rules <= {"compile_failed"}, error_rules


@pytest.mark.slow
@needs_compilers
def test_leak_report_points_at_the_hole(fixture_cfg):
    result = _compile_and_validate(fixture_cfg, "broken_leak")
    leak = next(f for f in result["findings"] if f["rule"] == "leak")
    x, y, z = leak["location"]
    assert y >= 512  # the removed north wall spans y = 512..528
    assert leak["details"]["entity"]["classname"].startswith("info_player")
    compile_json = json.loads(
        (fixture_cfg.path("build_dir") / "broken_leak" / "compile.json").read_text()
    )
    assert compile_json["leak"]["line"], "leak polyline from the .lin file"


@pytest.mark.slow
@needs_compilers
def test_narrow_gap_width_estimate(fixture_cfg):
    result = _compile_and_validate(fixture_cfg, "narrow_gap")
    narrow = [f for f in result["findings"] if f["rule"] == "narrow_passage"]
    assert len(narrow) == 1
    assert narrow[0]["details"]["min_width_estimate"] == 48
    assert narrow[0]["location"][1] > 464  # in the gap at the north end


@pytest.mark.slow
@needs_compilers
def test_test_box_is_valid():
    cfg = load_config()
    result = _compile_and_validate(cfg, "test_box")
    assert result["ok"], result["findings"]
    assert result["summary"] == {"errors": 0, "warnings": 0, "info": 0}
    walk = result["stats"]["walkable"]
    assert walk["walkable_area_units2"] == (1024 - 32) ** 2  # room minus half a hull per side


@pytest.mark.slow
@needs_compilers
def test_split_map_reports_each_team_and_site(fixture_cfg):
    result = _compile_and_validate(fixture_cfg, "de_split")
    unreachable = [f for f in result["findings"] if f["rule"] == "unreachable_site"]
    # CT (west) cannot reach the east site, T (east) cannot reach the west site
    assert sorted((f["details"]["site"], f["message"].split()[1]) for f in unreachable) == [
        (1, "T"),
        (2, "CT"),
    ]
    sites = result["stats"]["reachability"]["sites"]
    assert [s["spawns_reaching"] for s in sites] == [{"T": 0, "CT": 2}, {"T": 2, "CT": 0}]


@pytest.mark.slow
@needs_compilers
def test_two_site_map_is_clean(fixture_cfg):
    result = _compile_and_validate(fixture_cfg, "de_twosites")
    assert result["findings"] == []
    sites = result["stats"]["reachability"]["sites"]
    assert all(s["spawns_reaching"] == {"T": 2, "CT": 2} for s in sites)
