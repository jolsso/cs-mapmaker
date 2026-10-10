import numpy as np
import pytest
from conftest import needs_compilers

from mapforge.bsp.reader import read_bsp
from mapforge.compile.run import compile_map
from mapforge.config import load_config
from mapforge.validate.walk import STAND, build_walk_graph
from mapforge.wad.dev_textures import main as make_dev_wad

pytestmark = [pytest.mark.slow, needs_compilers]


@pytest.fixture(scope="module")
def box():
    make_dev_wad()
    return read_bsp(compile_map(load_config(), "test_box"))


def test_flood_fill_covers_the_room(box):
    g = build_walk_graph(box, np.array([[0, 0, 36]]))
    assert g.seeds[0] is not None
    standing = g.stance == STAND
    assert standing.sum() == 124 * 124  # same cells as the room's walkable area (1024-32)^2/64
    assert np.all(g.feet[standing, 2] == 0)  # everyone stands on the floor
