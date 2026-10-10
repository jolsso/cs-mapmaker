import copy
import json

from mapforge.config import Config, load_config
from mapforge.history import snapshot, versions
from mapforge.site.build import build_site


def _cfg(tmp_path) -> Config:
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(
        build_dir=str(tmp_path / "build"),
        maps_dir=str(tmp_path / "maps"),
        runs_dir=str(tmp_path / "runs"),
        history_dir=str(tmp_path / "history"),
    )
    return Config(root=base.root, data=data)


def _build(cfg, bsp_bytes: bytes, review_passed=None):
    b = cfg.path("build_dir") / "de_h"
    (b / "renders").mkdir(parents=True, exist_ok=True)
    (b / "de_h.bsp").write_bytes(bsp_bytes)
    (b / "renders" / "topdown.png").write_bytes(b"png")
    (b / "renders" / "index.json").write_text(
        json.dumps(
            {"bsp": str(b / "de_h.bsp"), "images": [{"file": "topdown.png", "purpose": "overview"}]}
        )
    )
    (b / "validation.json").write_text(
        json.dumps(
            {"ok": True, "summary": {}, "findings": [], "stats": {"timings": [{"site": "A"}]}}
        )
    )
    if review_passed is not None:
        (b / "review.json").write_text(json.dumps({"passed": review_passed, "summary": "s"}))


def test_new_version_only_when_the_bsp_changes(tmp_path):
    cfg = _cfg(tmp_path)
    _build(cfg, b"map v1")
    v1 = snapshot(cfg, "de_h", note="first")
    _build(cfg, b"map v1", review_passed=True)  # same map, now reviewed
    assert snapshot(cfg, "de_h") == v1
    meta = json.loads((v1 / "meta.json").read_text())
    assert meta["review_passed"] is True and meta["notes"] == ["first"]
    _build(cfg, b"map v2")
    v2 = snapshot(cfg, "de_h")
    assert [p.name for p in versions(cfg, "de_h")] == ["001", "002"] and v2.name == "002"
    assert (v2 / "renders" / "topdown.png").is_file() and (v2 / "validation.json").is_file()


def test_site_lists_versions_with_thumbnails_and_pages(tmp_path):
    cfg = _cfg(tmp_path)
    _build(cfg, b"a", review_passed=False)
    snapshot(cfg, "de_h")
    _build(cfg, b"b", review_passed=True)
    snapshot(cfg, "de_h")
    out = build_site(cfg)
    page = (out / "maps" / "de_h" / "index.html").read_text(encoding="utf-8")
    assert "Historik" in page and page.index("Version 002") < page.index(
        "Version 001"
    )  # newest first
    assert (out / "maps" / "de_h" / "history" / "001.html").is_file()
    assert (out / "maps" / "de_h" / "history" / "002" / "img" / "topdown.png").is_file()
