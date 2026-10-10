import numpy as np
import pytest
from conftest import needs_compilers

from mapforge.bsp.reader import CONTENTS_EMPTY, CONTENTS_SOLID, read_bsp
from mapforge.compile.run import compile_map
from mapforge.config import load_config
from mapforge.wad.dev_textures import main as make_dev_wad


@pytest.fixture(scope="module")
def test_box_bsp():
    make_dev_wad()
    return read_bsp(compile_map(load_config(), "test_box"))


pytestmark = [pytest.mark.slow, needs_compilers]


def test_lumps(test_box_bsp):
    b = test_box_bsp
    c = b.counts()
    assert c["models"] == 1 and c["visleafs"] == 1
    assert [t.name for t in b.textures] == ["DEV_CEIL", "DEV_FLOOR", "DEV_WALL"]
    assert all(t.embedded for t in b.textures)
    assert [e["classname"] for e in b.entities].count("info_player_start") == 2
    assert b.models[0]["mins"].tolist() == [-528, -528, -16]


def test_hull_contents(test_box_bsp):
    pts = np.array([[0, 0, 40], [0, 0, -100], [0, 0, 30], [-490, 0, 40], [-500, 0, 40]])
    E, S = CONTENTS_EMPTY, CONTENTS_SOLID
    assert test_box_bsp.point_contents(pts, hull=0).tolist() == [E, S, E, E, E]
    # hull 1 (32x32x72): floor raised to z=36, walls pushed in by 16
    assert test_box_bsp.point_contents(pts, hull=1).tolist() == [E, S, S, E, S]


def test_every_face_is_lit(test_box_bsp):
    b = test_box_bsp
    means = [b.face_lightmap(i).mean() for i in range(len(b.faces))]
    assert min(means) > 50  # 1 light, 8 bounces: no black faces in a closed box
    total = sum(int(np.prod(b.lightmap_size(i))) * 3 for i in range(len(b.faces)))
    assert total <= len(b.lighting)
