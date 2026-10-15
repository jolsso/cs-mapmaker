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


def test_only_running_loops_pulse_and_cards_sort_by_last_edit(tmp_path):
    import os

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"),
                         runs_dir=str(tmp_path / "runs"))  # fmt: skip
    cfg = Config(root=base.root, data=data)
    for i, m in enumerate(("de_old", "de_new", "de_mid")):
        b = tmp_path / "build" / m
        b.mkdir(parents=True)
        v = {"ok": True, "source": "map", "summary": {}, "findings": []}
        (b / "validation.json").write_text(json.dumps(v))
        os.utime(b / "validation.json", (1_000_000 + 1000 * i,) * 2)
    os.utime(tmp_path / "build" / "de_new" / "validation.json", (2_000_000,) * 2)
    (tmp_path / "runs" / "de_mid").mkdir(parents=True)
    (tmp_path / "runs" / "de_mid" / "loop.json").write_text(
        json.dumps({"status": "running", "step": "sim", "iteration": "001"})
    )
    os.utime(tmp_path / "runs" / "de_mid" / "loop.json", (1_000_000,) * 2)
    home = (build_site(cfg) / "index.html").read_text(encoding="utf-8")
    pos = {m: home.index(f"maps/{m}/index.html") for m in ("de_old", "de_new", "de_mid")}
    assert pos["de_new"] < pos["de_mid"] < pos["de_old"]
    assert home.count("class='stepper idle'") == 2 and home.count("class='stepper running'") == 1


def test_input_is_not_a_gate_but_marks_a_loop_waiting_for_a_person(tmp_path):
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"),
                         runs_dir=str(tmp_path / "runs"))  # fmt: skip
    cfg = Config(root=base.root, data=data)
    b = tmp_path / "build" / "de_x"
    b.mkdir(parents=True)
    v = {"ok": True, "source": "map", "summary": {}, "findings": []}
    (b / "validation.json").write_text(json.dumps(v))
    (tmp_path / "runs" / "de_x").mkdir(parents=True)
    (tmp_path / "runs" / "de_x" / "loop.json").write_text(
        json.dumps({"status": "stopped", "stop_reason": "alle mål ramt → Gate B"})
    )
    home = (build_site(cfg) / "index.html").read_text(encoding="utf-8")
    assert "af 7 faser bestået" in home and "class='stepper human'" in home
    assert "class='step todo now'" in home and "Venter på dig" in home
