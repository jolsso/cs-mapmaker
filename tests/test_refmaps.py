import copy
import shutil

import pytest
from conftest import needs_compilers

from mapforge.compile.run import compile_map
from mapforge.config import Config, load_config
from mapforge.refmaps import extract_archives, find_reference_bsp, list_reference_maps
from mapforge.validate.run import validate_map
from mapforge.wad.dev_textures import main as make_dev_wad


@pytest.fixture
def ref_cfg(tmp_path) -> Config:
    cfg = load_config()
    data = copy.deepcopy(cfg.data)
    data["reference_maps"] = {
        "archives_dir": str(tmp_path / "archives"),
        "extract_dir": str(tmp_path / "extracted"),
        "dirs": [str(tmp_path / "extracted"), str(tmp_path / "loose"), "/does/not/exist"],
    }
    data["paths"]["build_dir"] = str(tmp_path / "build")
    return Config(root=cfg.root, data=data)


def test_find_reference_bsp_searches_dirs_in_order(ref_cfg, tmp_path):
    (tmp_path / "loose" / "maps").mkdir(parents=True)
    (tmp_path / "loose" / "maps" / "de_x.bsp").write_bytes(b"")
    assert find_reference_bsp(ref_cfg, "de_x") == tmp_path / "loose" / "maps" / "de_x.bsp"
    assert find_reference_bsp(ref_cfg, "de_missing") is None
    assert list(list_reference_maps(ref_cfg)) == ["de_x"]


def test_no_archives_is_fine(ref_cfg):
    assert extract_archives(ref_cfg) == []


@pytest.mark.skipif(shutil.which("unar") is None, reason="unar only in the forge image")
def test_zip_is_unpacked_once(ref_cfg, tmp_path):
    archives = tmp_path / "archives"
    archives.mkdir()
    src = tmp_path / "zipsrc" / "maps"
    src.mkdir(parents=True)
    (src / "de_z.bsp").write_bytes(b"x")
    shutil.make_archive(str(archives / "pack"), "zip", tmp_path / "zipsrc")
    [dest] = extract_archives(ref_cfg)
    assert (dest / "maps" / "de_z.bsp").read_bytes() == b"x"
    marker = (dest / ".source-sha256").stat().st_mtime_ns
    extract_archives(ref_cfg)  # unchanged archive: not unpacked again
    assert (dest / ".source-sha256").stat().st_mtime_ns == marker


@pytest.mark.slow
@needs_compilers
def test_test_box_bsp_validates_as_reference(tmp_path):
    """Reference mode reads only the .bsp: no compile.json, no .map checks."""
    cfg = load_config()
    make_dev_wad()
    bsp = compile_map(cfg, "test_box")
    ref = tmp_path / "test_box.bsp"
    shutil.copy(bsp, ref)
    result = validate_map(cfg, "test_box", reference_bsp=ref)
    assert result["source"] == "reference"
    assert result["inputs"]["map"] is None
    assert not any(f["source"] in ("map", "compile") for f in result["findings"])
    assert result["stats"]["entities"]["spawns"] == {"T": 2, "CT": 2}
