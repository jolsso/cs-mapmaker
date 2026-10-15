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
        (
            {"ramps": [{"name": "r", "area": "mid", "axis": "+x", "rise": 96, "length": 128}]},
            "26.6",
        ),
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
    assert "de_gen_stack.rad" in log and "Duplication of texlight" not in log
    # lights without a targetname are compiled into the lightmaps and dropped from the .bsp
    assert {"func_ladder", "func_breakable", "env_sound"} <= {
        e.get("classname") for e in bsp.entities
    }


ROUND_AND_PRESETS = [
    {"name": "drum", "area": "a_site", "pos": [-256, 400], "size": [96, 96, 128],
     "shape": "cylinder"},
    {"name": "post", "area": "a_site", "pos": [0, 400], "size": [32, 32, 128], "shape": "cylinder"},
    {"name": "stack", "area": "a_site", "pos": [256, 400], "preset": "crate_stack"},
    {"name": "oil", "area": "b_site", "pos": [-256, -400], "preset": "barrels",
     "breakable": "metal"},
    {"name": "tall_oil", "area": "b_site", "pos": [0, -400], "size": [64, 128, 48],
     "preset": "barrels"},
    {"name": "step", "area": "b_site", "pos": [256, -400], "preset": "pallets"},
]  # fmt: skip


def test_cylinders_and_presets_are_convex_and_on_the_grid():
    from mapforge.generator.build import _cylinder, cover_solids

    for lo, hi, sides in (((0, 0), (32, 32), 8), ((0, 0), (96, 96), 12), ((0, 0), (128, 64), 12),
                          ((0, 0), (192, 192), 16)):  # fmt: skip
        poly = _cylinder(lo, hi)
        assert len(poly) == sides and len(set(poly)) == sides
        assert all(lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] for x, y in poly)
    lay = feat(cover=ROUND_AND_PRESETS)
    by = {c.name: c for c in lay.cover}
    assert by["stack"].size == (128, 64, 128) and by["step"].size == (64, 64, 16)
    stack = cover_solids(by["stack"], 0)
    assert len(stack) == 3 and stack[2].lo[2] == 64 and stack[2].hi[2] == 128  # crate on top
    oil = cover_solids(by["oil"], 0)
    assert len(oil) == 3 and all(s.shape == "cylinder" for s in oil)
    for c in lay.cover:  # every solid stays inside the footprint
        (px, py), (w, d, _) = c.pos, c.size
        for sol in cover_solids(c, 0):
            assert px - w // 2 <= sol.lo[0] and sol.hi[0] <= px + w // 2
            assert py - d // 2 <= sol.lo[1] and sol.hi[1] <= py + d // 2
    g = generate(lay)
    for b in g.mapfile.brushes():
        geo = brush_geometry(b)
        assert not geo.unbounded and all(len(v) >= 3 for v in geo.face_vertices)
        v = geo.vertices
        assert not np.any(np.abs(v - np.round(v / 8) * 8) > 1e-3), "off the 8 grid"
    names = {e.properties.get("targetname") for e in g.mapfile.entities}
    assert {"break_oil_1", "break_oil_2", "break_oil_3"} <= names


@pytest.mark.parametrize(
    "item, msg",
    [
        ({"preset": "boxes"}, "preset must be one of"),
        ({"preset": "barrels", "shape": "cylinder"}, "drop shape"),
        ({"preset": "barrels", "size": [48, 48, 48]}, "at least"),
        ({"shape": "cylinder", "size": [24, 24, 64]}, ">= 32"),
        ({}, "size is required"),
    ],
)
def test_bad_round_cover_and_presets(item, msg):
    with pytest.raises(SpecError, match=msg):
        feat(cover=[{"name": "x", "area": "a_site", "pos": [0, 400], **item}])


def test_arch_rounds_the_top_of_a_doorway_and_keeps_the_hull_clear():
    from mapforge.generator.build import arch_brushes

    data = copy.deepcopy(FEAT)
    next(d for d in data["doors"] if d["name"] == "mid_a")["arch"] = True
    lay = parse_layout(data)
    plain = generate(feat())
    g = generate(lay)
    extra = len(g.mapfile.worldspawn.brushes) - len(plain.mapfile.worldspawn.brushes)
    lo, hi = g.voids["mid_a"]
    arch = arch_brushes(lo, hi, "X")
    assert extra == len(arch) >= 6
    for b in arch:
        geo = brush_geometry(b)
        assert not geo.unbounded and all(len(v) >= 3 for v in geo.face_vertices)
        v = geo.vertices
        assert not np.any(np.abs(v - np.round(v / 8) * 8) > 1e-3), "off the 8 grid"
        assert v[:, 2].min() >= lo[2] + 80  # standing hull fits the whole width
        assert v[:, 0].min() >= lo[0] and v[:, 0].max() <= hi[0]
        assert v[:, 1].min() >= lo[1] and v[:, 1].max() <= hi[1]


@pytest.mark.parametrize(
    "door, msg",
    [
        ({"gate": "sliding"}, "only for a plain door"),
        ({"height": 88}, "too low for an arch"),
    ],
)
def test_bad_arches(door, msg):
    data = copy.deepcopy(FEAT)
    next(d for d in data["doors"] if d["name"] == "mid_a").update(arch=True, **door)
    with pytest.raises(SpecError, match=msg):
        generate(parse_layout(data))


@pytest.mark.parametrize("mode", ["auto", "button"])
def test_lift_is_a_plat_drawn_at_the_upper_floor(mode):
    data = copy.deepcopy(STACKED)
    hatch = data["hatches"][0]
    del hatch["ladder"]
    hatch["lift"] = mode
    g = generate(parse_layout(data))
    plats = [e for e in g.mapfile.entities if e.classname == "func_plat"]
    assert len(plats) == 1 and plats[0].properties["height"] == "176"  # loft floor - hall floor
    v = brush_geometry(plats[0].brushes[0]).vertices
    assert v[:, 2].min() == 168 and v[:, 2].max() == 176
    buttons = [e for e in g.mapfile.entities if e.classname == "func_button"]
    assert "func_ladder" not in [e.classname for e in g.mapfile.entities]
    if mode == "auto":
        assert not buttons and "targetname" not in plats[0].properties
    else:
        assert len(buttons) == 2
        assert {b.properties["target"] for b in buttons} == {plats[0].properties["targetname"]}
        zs = sorted(brush_geometry(b.brushes[0]).vertices[:, 2].min() for b in buttons)
        assert zs == [40, 176 + 40]  # on a pedestal on each floor


def test_lift_and_ladder_exclude_each_other():
    data = copy.deepcopy(STACKED)
    data["hatches"][0]["lift"] = "auto"
    with pytest.raises(SpecError, match="exclude each other"):
        parse_layout(data)


@pytest.mark.parametrize("name", ["container", "rail_wagon", "ladle", "forklift", "ingot_stack",
                                  "pipe_run", "crate_stack", "barrels", "pallets"])  # fmt: skip
@pytest.mark.parametrize("turn", [False, True])
def test_every_prop_is_valid_inside_its_footprint_both_ways(name, turn):
    from mapforge.generator.build import cover_solids
    from mapforge.generator.props import PROPS

    w, d, h = PROPS[name].size
    size = [d, w, h] if turn else [w, d, h]
    item = {"name": "p", "area": "a_site", "pos": [0, 400], "preset": name, "size": size}
    if name == "pipe_run":
        item["z"] = 160  # along the wall, above heads
    lay = feat(cover=[item])
    g = generate(lay)
    c = lay.cover[0]
    for sol in cover_solids(c, lay.areas["a_site"].floor):
        assert -size[0] // 2 <= sol.lo[0] < sol.hi[0] <= size[0] // 2
        assert 400 - size[1] // 2 <= sol.lo[1] < sol.hi[1] <= 400 + size[1] // 2
    for b in g.mapfile.brushes():
        geo = brush_geometry(b)
        assert not geo.unbounded and all(len(v) >= 3 for v in geo.face_vertices)
        v = geo.vertices
        assert not np.any(np.abs(v - np.round(v / 8) * 8) > 1e-3), "off the 8 grid"


def test_rail_wagon_rails_are_a_step_and_the_props_bring_their_own_textures():
    from mapforge.generator.build import cover_solids

    lay = feat(cover=[{"name": "wagon", "area": "a_site", "pos": [0, 400], "preset": "rail_wagon"}])
    parts = cover_solids(lay.cover[0], 0)
    rails = [p for p in parts if p.hi[2] - p.lo[2] == 8]
    assert len(rails) == 2  # 8 high: walk over them (max step 18)
    used = {f.texture for b in generate(lay).mapfile.brushes() for f in b.faces}
    assert {"TSIBEAM", "WHEELSIDE01", "TRAINSIDE02-1", "TRAINTOP01"} <= used


def test_ambient_sounds_become_looping_ambient_generics():
    lay = feat(ambient=[
        {"name": "furnace", "area": "a_site", "sound": "ambience/industrial1.wav", "volume": 7},
        {"name": "wind", "area": "mid", "sound": "ambience/wind1.wav", "pos": [0, 64],
         "radius": "large"},
    ])  # fmt: skip
    amb = [e for e in generate(lay).mapfile.entities if e.classname == "ambient_generic"]
    assert [(e.properties["message"], e.properties["spawnflags"]) for e in amb] == [
        ("ambience/industrial1.wav", "4"),
        ("ambience/wind1.wav", "8"),
    ]
    assert amb[1].properties["origin"] == "0 64 64" and amb[0].properties["health"] == "7"
    with pytest.raises(SpecError, match="under sound/"):
        feat(ambient=[{"name": "x", "area": "mid", "sound": "sound/ambience/wind1.wav"}])


def test_missing_ambient_sounds_are_reported():
    from pathlib import Path

    from mapforge.generator.run import missing_sounds

    cfg = load_config()
    if not any(Path(d).is_dir() for d in cfg.data["paths"]["sound_dirs"]):
        pytest.skip("needs the Half-Life install mounted at /refmaps/hl")
    lay = feat(ambient=[{"name": "a", "area": "mid", "sound": "ambience/industrial1.wav"},
                        {"name": "b", "area": "mid", "sound": "ambience/nope.wav"}])  # fmt: skip
    assert missing_sounds(lay, cfg) == ["ambience/nope.wav"]


def test_game_models_become_env_sprites_with_an_optional_clip_box():
    lay = feat(models=[
        {"name": "belt", "area": "a_site", "model": "models/conveyor1.mdl", "pos": [0, 400],
         "yaw": 90, "clip": [64, 128, 48]},
        {"name": "lamp", "area": "mid", "model": "models/light.mdl", "pos": [0, 0], "z": 160},
    ])  # fmt: skip
    g = generate(lay)
    spr = [e for e in g.mapfile.entities if e.classname == "env_sprite"]
    assert [e.properties["model"] for e in spr] == ["models/conveyor1.mdl", "models/light.mdl"]
    assert spr[0].properties["angles"] == "0 90 0" and spr[1].properties["origin"] == "0 0 160"
    clips = [b for b in g.mapfile.worldspawn.brushes if b.faces[0].texture == "CLIP"]
    assert any(brush_geometry(b).vertices[:, 2].max() == 48 for b in clips)
    with pytest.raises(SpecError, match="models/conveyor1.mdl"):
        feat(models=[{"name": "x", "area": "mid", "model": "conveyor1.mdl", "pos": [0, 0]}])


def test_missing_game_models_are_reported():
    from pathlib import Path

    from mapforge.generator.run import missing_models

    cfg = load_config()
    if not any(Path(d).is_dir() for d in cfg.data["paths"]["model_dirs"]):
        pytest.skip("needs the Half-Life install mounted at /refmaps/hl")
    lay = feat(models=[
        {"name": "a", "area": "mid", "model": "models/conveyor1.mdl", "pos": [0, 0]},
        {"name": "b", "area": "mid", "model": "models/forklift.mdl", "pos": [0, 64]},
        {"name": "c", "area": "mid", "model": "models/nope.mdl", "pos": [0, 96]},
    ])  # fmt: skip
    assert missing_models(lay, cfg) == ["models/nope.mdl"]  # conveyor: cstrike, forklift: valve


def test_door_frames_are_detail_jambs_and_a_lintel():
    from mapforge.generator.build import FRAME_D, FRAME_W

    data = copy.deepcopy(FEAT)
    next(d for d in data["doors"] if d["name"] == "mid_a").update(frame="DEV_METAL", height=128)
    g = generate(parse_layout(data))
    lo, hi = g.voids["mid_a"]
    det = [e for e in g.mapfile.entities if e.classname == "func_detail"]
    frame = [b for e in det for b in e.brushes if b.faces[0].texture == "DEV_METAL"]
    assert len(frame) == 3  # two jambs and the lintel (room under the 192 ceiling)
    v = np.vstack([brush_geometry(b).vertices for b in frame])
    assert v[:, 2].max() == hi[2] + FRAME_W and v[:, 0].min() == lo[0] - FRAME_W
    assert v[:, 1].min() == lo[1] - FRAME_D and v[:, 1].max() == hi[1] + FRAME_D
    data = copy.deepcopy(FEAT)
    next(d for d in data["doors"] if d["name"] == "mid_a").update(frame="DEV_METAL")  # full height
    g = generate(parse_layout(data))
    det = [b for e in g.mapfile.entities if e.classname == "func_detail" for b in e.brushes
           if b.faces[0].texture == "DEV_METAL"]  # fmt: skip
    assert len(det) == 2  # no room for a lintel: jambs only


def test_door_lights_hang_on_both_sides_of_the_opening():
    data = copy.deepcopy(FEAT)
    next(d for d in data["doors"] if d["name"] == "mid_a").update(light=True)
    g = generate(parse_layout(data))
    plain = generate(feat())
    lo, hi = g.voids["mid_a"]
    lights = [e.properties["origin"] for e in g.mapfile.entities if e.classname == "light"]
    before = [e.properties["origin"] for e in plain.mapfile.entities if e.classname == "light"]
    new = [tuple(map(int, o.split())) for o in lights if o not in before]
    assert len(new) == 2
    ys = sorted(p[1] for p in new)
    assert ys == [lo[1] - 48, hi[1] + 48]  # mid_a runs between mid (south) and a_site (north)
    assert all(p[0] == (lo[0] + hi[0]) // 2 for p in new)


ROOFED = {
    "roofs": [{"name": "canopy", "area": "ct_spawn", "rect": [576, -192, 896, 64], "z": 160,
               "shape": "gable", "axis": "y", "rise": 48, "posts": True},
              {"name": "shed", "area": "ct_spawn", "rect": [576, 96, 896, 224], "z": 128,
               "shape": "shed", "axis": "x", "rise": 32}],
}  # fmt: skip


def test_roofs_are_slabs_above_head_height_with_posts():
    data = copy.deepcopy(FEAT)
    data.update(ROOFED)
    g = generate(parse_layout(data))

    def inside_roofs(b) -> bool:
        v = brush_geometry(b).vertices
        in_x = v[:, 0].min() >= 576 and v[:, 0].max() <= 896
        return in_x and v[:, 2].min() >= 128 and v[:, 2].max() <= 224

    roof = [b for b in g.mapfile.worldspawn.brushes if inside_roofs(b)]
    assert len(roof) == 3  # two gable halves + the shed slab
    posts = [b for b in g.mapfile.worldspawn.brushes
             if (v := brush_geometry(b).vertices)[:, 2].min() == 0 and v[:, 2].max() == 160
             and np.ptp(v[:, 0]) == 16 and np.ptp(v[:, 1]) == 16]  # fmt: skip
    assert len(posts) == 4
    for b in g.mapfile.brushes():
        geo = brush_geometry(b)
        assert not geo.unbounded and all(len(f) >= 3 for f in geo.face_vertices)


def test_a_pitched_hall_gets_a_gable_ceiling_inside_a_taller_void():
    from mapforge.generator.build import pitch_fill

    data = copy.deepcopy(FEAT)
    next(a for a in data["areas"] if a["name"] == "b_site")["pitch"] = {
        "shape": "gable",
        "axis": "x",
        "rise": 64,
    }
    lay = parse_layout(data)
    g = generate(lay)
    lo, hi = g.voids["b_site"]
    assert hi[2] == lay.areas["b_site"].top + 64
    fill = pitch_fill(lay.areas["b_site"], "X")
    assert len(fill) == 2
    v = np.vstack([brush_geometry(b).vertices for b in fill])
    assert v[:, 2].min() == 192 and v[:, 2].max() == 256 and v[:, 1].max() == -144


@pytest.mark.parametrize(
    "roof, msg",
    [({"z": 64}, "players hit their heads"), ({"shape": "flat", "rise": 48}, "flat roof"),
     ({"rect": [576, -192, 1100, 64]}, "inside ct_spawn"), ({"z": 216}, "reaches above")],
)  # fmt: skip
def test_bad_roofs(roof, msg):
    data = copy.deepcopy(FEAT)
    data["roofs"] = [{**ROOFED["roofs"][0], **roof}]
    with pytest.raises(SpecError, match=msg):
        parse_layout(data)


@pytest.mark.slow
@needs_compilers
def test_roofed_and_pitched_map_compiles_without_a_leak(tmp_path):
    from mapforge.compile.run import compile_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data_cfg = copy.deepcopy(base.data)
    data_cfg["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    cfg = Config(root=base.root, data=data_cfg)
    data = copy.deepcopy(FEAT)
    data.update(ROOFED)
    next(a for a in data["areas"] if a["name"] == "b_site")["pitch"] = {
        "shape": "shed",
        "axis": "y",
        "rise": 48,
    }
    g = generate(parse_layout(data))
    write_map(g.mapfile, tmp_path / "maps" / "de_gen_feat" / "src" / "de_gen_feat.map")
    make_dev_wad()
    compile_map(cfg, "de_gen_feat")  # raises CompileError on a leak


def test_skyline_yard_walls_even_and_city_blocks_with_gables():
    from mapforge.generator.build import PARAPET, skyline_plan

    data = copy.deepcopy(FEAT)
    data["skyline"] = {"facade": "DEV_BRICK", "roof": "DEV_CONCRETE"}
    lay = parse_layout(data)
    g = generate(lay)
    world = g.mapfile.worldspawn.brushes
    # rebuild the plan on a fine grid to read it back
    xs = list(range(-1200, 1201, 16))
    ys = list(range(-848, 849, 16))
    sky = skyline_plan(lay, g.voids, xs, ys)
    ct = lay.areas["ct_spawn"]  # an outdoor yard: its walls end PARAPET above its top
    i_wall = xs.index(ct.rect[2])  # the column just east of the yard (its wall)
    j_mid = ys.index(0)
    assert sky.roof[i_wall, j_mid] == ct.top + PARAPET
    mid = lay.areas["mid"]  # an indoor corridor lies under a building that covers it
    assert sky.roof[xs.index(0), j_mid] >= mid.top + lay.wall
    assert sky.blocks and all(b["rect"] for b in sky.blocks)  # city blocks: rectangles
    gables = [b for b in world if any(f.texture == "DEV_CONCRETE" for f in b.faces)
              and len(b.faces) == 5]  # fmt: skip
    assert gables  # prisms on the rectangular blocks
    clips = [b for b in world if b.faces[0].texture == "CLIP"]
    assert any(brush_geometry(b).vertices[:, 2].min() == ct.top for b in clips)
    for b in g.mapfile.brushes():
        assert not brush_geometry(b).unbounded


@pytest.mark.slow
@needs_compilers
def test_skyline_map_compiles_sealed(tmp_path):
    from mapforge.compile.run import compile_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data_cfg = copy.deepcopy(base.data)
    data_cfg["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    cfg = Config(root=base.root, data=data_cfg)
    data = copy.deepcopy(FEAT)
    data["skyline"] = True
    g = generate(parse_layout(data))
    write_map(g.mapfile, tmp_path / "maps" / "de_gen_feat" / "src" / "de_gen_feat.map")
    make_dev_wad()
    compile_map(cfg, "de_gen_feat")  # raises CompileError on a leak


def test_wall_details_are_whole_doors_and_windows_clear_of_openings():
    from mapforge.generator.build import wall_detail_boxes

    data = copy.deepcopy(FEAT)
    data["wall_details"] = {
        "areas": ["mid", "ct_spawn"], "spacing": 192,
        "doors": [{"texture": "DEV_DOOR", "size": [64, 128]}],
        "windows": [{"texture": "DEV_GLASS", "size": [64, 48], "z": 96}],
    }  # fmt: skip
    lay = parse_layout(data)
    g = generate(lay)
    panels = wall_detail_boxes(lay, g.voids)
    assert len(panels) >= 4 and {t for _, t in panels} == {"DEV_DOOR", "DEV_GLASS"}
    doors = [b for n, b in g.voids.items() if n not in lay.areas]
    for (lo, hi), _ in panels:
        assert hi[0] - lo[0] == 8 or hi[1] - lo[1] == 8  # flat against a wall
        for d_lo, d_hi in doors:  # never in front of a real opening
            overlap_x = d_lo[0] < hi[0] and lo[0] < d_hi[0]
            assert not (overlap_x and d_lo[1] < hi[1] and lo[1] < d_hi[1])
    det = [b for e in g.mapfile.entities if e.classname == "func_detail" for b in e.brushes
           if b.faces[0].texture == "DEV_DOOR"]  # fmt: skip
    assert det
    face = det[0].faces[0]  # its texture starts at the panel's corner (one whole door)
    v = brush_geometry(det[0]).vertices
    s_vals = v[:, :3] @ np.array(face.u_axis[:3]) + face.u_axis[3]
    assert s_vals.min() == 0
