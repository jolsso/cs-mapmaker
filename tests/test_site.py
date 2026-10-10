import copy
import json

from mapforge.config import Config, load_config
from mapforge.site.build import _md, build_site


def test_site_has_home_architecture_and_a_page_per_map(tmp_path):
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"),
                         runs_dir=str(tmp_path / "runs"))  # fmt: skip
    cfg = Config(root=base.root, data=data)
    b = tmp_path / "build" / "de_x"
    (b / "renders").mkdir(parents=True)
    (b / "renders" / "topdown.png").write_bytes(b"\x89PNG")
    index = {"images": [{"file": "topdown.png", "purpose": "overview"}], "brightness": {}}
    (b / "renders" / "index.json").write_text(json.dumps(index))
    (b / "validation.json").write_text(json.dumps(
        {"ok": False, "source": "map", "summary": {"errors": 1},
         "findings": [{"rule": "leak", "severity": "error", "message": "map leaks"}]}))  # fmt: skip
    out = build_site(cfg)
    home = (out / "index.html").read_text(encoding="utf-8")
    page = (out / "maps" / "de_x" / "index.html").read_text(encoding="utf-8")
    assert "de_x" in home and "Egne maps" in home
    assert (out / "architecture.html").is_file() and (out / "style.css").is_file()
    assert "map leaks" in page and "img/topdown.png" in page
    assert (out / "maps" / "de_x" / "img" / "topdown.png").read_bytes() == b"\x89PNG"


def test_markdown_subset():
    out = _md("# Titel\n- **fed** punkt\n- `kode`\ntekst <script>")
    assert "<h3>Titel</h3>" in out and "<li><b>fed</b> punkt</li>" in out
    assert "<code>kode</code>" in out and "&lt;script&gt;" in out
