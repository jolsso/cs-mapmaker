"""Closing ("afslut") and reopening a map under Input."""

import copy
import json

import pytest

from mapforge import annotations, project
from mapforge.config import Config, load_config
from mapforge.site.build import build_site


def test_closed_map_takes_no_wishes_and_reopens(tmp_path):
    (tmp_path / "de_x").mkdir()
    assert project.load(tmp_path, "de_x")["state"] == "open"
    project.set_state(tmp_path, "de_x", "closed")
    assert project.is_closed(tmp_path, "de_x") and project.load_all(tmp_path)["de_x"]["changed"]
    with pytest.raises(ValueError, match="afsluttet"):
        annotations.add(tmp_path, "de_x", {"kind": "note", "text": "mere cover", "points": []})
    project.set_state(tmp_path, "de_x", "open")
    assert annotations.add(tmp_path, "de_x", {"kind": "note", "text": "mere cover", "points": []})
    with pytest.raises(ValueError):
        project.set_state(tmp_path, "de_x", "done")
    with pytest.raises(ValueError, match="unknown"):
        project.set_state(tmp_path, "de_nope", "closed")


def test_loop_does_not_run_on_a_closed_map(tmp_path, monkeypatch):
    from mapforge.loop.run import Loop

    cfg = load_config()
    data = copy.deepcopy(cfg.data)
    data["paths"]["maps_dir"] = str(tmp_path)
    (tmp_path / "de_x").mkdir()
    project.set_state(tmp_path, "de_x", "closed")
    loop = Loop(Config(root=cfg.root, data=data), "de_x")
    loop.root, loop.state_file = tmp_path, tmp_path / "loop.json"
    loop.state = {"status": "running", "step": "build", "iteration": "001"}
    assert loop.run() == 0 and "afsluttet" in loop.state["stop_reason"]
    with pytest.raises(RuntimeError, match="afsluttet"):
        loop.init(False)


def test_closed_map_is_grey_and_last_on_the_front_page(tmp_path):
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"),
                         runs_dir=str(tmp_path / "runs"))  # fmt: skip
    cfg = Config(root=base.root, data=data)
    for m in ("de_a", "de_b"):
        (tmp_path / "build" / m).mkdir(parents=True)
        v = {"ok": True, "source": "map", "summary": {}, "findings": []}
        (tmp_path / "build" / m / "validation.json").write_text(json.dumps(v))
        (tmp_path / "maps" / m).mkdir(parents=True)
    project.set_state(tmp_path / "maps", "de_b", "closed")
    import os

    os.utime(tmp_path / "build" / "de_b" / "validation.json", (2_000_000_000,) * 2)  # newest
    home = (build_site(cfg) / "index.html").read_text(encoding="utf-8")
    assert home.index("data-map='de_a'") < home.index("data-map='de_b'")
    assert "class='pcard closed' data-map='de_b'" in home and "Afsluttet" in home
