import struct

import pytest

from mapforge.compile.run import CompileError, compile_map, prepare_map, tool_paths
from mapforge.config import load_config
from mapforge.wad.dev_textures import main as make_dev_wad


def test_prepare_map_rewrites_wad_key(tmp_path):
    wad_dir = tmp_path / "wads"
    wad_dir.mkdir()
    (wad_dir / "a.wad").write_bytes(b"WAD3")
    src = tmp_path / "in.map"
    src.write_text('{\n"classname" "worldspawn"\n"wad" "\\old\\path\\a.wad"\n}\n')
    dest = tmp_path / "out.map"

    wads = prepare_map(src, dest, [wad_dir])

    assert wads == [(wad_dir / "a.wad").resolve()]
    assert f'"wad" "{wads[0].as_posix()}"' in dest.read_text()


def test_prepare_map_missing_wad(tmp_path):
    src = tmp_path / "in.map"
    src.write_text('{\n"classname" "worldspawn"\n"wad" "nope.wad"\n}\n')
    with pytest.raises(CompileError, match="nope.wad"):
        prepare_map(src, tmp_path / "out.map", [tmp_path])


def _compilers_present() -> bool:
    try:
        tool_paths(load_config())
    except CompileError:
        return False
    return True


@pytest.mark.slow
@pytest.mark.skipif(not _compilers_present(), reason="compilers not fetched")
def test_test_box_compiles():
    make_dev_wad()
    bsp = compile_map(load_config(), "test_box", "fast")
    assert struct.unpack_from("<i", bsp.read_bytes())[0] == 30  # GoldSrc BSP version
    log = (bsp.parent / "compile.log").read_text(encoding="utf-8")
    assert "LEAK" not in log
