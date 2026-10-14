"""Phase 6b, last item: polygon areas (angled walls at any grid angle), the `corridors:` macro,
bridges across tall areas, and space stacked over outdoor areas (overpasses)."""

import copy
import math

import numpy as np
import pytest
from conftest import needs_compilers

from mapforge.config import Config, load_config
from mapforge.generator.build import _poly_fill, door_box, generate
from mapforge.generator.spec import SpecError, corridor_poly, parse_layout
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.writer import write_map
from mapforge.validate.design import layout_graph

# T spawn west, CT spawn east; mid is a tall street (outdoor) with a bridge across it between
# two upper rooms; a 1:2 angled corridor climbs from T spawn to A; a covered overpass crosses
# over an outdoor yard south of CT; a hexagonal room north of CT.
ANGLED = {
    "name": "de_gen_angle",
    "areas": [
        {"name": "t_spawn", "rect": [-1536, -256, -1024, 256], "height": 192},
        {"name": "street", "rect": [-1008, -256, 1008, 256], "height": 384, "outdoor": True},
        {"name": "ct_spawn", "rect": [1024, -256, 1536, 256], "height": 320},
        {"name": "a_site", "rect": [-1536, 976, -512, 1488], "floor": 64, "height": 224},
        {"name": "b_site", "rect": [-512, -1488, 512, -976], "height": 192},
        {"name": "north", "rect": [-256, 272, 256, 512], "floor": 160, "height": 160},
        {"name": "south", "rect": [-256, -512, 256, -272], "floor": 160, "height": 160},
        {"name": "b_hall", "rect": [-256, -960, 256, -528], "height": 256},
        {"name": "south_low", "rect": [-256, -512, 256, -272], "height": 144},
        {"name": "yard", "rect": [1024, -1008, 1536, -272], "height": 160, "outdoor": True},
        {"name": "over", "rect": [1216, -1008, 1344, -272], "floor": 176, "height": 128},
        {
            "name": "hex",
            "poly": [[1024, 400], [1216, 272], [1408, 272], [1536, 400], [1536, 624], [1024, 624]],
            "height": 192,
        },
    ],  # fmt: skip
    "corridors": [
        {
            "name": "t_long",
            "from": [-1280, 272],
            "to": [-960, 960],
            "width": 128,
            "floor": 0,
            "height": 192,
            "rise": 64,
            "between": ["t_spawn", "a_site"],
        },
    ],  # fmt: skip
    "bridges": [{"name": "deck", "area": "street", "axis": "y", "z": 176, "width": 128}],
    "doors": [
        {"name": "t_st", "between": ["t_spawn", "street"], "width": 128},
        {"name": "st_ct", "between": ["street", "ct_spawn"], "width": 128},
        {"name": "n_deck", "between": ["north", "street"], "width": 112},
        {"name": "s_deck", "between": ["south", "street"], "width": 112},
        {"name": "s_b", "between": ["south", "b_hall"], "width": 96, "kind": "vent", "height": 48},
        {"name": "hall_b", "between": ["b_hall", "b_site"], "width": 160},
        {"name": "st_low", "between": ["street", "south_low"], "width": 128},
        {"name": "ct_yard", "between": ["ct_spawn", "yard"], "width": 128, "offset": -128},
        {"name": "ct_over", "between": ["ct_spawn", "over"], "width": 112},
        {"name": "ct_hex", "between": ["ct_spawn", "hex"], "width": 128},
    ],  # fmt: skip
    "hatches": [
        {
            "name": "up",
            "lower": "south_low",
            "upper": "south",
            "rect": [128, -448, 192, -336],
            "ladder": "+x",
        },
    ],  # fmt: skip
    "sites": {"A": "a_site", "B": "b_site"},
    "spawns": {"T": {"area": "t_spawn", "count": 10}, "CT": {"area": "ct_spawn", "count": 10}},
}


def lay(**over):
    data = copy.deepcopy(ANGLED)
    data.update(over)
    return parse_layout(data)


def test_corridor_poly_keeps_its_width_across_the_slant():
    poly, along, half, length = corridor_poly(
        {"name": "c", "from": [0, 0], "to": [320, 960], "width": 128}, 16
    )
    assert along == "y" and length == 960
    # the end is wider than 128 by 1/cos(angle), rounded up to the grid
    assert 2 * half >= 128 * math.hypot(960, 320) / 960 and half % 16 == 0
    (ax, ay), (bx, by) = poly[0], poly[3]  # one long wall
    nx, ny = by - ay, ax - bx
    across = abs((poly[1][0] - ax) * nx + (poly[1][1] - ay) * ny) / math.hypot(nx, ny)
    assert across >= 128


def test_corridor_macro_makes_area_ramp_and_doors():
    lt = lay()
    a = lt.areas["t_long"]
    assert a.poly is not None and a.floor == 0
    assert {r.name: (r.axis, r.rise) for r in lt.ramps} == {"t_long_ramp": ("+y", 64)}
    doors = {d.name: d.between for d in lt.doors}
    assert doors["t_long_from"] == ("t_spawn", "t_long")
    assert doors["t_long_to"] == ("a_site", "t_long")
    # the doors sit on the corridor's square ends, not on its bounding box
    lo, hi = door_box(next(d for d in lt.doors if d.name == "t_long_from"), lt.areas, 16)
    assert (lo[0] + hi[0]) // 2 == -1280
    lo, hi = door_box(next(d for d in lt.doors if d.name == "t_long_to"), lt.areas, 16)
    assert (lo[0] + hi[0]) // 2 == -960 and lo[2] == 64  # the higher floor at the top end


def test_poly_fill_tiles_the_bounding_box_outside_the_polygon():
    hexa = lay().areas["hex"]
    x0, y0, x1, y1 = hexa.rect
    tri_area = sum(
        abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2
        for a, b, c in _poly_fill(hexa)
    )
    pts = hexa.poly
    poly_area = (
        sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1], strict=True)) / 2
    )
    assert tri_area + poly_area == (x1 - x0) * (y1 - y0)


def test_all_brushes_convex_and_on_grid():
    g = generate(lay())
    for b in g.mapfile.brushes():
        geo = brush_geometry(b)
        assert not geo.unbounded and all(len(v) >= 3 for v in geo.face_vertices)
        v = geo.vertices
        assert not np.any(np.abs(v - np.round(v / 8) * 8) > 1e-3)


def test_lights_and_spawns_stay_on_the_polygon_floor():
    lt = lay(spawns={"T": {"area": "t_spawn", "count": 10}, "CT": {"area": "hex", "count": 10}})
    g = generate(lt)
    hexa = lt.areas["hex"]
    for e in g.mapfile.entities:
        if e.classname in ("light", "info_player_start"):
            x, y, z = (float(v) for v in e.properties["origin"].split())
            if hexa.rect[0] <= x <= hexa.rect[2] and hexa.rect[1] <= y <= hexa.rect[3]:
                assert hexa.inside(x, y), e.properties


def test_bridge_deck_rails_and_light_under_it():
    g = generate(lay())
    boxes = [brush_geometry(b).vertices for b in g.mapfile.worldspawn.brushes]
    deck = [
        v for v in boxes if v[:, 2].max() == 176 and v[:, 2].min() == 160 and v[:, 0].min() == -64
    ]
    assert deck and np.ptp(deck[0][:, 1]) == 512 and np.ptp(deck[0][:, 0]) == 128
    rails = [v for v in boxes if v[:, 2].min() == 176 and v[:, 2].max() == 216]
    assert len(rails) == 2
    under = [
        e
        for e in g.mapfile.entities
        if e.classname == "light" and e.properties["origin"].endswith(" 144")
    ]
    assert under


def test_overpass_over_an_outdoor_area_is_walled_not_sky():
    g = generate(lay())
    sky = [b for b in g.mapfile.worldspawn.brushes if all(f.texture == "SKY" for f in b.faces)]
    assert sky
    ox0, oy0, ox1, oy1 = 1216, -1008, 1344, -272  # the overpass
    for b in sky:
        v = brush_geometry(b).vertices
        lo, hi = v.min(axis=0), v.max(axis=0)
        # no sky brush inside the overpass's shell (slab under it, walls, roof)
        overlap = lo[0] < ox1 + 16 and hi[0] > ox0 - 16 and lo[1] < oy1 + 16 and hi[1] > oy0 - 16
        assert not (overlap and lo[2] < 176 + 128 + 16), (lo, hi)
    # the yard still has open sky beside the overpass
    assert any(brush_geometry(b).vertices[:, 0].max() <= ox0 - 16 for b in sky)


def test_layout_graph_sees_corridor_and_bridge_routes():
    data = copy.deepcopy(ANGLED)
    lg = layout_graph(data)
    assert lg["site_entrances"]["A"] == 1  # the angled corridor (macro doors count)
    assert lg["site_entrances"]["B"] == 1


@pytest.mark.parametrize(
    "over,msg",
    [
        ({"bridges": [{"name": "x", "area": "street", "axis": "y", "z": 64}]}, "free under"),
        ({"bridges": [{"name": "x", "area": "street", "axis": "q", "z": 176}]}, "axis"),
        (
            {
                "areas": [
                    *ANGLED["areas"][:-1],
                    {"name": "hex", "poly": [[1024, 400], [1536, 624], [1280, 400], [1024, 624]]},
                ]
            },
            "convex",
        ),  # fmt: skip
        (
            {
                "doors": [
                    *ANGLED["doors"][:-1],
                    {"name": "x", "between": ["ct_spawn", "hex"], "width": 128, "offset": 160},
                ]
            },
            "outside the shared wall|share a wall",
        ),  # fmt: skip
        (
            {"cover": [{"name": "c", "area": "hex", "pos": [1040, 288], "size": [32, 32, 32]}]},
            "outside the floor",
        ),
    ],
)
def test_angled_spec_errors(over, msg):
    with pytest.raises(SpecError, match=msg):
        generate(lay(**over))


@pytest.mark.slow
@needs_compilers
def test_angled_map_compiles_and_validates(tmp_path):
    from mapforge.compile.run import compile_map
    from mapforge.validate.run import validate_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    data["validate"]["design"]["off"] = True
    cfg = Config(root=base.root, data=data)
    write_map(
        generate(lay()).mapfile, tmp_path / "maps" / "de_gen_angle" / "src" / "de_gen_angle.map"
    )
    make_dev_wad()
    compile_map(cfg, "de_gen_angle")
    v = validate_map(cfg, "de_gen_angle")
    errors = [f for f in v["findings"] if f["severity"] == "error"]
    assert v["ok"], errors
