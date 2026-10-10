import shutil

from mapforge.config import REPO_ROOT, deep_merge, load_config


def test_repo_config_loads(monkeypatch):
    monkeypatch.delenv("MAPFORGE_TOOLS_DIR", raising=False)
    cfg = load_config()
    assert cfg.compiler["flavor"]
    assert {"fast", "final"} <= set(cfg.data["profiles"])
    assert cfg.path("maps_dir") == REPO_ROOT / "maps"
    assert cfg.path("tools_dir") == REPO_ROOT / "tools"


def test_local_override_is_deep_merged(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(REPO_ROOT / "config" / "pipeline.yaml", tmp_path / "config" / "pipeline.yaml")
    (tmp_path / "config" / "pipeline.local.yaml").write_text("paths:\n  build_dir: out\n")
    cfg = load_config(tmp_path)
    assert cfg.path("build_dir") == tmp_path / "out"
    assert cfg.path("maps_dir") == tmp_path / "maps"  # untouched sibling key survives


def test_tools_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MAPFORGE_TOOLS_DIR", str(tmp_path))
    assert load_config().path("tools_dir") == tmp_path


def test_deep_merge_replaces_non_dicts():
    assert deep_merge({"a": {"b": 1, "c": [1]}}, {"a": {"c": [2]}}) == {"a": {"b": 1, "c": [2]}}
