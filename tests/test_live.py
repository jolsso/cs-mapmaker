from mapforge.live.collector import State


def test_collector_tracks_positions_kills_and_rounds():
    s = State()
    s.handle("P|b01s0|de_x|3|12.5|1|2|1|1,T,1,100,-50,90;2,CT,0,10,20,0;")
    s.handle("K|b01s0|de_x|3|13.0|CT|T|100|-50|m4a1")
    s.handle("B|b01s0|de_x|3|40.0|A|1500|1600")
    s.handle("R|b01s0|de_x|3|T|bomb|A|2|2")
    s.handle("garbage")
    s.handle("P|b01s0|de_x|x|bad|1|2|1|")  # malformed numbers are ignored
    snap = s.snapshot()
    r = snap["runs"][0]
    assert r["key"] == "de_x/b01s0" and r["round"] == 3 and r["live"]
    assert r["players"][0] == {
        "id": 1,
        "team": "T",
        "alive": True,
        "x": 100.0,
        "y": -50.0,
        "yaw": 90.0,
    }
    assert not r["players"][1]["alive"]
    assert r["kills"][0]["weapon"] == "m4a1" and r["plants"][0]["site"] == "A"
    assert r["rounds"][-1]["winner"] == "T" and r["score"] == {"T": 2, "CT": 2}
    s.handle("Q|b01s0|de_x|done")
    assert s.snapshot()["runs"][0]["done"]


def test_new_map_brief(tmp_path, monkeypatch):
    import pytest

    from mapforge.live import collector

    monkeypatch.setattr(collector, "MAPS_DIR", tmp_path)
    b = collector.create_map({"name": "de_harbour01",
                              "description": "En havn ved nat med et lagerhus på A."})  # fmt: skip
    assert (tmp_path / "de_harbour01" / "brief.json").is_file() and b["status"] == "brief"
    assert [x["name"] for x in collector.list_briefs()] == ["de_harbour01"]
    for name, desc, msg in (("de_harbour01", "a valid description", "exists"),
                            ("../evil", "a valid description", "name"),
                            ("de_ok01", "short", "description")):  # fmt: skip
        with pytest.raises(ValueError, match=msg):
            collector.create_map({"name": name, "description": desc})
