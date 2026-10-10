import numpy as np
import pytest
from conftest import needs_compilers

from mapforge.bsp.reader import read_bsp
from mapforge.bsp.writer import write_with_entities
from mapforge.compile.run import compile_map
from mapforge.config import load_config
from mapforge.refmaps_variants import spawnswap
from mapforge.wad.dev_textures import main as make_dev_wad


@pytest.mark.slow
@needs_compilers
def test_entity_rewrite_keeps_geometry(tmp_path):
    make_dev_wad()
    src = compile_map(load_config(), "test_box")
    before = read_bsp(src)
    dst = tmp_path / "swapped.bsp"
    write_with_entities(src, dst, spawnswap(before.entities))
    after = read_bsp(dst)
    # geometry identical
    assert np.array_equal(before.vertices, after.vertices)
    assert np.array_equal(before.faces, after.faces) and before.lighting == after.lighting
    # T spawns now sit on the CT spawn positions
    ct = sorted(e["origin"] for e in after.entities if e["classname"] == "info_player_start")
    t = sorted(e["origin"] for e in after.entities if e["classname"] == "info_player_deathmatch")
    assert t == ct
