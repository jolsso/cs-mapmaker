import copy

import numpy as np
import pytest
from conftest import needs_compilers

from mapforge.config import Config, load_config
from mapforge.generator.build import door_box, generate
from mapforge.generator.spec import SpecError, parse_layout
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.writer import write_map

SMALL = {
    "name": "de_gen_small",
    "areas": [
        {"name": "t_spawn", "rect": [-1024, -256, -512, 256], "height": 192},
        {"name": "mid", "rect": [-496, -128, 496, 128], "height": 160},
        {"name": "ct_spawn", "rect": [512, -256, 1024, 256], "height": 256, "outdoor": True},
        {"name": "a_site", "rect": [-496, 144, 496, 656], "floor": 32, "height": 224},
        {"name": "b_site", "rect": [-496, -656, 496, -144], "height": 192},
    ],
    "doors": [
        {"name": "t_mid", "between": ["t_spawn", "mid"], "width": 128},
        {"name": "mid_ct", "between": ["mid", "ct_spawn"], "width": 128},
        {"name": "mid_a", "between": ["mid", "a_site"], "width": 160},
        {"name": "mid_b", "between": ["mid", "b_site"], "width": 160},
    ],
    "stairs": [
        {"name": "a_steps", "area": "a_site", "axis": "+y", "rise": 32, "step": 16, "start": -64}
    ],
    "cover": [{"name": "a_box", "area": "a_site", "pos": [0, 512], "size": [64, 64, 64]}],
    "sites": {"A": "a_site", "B": "b_site"},
    "spawns": {"T": {"area": "t_spawn", "count": 10}, "CT": {"area": "ct_spawn", "count": 10}},
}


def layout(**over):
    data = copy.deepcopy(SMALL)
    data.update(over)
    return parse_layout(data)


def test_door_box_goes_through_the_wall():
    lay = layout()
    lo, hi = door_box(lay.doors[0], lay.areas, lay.wall)
    assert lo == (-512, -64, 0) and hi == (-496, 64, 160)  # wall x=-512..-496, width 128


def test_shell_is_sealed_and_fills_exactly_the_solid_volume():
    g = generate(layout(stairs=[], cover=[]))
    brushes = g.mapfile.worldspawn.brushes
    vols = []
    for b in brushes:
        v = brush_geometry(b).vertices
        assert not np.any(np.abs(v - np.round(v / 16) * 16) > 1e-6), "off the 16 grid"
        vols.append(np.prod(v.max(axis=0) - v.min(axis=0)))
    lo = np.min([v[0] for v in g.voids.values()], axis=0) - 16
    hi = np.max([v[1] for v in g.voids.values()], axis=0) + 16
    empty = sum(np.prod(np.subtract(b[1], b[0])) for b in g.voids.values())
    assert sum(vols) == np.prod(hi - lo) - empty  # solid + empty = shell, no overlaps or gaps


def test_entities():
    g = generate(layout())
    cls = [e.classname for e in g.mapfile.entities]
    assert cls.count("info_player_deathmatch") == 10 and cls.count("info_player_start") == 10
    assert cls.count("func_bomb_target") == 2 and cls.count("func_buyzone") == 2
    assert cls.count("light_environment") == 1 and cls.count("light") >= 4


@pytest.mark.parametrize(
    ("over", "msg"),
    [
        (
            {"doors": [{"name": "x", "between": ["t_spawn", "b_site"], "width": 128}]},
            "do not share",
        ),
        ({"doors": [{"name": "x", "between": ["t_spawn", "nope"], "width": 64}]}, "unknown area"),
        ({"stairs": [{"name": "s", "area": "mid", "axis": "+y", "rise": 40, "step": 20}]}, "> 18"),
        ({"areas": [{"name": "a", "rect": [0, 0, 100, 64]}]}, "off the 16-unit grid"),
        ({"spawns": {"T": {"area": "mid", "count": 99}, "CT": {"area": "ct_spawn"}}}, "fits"),
    ],
)
def test_spec_errors(over, msg):
    with pytest.raises(SpecError, match=msg):
        generate(layout(**over))


@pytest.mark.slow
@needs_compilers
def test_generated_map_compiles_and_validates(tmp_path):
    from mapforge.compile.run import compile_map
    from mapforge.validate.run import validate_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    cfg = Config(root=base.root, data=data)
    write_map(
        generate(layout()).mapfile, tmp_path / "maps" / "de_gen_small" / "src" / "de_gen_small.map"
    )
    make_dev_wad()
    compile_map(cfg, "de_gen_small")
    v = validate_map(cfg, "de_gen_small")
    errors = [f for f in v["findings"] if f["severity"] == "error"]
    assert v["ok"], errors
    assert all(
        s["spawns_reaching"] == {"T": 10, "CT": 10} for s in v["stats"]["reachability"]["sites"]
    )
