import copy

import pytest

from mapforge.decide.policy import check_plan, load_fitness

FITNESS = load_fitness()
# the policy rules are tested on open geometry, whatever gate the real map is at
FITNESS["locked"]["geometry_frozen"] = False


def plan(*changes, escalate=False, reason=""):
    p = {"summary": "s", "changes": list(changes), "expected_effect": "e", "risk": "r",
         "escalate": escalate}  # fmt: skip
    if reason:
        p["escalation_reason"] = reason
    return p


def ch(ctype, **params):
    return {"type": ctype, "params": params, "rationale": "because"}


def test_allowed_changes_are_accepted():
    v = check_plan(plan(ch("add_cover", zone="site A", position=[0, 0], size=[64, 64, 64]),
                        ch("move_spawn", team="T", delta=[128, 0])), FITNESS)  # fmt: skip
    assert v.ok and len(v.accepted) == 2


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (ch("move_site", target="site 2", delta=[0, 500]), "not in the allowed toolbox"),
        (ch("move_corridor", target="mid", delta=[300, 0]), "exceeds"),
        (ch("adjust_opening", target="B door", width=48), "below the 64"),
        (ch("add_cover", zone="A"), "missing params"),
        (ch("lighting", target="tunnel"), "only from phase 7"),
        (ch("move_spawn", team="T", delta="far"), "not a number"),
    ],
)
def test_bad_changes_are_rejected_with_a_reason(change, why):
    v = check_plan(plan(change), FITNESS)
    assert not v.ok and v.accepted == []
    assert why in v.rejected[0]["reason"]


def test_one_connection_change_per_iteration():
    add = ch("add_connection", **{"from": "mid", "to": "B"})
    remove = ch("remove_connection", **{"from": "long", "to": "A"})
    v = check_plan(plan(add, remove), FITNESS)
    assert len(v.accepted) == 1 and "one connection" in v.rejected[0]["reason"]


def test_locked_landmarks_and_frozen_geometry():
    f = copy.deepcopy(FITNESS)
    f["locked"]["landmarks"] = ["the well"]
    v = check_plan(plan(ch("remove_cover", target="crates next to The Well")), f)
    assert "locked decision" in v.rejected[0]["reason"]
    f["locked"]["geometry_frozen"] = True
    v = check_plan(plan(ch("add_cover", zone="A", position=[0, 0], size=[8, 8, 8])), f)
    assert "frozen" in v.rejected[0]["reason"]
    v = check_plan(plan(ch("lighting", target="tunnel")), f, phase=7)
    assert v.ok  # lighting is still allowed after Gate B, in the art pass


def test_plan_level_errors():
    assert "missing field: risk" in check_plan({"summary": "s", "changes": [],
        "expected_effect": "e", "escalate": False}, FITNESS).errors  # fmt: skip
    assert check_plan(plan(escalate=True), FITNESS).errors  # escalate needs a reason
    assert check_plan(plan(escalate=True, reason="site must move: locked"), FITNESS).ok
