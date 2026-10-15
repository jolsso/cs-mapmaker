from mapforge.config import load_config
from mapforge.mapfile.parser import MapFile
from mapforge.mapfile.writer import box_brush, entity
from mapforge.wad import repeat

SIZES = {
    "OUT_WALL7": (96, 128), "OUT_WALL7A": (96, 128), "OUT_WALL7B": (96, 128),
    "OUT_WALL1A": (96, 128), "BRICK05": (256, 256), "BRICK05-2": (256, 256),
    "BRICK05_SM": (128, 128), "CSTRIKE_WR4CCWD": (128, 128), "CSTRIKE_WR4CCPN": (128, 128),
    "SIGN": (64, 64), "-0PLATE": (64, 64), "-1PLATE": (64, 64), "-0LONE": (64, 64),
}  # fmt: skip
RISK = {
    "OUT_WALL7": {"risk": "low"}, "OUT_WALL7A": {"risk": "medium"},
    "OUT_WALL7B": {"risk": "high", "feature": "bullet holes"}, "BRICK05": {"risk": "low"},
    "BRICK05-2": {"risk": "high", "feature": "windows"}, "SIGN": {"risk": "high"},
}  # fmt: skip


def test_family_root_and_siblings():
    assert repeat.root("OUT_WALL7B") == "OUT_WALL7"
    assert repeat.root("BRICK05-2") == "BRICK05"
    assert repeat.root("CSTRIKE_WR4CCWD") == "CSTRIKE_WR4CC"
    assert repeat.root("-0CSTRIKE_ME1PL") == "CSTRIKE_ME1"
    assert repeat.siblings("OUT_WALL7B", SIZES) == ["OUT_WALL7", "OUT_WALL7A"]
    assert repeat.siblings("BRICK05-2", SIZES) == ["BRICK05"]  # BRICK05_SM: other size
    assert repeat.calm_sibling("OUT_WALL7B", RISK, SIZES) == "OUT_WALL7"
    assert repeat.calm_sibling("SIGN", RISK, SIZES) is None
    assert repeat.random_tiled("-0PLATE", SIZES) and not repeat.random_tiled("-0LONE", SIZES)
    medium = {**RISK, "BRICK05": {"risk": "medium"}}  # no low sibling: medium beats high
    assert repeat.calm_sibling("BRICK05-2", medium, SIZES) == "BRICK05"


def test_big_faces_get_the_calm_sibling_small_ones_keep_the_feature(monkeypatch):
    monkeypatch.setattr(repeat, "load_risk", lambda cfg: RISK)
    monkeypatch.setattr(repeat, "texture_sizes", lambda dirs: SIZES)
    big = box_brush((0, 0, 0), (960, 16, 256), "OUT_WALL7B")  # 10 tiles across
    small = box_brush((0, 64, 0), (96, 80, 128), "OUT_WALL7B")  # one tile: an accent
    sign = box_brush((0, 128, 0), (640, 144, 64), "SIGN")  # no calm sibling
    mf = MapFile(entities=[entity({"classname": "worldspawn"}, [big, small, sign])])
    rep = repeat.tame(mf, load_config())
    tex = [{f.texture for f in b.faces} for b in mf.brushes()]
    assert tex[0] == {"OUT_WALL7", "OUT_WALL7B"}  # the long faces swap, the 16-wide ends keep it
    assert tex[1] == {"OUT_WALL7B"}
    assert rep["swapped"]["OUT_WALL7B"][0] == "OUT_WALL7"
    assert rep["kept"]["SIGN"][0] == "high" and rep["kept"]["SIGN"][2] == 10.0
    monkeypatch.setattr(repeat, "tame", lambda mf, cfg: rep)
    (f,) = [d for d in repeat.findings(mf, load_config()) if d["severity"] == "warning"]
    assert "SIGN" in f["message"] and f["rule"] == "repeating_texture"
