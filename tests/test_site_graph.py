"""The topology page (graph.html) on the local website."""

import copy
import json
import re

from mapforge.config import Config, load_config
from mapforge.site.build import build_site


def test_graph_page_has_every_own_map_with_a_layout(tmp_path):
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), runs_dir=str(tmp_path / "runs"))
    cfg = Config(root=base.root, data=data)
    out = build_site(cfg)
    page = (out / "graph.html").read_text(encoding="utf-8")
    assert (out / "graph.js").is_file() and (out / "graph.css").is_file()
    blob = re.search(r"<script type='application/json' id='graph-data'>(.*?)</script>", page, re.S)
    graphs = json.loads(blob.group(1))
    layouts = {p.parent.name for p in (base.root / "maps").glob("*/layout.yaml")}
    assert set(graphs["maps"]) == layouts and graphs["default"] in layouts
    assert "href='graph.html'" in (out / "index.html").read_text(encoding="utf-8")
    assert "graph.html#de_cistern01" in (out / "maps" / "de_cistern01" / "index.html").read_text(
        encoding="utf-8"
    )
