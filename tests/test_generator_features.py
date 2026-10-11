"""Generator features beyond boxes: ramps, wedges, raised cover, windows/vents, glass, gates,
ladders, stair clips, zones, weapons, map parameters, func_detail."""

import copy

import numpy as np
import pytest
from conftest import needs_compilers

from mapforge.config import Config, load_config
from mapforge.generator.build import door_box, generate
from mapforge.generator.spec import SpecError, parse_layout
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.writer import write_map

FEAT = {
    "name": "de_gen_feat",
    "detail": True,
    "zones": {
        "a": {
            "floor": "DEV_FLOOR_RED",
            "wall": "DEV_WALL_RED",
            "ceiling": "DEV_CEIL_RED",
            "light": {"color": [255, 200, 180]},
        },
        "b": {"floor": "DEV_FLOOR_BLUE", "wall": "DEV_WALL_BLUE", "ceiling": "DEV_CEIL_BLUE"},
    },  # fmt: skip
    "areas": [
        {"name": "t_spawn", "rect": [-1024, -256, -512, 256], "height": 192},
        {"name": "mid", "rect": [-496, -128, 496, 128], "height": 192},
        {"name": "ct_spawn", "rect": [512, -256, 1024, 256], "height": 256, "outdoor": True},
        {"name": "a_site", "rect": [-496, 144, 496, 656], "height": 288, "zone": "a"},
        {"name": "b_site", "rect": [-496, -656, 496, -144], "height": 192, "zone": "b"},
    ],
    "doors": [
        {"name": "t_mid", "between": ["t_spawn", "mid"], "width": 128, "gate": "rotating"},
        {"name": "mid_ct", "between": ["mid", "ct_spawn"], "width": 128, "gate": "sliding"},
        {"name": "mid_a", "between": ["mid", "a_site"], "width": 160},
        {"name": "mid_b", "between": ["mid", "b_site"], "width": 160},
        {
            "name": "mid_a_win",
            "between": ["mid", "a_site"],
            "width": 96,
            "offset": 256,
            "kind": "window",
            "sill": 80,
            "height": 64,
            "glass": True,
        },
        {
            "name": "t_b_vent",
            "between": ["t_spawn", "b_site"],
            "width": 64,
            "kind": "vent",
            "height": 48,
        },
    ],  # fmt: skip
    "ramps": [
        {"name": "a_ramp", "area": "a_site", "axis": "+y", "rise": 64, "length": 128, "start": 128}
    ],  # fmt: skip
    "wedges": [
        {"name": "b_chamfer", "area": "b_site", "corner": "sw", "size": [192, 192]},
        {"name": "t_chamfer", "area": "t_spawn", "corner": "nw", "size": [128, 64]},
    ],
    "stairs": [
        {
            "name": "ct_steps",
            "area": "ct_spawn",
            "axis": "+x",
            "rise": 32,
            "step": 16,
            "start": 448,
            "clip": True,
        }
    ],  # fmt: skip
    "cover": [
        {"name": "a_box", "area": "a_site", "pos": [0, 512], "size": [64, 64, 64], "z": 64},
        {"name": "a_box_top", "area": "a_site", "pos": [0, 512], "size": [32, 32, 32], "z": 128},
        {
            "name": "a_pillar",
            "area": "a_site",
            "pos": [-320, 512],
            "size": [64, 64, 288],
            "texture": "DEV_METAL",
        },
        {"name": "b_ledge", "area": "b_site", "pos": [384, -560], "size": [128, 128, 16], "z": 112},
    ],  # fmt: skip
    "ladders": [
        {"name": "b_ladder", "area": "b_site", "wall": "+x", "pos": -96, "width": 32, "height": 128}
    ],  # fmt: skip
    "weapons": [{"area": "mid", "pos": [0, 0], "item": "awp"}],
    "map_parameters": {"buying": "both"},
    "sites": {"A": "a_site", "B": "b_site"},
    "spawns": {"T": {"area": "t_spawn", "count": 10}, "CT": {"area": "ct_spawn", "count": 10}},
}


def feat(**over):
    data = copy.deepcopy(FEAT)
    data.update(over)
    return parse_layout(data)


def test_all_brushes_are_valid_convex_solids_on_the_grid():
    g = generate(feat())
    for b in g.mapfile.brushes():
        geo = brush_geometry(b)
        assert not geo.unbounded and len(geo.vertices) >= 4
        assert all(p is not None for p in geo.planes)
        assert all(len(v) >= 3 for v in geo.face_vertices), "redundant face"
        v = geo.vertices
        assert not np.any(np.abs(v - np.round(v / 8) * 8) > 1e-3), "off the 8 grid"


def test_wedge_is_a_triangle_with_a_45_degree_wall():
    g = generate(feat())
    # angled walls are structural (world), low solids go to func_detail
    world = g.mapfile.worldspawn.brushes
    tris = [brush_geometry(b).vertices for b in world if len(b.faces) == 5]
    b_wedge = next(v for v in tris if v[:, 0].min() == -496 and v[:, 1].min() == -656)
    xy = {(round(x), round(y)) for x, y, _ in b_wedge}
    assert xy == {(-496, -656), (-304, -656), (-496, -464)}


def test_window_starts_at_its_sill_and_vent_is_crouch_height():
    lay = feat()
    win = next(d for d in lay.doors if d.name == "mid_a_win")
    lo, hi = door_box(win, lay.areas, lay.wall)
    assert lo[2] == 80 and hi[2] == 144 and not win.walkable
    vent = next(d for d in lay.doors if d.name == "t_b_vent")
    assert vent.walkable and vent.height == 48


def test_entities_of_the_features():
    g = generate(feat())
    cls = [e.classname for e in g.mapfile.entities]
    for c in ("func_breakable", "func_door", "func_door_rotating", "func_ladder",
              "func_illusionary", "armoury_entity", "info_map_parameters",
              "func_detail"):  # fmt: skip
        assert c in cls, c
    rot = next(e for e in g.mapfile.entities if e.classname == "func_door_rotating")
    assert any(f.texture == "ORIGIN" for b in rot.brushes for f in b.faces)
    awp = next(e for e in g.mapfile.entities if e.classname == "armoury_entity")
    assert awp.properties["item"] == "10"
    clips = [b for b in g.mapfile.worldspawn.brushes if b.faces[0].texture == "CLIP"]
    assert len(clips) == 1


def test_zones_texture_the_faces_of_their_areas():
    g = generate(feat())
    used = {f.texture for b in g.mapfile.worldspawn.brushes for f in b.faces}
    assert {"DEV_FLOOR_RED", "DEV_WALL_RED", "DEV_FLOOR_BLUE", "DEV_FLOOR", "DEV_WALL"} <= used
    # the a_site floor (top face at z=0 under a_site) is red
    for b in g.mapfile.worldspawn.brushes:
        v = brush_geometry(b).vertices
        if (
            v[:, 2].max() == 0
            and v[:, 0].min() >= -496
            and v[:, 0].max() <= 496
            and v[:, 1].min() >= 144
        ):
            assert any(f.texture == "DEV_FLOOR_RED" for f in b.faces)
    lights = [e for e in g.mapfile.entities if e.classname == "light"]
    assert any(e.properties["_light"].startswith("255 200 180") for e in lights)


def test_without_new_keys_the_output_is_unchanged():
    data = copy.deepcopy(FEAT)
    for k in ("zones", "ramps", "wedges", "ladders", "weapons", "map_parameters", "detail"):
        data.pop(k)
    for a in data["areas"]:
        a.pop("zone", None)
    lay = parse_layout(data)
    assert not lay.detail and not lay.zones


@pytest.mark.parametrize(
    ("over", "msg"),
    [
        ({"ramps": [{"name": "r", "area": "mid", "axis": "+x", "rise": 128, "length": 64}]}, "45"),
        ({"wedges": [{"name": "w", "area": "mid", "corner": "up", "size": [64, 64]}]}, "corner"),
        ({"wedges": [{"name": "w", "area": "mid", "corner": "ne", "size": [64, 999]}]}, "fit"),
        (
            {
                "doors": [
                    {
                        "name": "w",
                        "between": ["mid", "a_site"],
                        "width": 96,
                        "kind": "window",
                        "sill": 16,
                    }
                ]
            },
            "sill >= 64",
        ),  # fmt: skip
        (
            {
                "doors": [
                    {
                        "name": "v",
                        "between": ["mid", "a_site"],
                        "width": 64,
                        "kind": "vent",
                        "height": 96,
                    }
                ]
            },
            "40..64",
        ),  # fmt: skip
        (
            {
                "cover": [
                    {"name": "c", "area": "mid", "pos": [0, 0], "size": [32, 32, 64], "z": 160}
                ]
            },
            "leaves its area",
        ),  # fmt: skip
        ({"areas": [*FEAT["areas"][:4], {**FEAT["areas"][4], "zone": "nope"}]}, "unknown zone"),
    ],
)
def test_feature_spec_errors(over, msg):
    with pytest.raises(SpecError, match=msg):
        generate(feat(**over))


@pytest.mark.slow
@needs_compilers
def test_feature_map_compiles_and_validates(tmp_path):
    from mapforge.bsp.reader import read_bsp
    from mapforge.compile.run import compile_map
    from mapforge.validate.run import validate_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    data["validate"]["design"]["off"] = True
    cfg = Config(root=base.root, data=data)
    write_map(
        generate(feat()).mapfile, tmp_path / "maps" / "de_gen_feat" / "src" / "de_gen_feat.map"
    )
    make_dev_wad()
    bsp_path = compile_map(cfg, "de_gen_feat")
    v = validate_map(cfg, "de_gen_feat")
    errors = [f for f in v["findings"] if f["severity"] == "error"]
    assert v["ok"], errors
    bsp = read_bsp(bsp_path)
    cls = {e.get("classname") for e in bsp.entities}
    assert "func_detail" not in cls  # SDHLT merges func_detail into the world
    assert {"func_ladder", "func_breakable", "func_door", "func_door_rotating"} <= cls


STACKED = {
    "name": "de_gen_stack",
    "sounds": True,
    "areas": [
        {"name": "t_spawn", "rect": [-1024, -256, -512, 256], "height": 192},
        {
            "name": "hall",
            "rect": [-496, -256, 496, 256],
            "height": 160,
            "light": {"brightness": 300},
        },
        {"name": "loft", "rect": [-496, -256, 496, 256], "floor": 176, "height": 160},
        {"name": "ct_spawn", "rect": [512, -256, 1024, 256], "height": 192},
        {"name": "a_site", "rect": [-496, 272, 496, 784], "height": 192},
        {"name": "b_site", "rect": [-496, -784, 496, -272], "height": 192},
    ],
    "diagonals": [{"name": "diag", "rect": [512, 272, 1024, 784], "width": 192, "dir": "ne"}],
    "doors": [
        {"name": "t_hall", "between": ["t_spawn", "hall"], "width": 128},
        {"name": "hall_ct", "between": ["hall", "ct_spawn"], "width": 128},
        {"name": "hall_a", "between": ["hall", "a_site"], "width": 160},
        {"name": "hall_b", "between": ["hall", "b_site"], "width": 160},
    ],
    "hatches": [
        {
            "name": "h1",
            "lower": "hall",
            "upper": "loft",
            "rect": [256, -64, 320, 64],
            "ladder": "+x",
        }
    ],  # fmt: skip
    "water": [{"name": "pool", "area": "b_site", "rect": [-256, -704, 256, -448], "depth": 24}],
    "spots": [{"name": "s1", "area": "a_site", "pos": [0, 528], "z": 176}],
    "cover": [
        {
            "name": "pillar",
            "area": "a_site",
            "pos": [-256, 528],
            "size": [64, 64, 192],
            "shape": "octagon",
            "texture": "DEV_CONCRETE",
        },
        {
            "name": "crate",
            "area": "b_site",
            "pos": [320, -528],
            "size": [64, 64, 64],
            "breakable": "wood",
        },
        {
            "name": "lamp",
            "area": "a_site",
            "pos": [256, 528],
            "size": [64, 64, 8],
            "z": 176,
            "texture": "DEV_LIGHT",
        },
    ],  # fmt: skip
    "sites": {"A": "a_site", "B": "b_site"},
    "spawns": {"T": {"area": "t_spawn", "count": 10}, "CT": {"area": "ct_spawn", "count": 10}},
}


def test_stacked_levels_hatch_water_lights_sound_shapes():
    lay = parse_layout(copy.deepcopy(STACKED))
    assert {w.name for w in lay.wedges} == {"diag_nw", "diag_se"} and "diag" in lay.areas
    g = generate(lay)
    lo, hi = g.voids["h1"]
    assert lo[2] == 160 and hi[2] == 176  # the hole through the slab
    cls = [e.classname for e in g.mapfile.entities]
    assert cls.count("func_ladder") == 1 and "light_spot" in cls and "func_breakable" in cls
    assert cls.count("env_sound") == len(lay.areas)
    sounds = {e.properties["roomtype"] for e in g.mapfile.entities if e.classname == "env_sound"}
    assert "15" in sounds  # the wet site
    assert any(f.texture == "!WATER" for b in g.mapfile.worldspawn.brushes for f in b.faces)
    octs = [b for b in g.mapfile.worldspawn.brushes if len(b.faces) == 10]
    assert octs and not brush_geometry(octs[0]).unbounded
    assert g.rad.startswith("DEV_LIGHT ")
    hall = [e for e in g.mapfile.entities if e.classname == "light"]
    assert any(e.properties["_light"].endswith(" 300") for e in hall)


@pytest.mark.slow
@needs_compilers
def test_stacked_map_compiles_with_texlights(tmp_path):
    from mapforge.bsp.reader import read_bsp
    from mapforge.compile.run import compile_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    cfg = Config(root=base.root, data=data)
    g = generate(parse_layout(copy.deepcopy(STACKED)))
    src = tmp_path / "maps" / "de_gen_stack" / "src" / "de_gen_stack.map"
    write_map(g.mapfile, src)
    src.with_suffix(".rad").write_text(g.rad)
    make_dev_wad()
    bsp = read_bsp(compile_map(cfg, "de_gen_stack"))
    log = (tmp_path / "build" / "de_gen_stack" / "compile.log").read_text()
    assert "de_gen_stack.rad" in log
    # lights without a targetname are compiled into the lightmaps and dropped from the .bsp
    assert {"func_ladder", "func_breakable", "env_sound"} <= {
        e.get("classname") for e in bsp.entities
    }
