from mapforge.validate.checks import check_entities

RULES = {"spawns_per_team": 1, "buyzones_per_team": 1, "bomb_targets": {"de": 2}}
SPAWNS = [{"classname": "info_player_start"}, {"classname": "info_player_deathmatch"}]
BOMBS = [{"classname": "func_bomb_target"}, {"classname": "info_bomb_target"}]


def _rules(entities):
    findings, stats = check_entities(entities, RULES, "de", bsp=None)
    return {f.rule for f in findings}, stats


def test_no_buyzones_at_all_is_implicit_and_ok():
    rules, stats = _rules(SPAWNS + BOMBS)
    assert rules == set()
    assert stats["buyzones"] == {"T": 0, "CT": 0, "implicit": True}


def test_buyzone_for_only_one_team_fails():
    rules, _ = _rules(SPAWNS + BOMBS + [{"classname": "func_buyzone", "team": "1"}])
    assert rules == {"buyzone_count"}


def test_shared_buyzone_counts_for_both_teams():
    rules, stats = _rules(SPAWNS + BOMBS + [{"classname": "func_buyzone"}])
    assert rules == set()
    assert stats["buyzones"] == {"T": 1, "CT": 1, "implicit": False}


def test_bomb_targets_only_required_for_de_maps():
    findings, _ = check_entities(SPAWNS, RULES, "cs", bsp=None)
    assert findings == []
    findings, _ = check_entities(SPAWNS + BOMBS[:1], RULES, "de", bsp=None)
    assert {f.rule for f in findings} == {"bomb_targets"}
