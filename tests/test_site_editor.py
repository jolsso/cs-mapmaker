"""The graph editor page on the local website (editor.html, editor.js, refgraphs.json)."""

import copy
import json
from pathlib import Path

from mapforge.config import Config, load_config
from mapforge.site.build import build_site

ROOT = Path(__file__).resolve().parents[1]


def _site(tmp_path) -> Path:
    base = load_config()
    data = copy.deepcopy(base.data)
    build = tmp_path / "build"
    ref = build / "topologies" / "refmap"
    ref.mkdir(parents=True)
    topo = {"tier": "A", "nodes": [{"id": "t_spawn", "role": "t_spawn", "level": 0, "_c": [0, 0]}],
            "edges": [{"a": "t_spawn", "b": "t_spawn", "kind": "door"}]}  # fmt: skip
    (ref / "de_ref.json").write_text(json.dumps(topo), encoding="utf-8")
    data["paths"].update(build_dir=str(build), runs_dir=str(tmp_path / "runs"))
    return build_site(Config(root=base.root, data=data))


def test_site_writes_editor_and_refgraphs(tmp_path):
    out = _site(tmp_path)
    page = (out / "editor.html").read_text(encoding="utf-8")
    assert "editor.js" in page and "editor.css" in page and "id='ed-svg'" in page
    refs = json.loads((out / "refgraphs.json").read_text(encoding="utf-8"))
    assert refs["de_ref"]["tier"] == "A" and refs["de_ref"]["nodes"][0][0] == "t_spawn"
    assert refs["own:de_forge01"]["tier"] == "own"
    assert refs["own:de_forge01"]["choke_edges"]  # its four chokes come along
    assert "href='editor.html'" in (out / "index.html").read_text(encoding="utf-8")


def test_editor_js_has_no_inlined_refs(tmp_path):
    out = _site(tmp_path)
    js = (out / "editor.js").read_text(encoding="utf-8")
    assert "/*REFS*/" not in js and "refgraphs.json" in js
    assert "localhost:8090/api" in js and "/topology" in js and "/changes" in js and "/graph" in js
