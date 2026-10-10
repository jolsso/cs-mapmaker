import numpy as np
import pytest

from mapforge.config import REPO_ROOT
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.parser import parse_map, read_map
from mapforge.mapfile.writer import box_brush, entity, format_map

TEST_BOX = REPO_ROOT / "maps" / "test_box" / "src" / "test_box.map"


def _same(a, b):
    assert len(a.entities) == len(b.entities)
    for ea, eb in zip(a.entities, b.entities, strict=True):
        assert ea.properties == eb.properties
        assert len(ea.brushes) == len(eb.brushes)
        for ba, bb in zip(ea.brushes, eb.brushes, strict=True):
            for fa, fb in zip(ba.faces, bb.faces, strict=True):
                assert (fa.points, fa.texture, fa.u_axis, fa.v_axis, fa.scale) == (
                    fb.points, fb.texture, fb.u_axis, fb.v_axis, fb.scale)  # fmt: skip


def test_round_trip_test_box():
    original = read_map(TEST_BOX)
    again = parse_map(format_map(original))
    _same(original, again)


def test_read_modify_write():
    m = read_map(TEST_BOX)
    m.entities[1].properties["_light"] = "255 0 0 100"
    m.worldspawn.brushes.append(box_brush((-64, -64, 0), (64, 64, 32), "DEV_WALL"))
    again = parse_map(format_map(m, header="modified"))
    assert again.entities[1].properties["_light"] == "255 0 0 100"
    assert len(again.worldspawn.brushes) == 7


def test_box_brush_is_closed_and_on_grid():
    b = box_brush((0, 16, -32), (128, 64, 96), {"top": "F", "bottom": "C", "side": "W"})
    geo = brush_geometry(b)
    assert not geo.unbounded and len(geo.vertices) == 8
    assert geo.vertices.min(axis=0).tolist() == [0, 16, -32]
    assert geo.vertices.max(axis=0).tolist() == [128, 64, 96]
    tex = {f.texture for f in b.faces}
    assert tex == {"F", "C", "W"}
    top = next(f for f in b.faces if f.texture == "F")
    n = np.cross(
        np.subtract(top.points[0], top.points[1]), np.subtract(top.points[2], top.points[1])
    )
    assert n[2] > 0  # the top face points up


def test_empty_box_and_quotes_are_rejected():
    with pytest.raises(ValueError):
        box_brush((0, 0, 0), (0, 16, 16), "W")
    m = parse_map(format_map(read_map(TEST_BOX)))
    m.entities.append(entity({"classname": 'bad"name'}))
    with pytest.raises(ValueError):
        format_map(m)
