import base64
import io
import json

import pytest
from PIL import Image

from mapforge import brief, interpret


def test_v1_upgrades_and_bad_values_name_the_field():
    b = brief.normalize({"name": "de_x01", "description": "En havn om natten.", "canvas": [0]})
    assert b["version"] == 2 and b["mode"] == "simple" and b["canvas"] == [0]
    bad_values = [
        ({"pace": "warp"}, "pace"),
        ({"sightlines": {"long": "lots"}}, "sightlines"),
        ({"landmarks": [{"note": "x"}]}, "landmarks"),
        ({"name": "x"}, "name"),
    ]
    for bad, field in bad_values:
        with pytest.raises(ValueError, match=field):
            brief.normalize({"name": "de_x01", "description": "En havn om natten.", **bad})


def _png(exif: bool) -> str:
    im, buf = Image.new("RGB", (8, 8), (200, 10, 10)), io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"  # Make
        im.save(buf, "JPEG", exif=ex)
    else:
        im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_images_are_tagged_stripped_and_inspiration_stays_local(tmp_path):
    brief.create(tmp_path, {"name": "de_x01", "description": "En havn om natten."}, [0, 0, 1, 1])
    req = {"file": "Kran Foto.JPG", "data": _png(True), "tag": "landmark", "license": "inspiration"}
    e = brief.add_image(tmp_path, "de_x01", req)
    p = brief.image_path(tmp_path, "de_x01", e)
    assert e["file"] == "kran_foto.jpg" and p.parent.name == "inspiration"
    assert "SecretCam" not in p.read_bytes().decode("latin-1")
    e2 = brief.add_image(tmp_path, "de_x01", {"file": "kran.png", "data": _png(False),
                                              "tag": "mood", "license": "own"})  # fmt: skip
    assert brief.image_path(tmp_path, "de_x01", e2).parent.name == "brief"
    with pytest.raises(ValueError, match="tag"):
        brief.add_image(tmp_path, "de_x01", {"data": _png(False), "tag": "x", "license": "own"})
    with pytest.raises(ValueError, match="PNG/JPEG"):
        brief.add_image(tmp_path, "de_x01", {"data": base64.b64encode(b"nope").decode(),
                                             "tag": "mood", "license": "own"})  # fmt: skip


BRIEF = {"name": "de_x01", "description": "En havn om natten.", "pace": "slow",
         "must_have": ["kran ved A"]}  # fmt: skip


def _intent(**over):
    i = {
        "summary": "A slow, tactical harbour map at night with a crane by A and a terminal at B.",
        "concept": "Blow up the ferry berth", "archetype": "asymmetric", "size": "medium",
        "pace": "slow",
        "space": {"levels": "some", "inside": "mixed", "density": "mixed", "stacked_sites": False},
        "playstyle": {"sightlines": {"long": "some", "cqb": "many"}, "site_cover": "mixed"},
        "sites": {s: {"character": "x", "entrances": 3, "vertical": False} for s in "AB"},
        "mid": "a decision",
        "theme": {"setting": "harbour", "tags": [], "palette": [], "materials": []},
        "landmarks": [{"name": "crane", "where": "A", "space": "large", "purpose": "callout",
                       "image": ""}],
        "targets": {"t_to_site_s": [16, 22], "ct_lead_s": 5, "longest_sightline": 2200},
        "must_have": [{"item": "kran ved A", "status": "covered", "how": "landmark crane on A"}],
        "no_go": [], "open_questions": [],
        "assumptions": [{"field": f, "value": "x", "why": "not in the brief"} for f in
                        ("archetype", "size", "levels", "inside", "density", "stacked_sites",
                         "site_cover")],
    }  # fmt: skip
    i.update(over)
    return i


def test_interpreter_rules():
    b = brief.normalize(BRIEF)
    assert interpret.check(_intent(), b) == []
    assert any("must_have" in e for e in interpret.check(_intent(must_have=[]), b))
    assert any("pace" in e for e in interpret.check(_intent(pace="fast"), b))  # changed silently
    no_assume = _intent(assumptions=[])
    assert any("archetype" in e and "assumptions" in e for e in interpret.check(no_assume, b))
    t = _intent(targets={"t_to_site_s": [10, 30], "ct_lead_s": 5, "longest_sightline": 2200})
    assert any("t_to_site_s" in e for e in interpret.check(t, b))
    assert interpret.check({"summary": 3}, b)  # schema


def test_human_edit_is_checked_and_confirms(tmp_path):
    brief.create(tmp_path, BRIEF, [0, 0, 1, 1])
    out = interpret.save_edit(tmp_path, "de_x01", {"intent": _intent(), "confirm": True})
    assert out["meta"]["confirmed"] and out["meta"]["by"] == "human"
    saved = json.loads((tmp_path / "de_x01" / "intent.json").read_text(encoding="utf-8"))
    assert saved["pace"] == "slow"
    with pytest.raises(ValueError, match="must_have"):
        interpret.save_edit(tmp_path, "de_x01", {"intent": _intent(must_have=[])})
