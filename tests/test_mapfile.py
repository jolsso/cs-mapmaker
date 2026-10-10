import numpy as np
import pytest

from mapforge.config import REPO_ROOT
from mapforge.mapfile.geometry import brush_geometry, face_plane
from mapforge.mapfile.parser import MapParseError, parse_map, read_map

TEST_BOX = REPO_ROOT / "maps" / "test_box" / "src" / "test_box.map"


def test_parse_test_box():
    m = read_map(TEST_BOX)
    assert m.worldspawn.properties["mapversion"] == "220"
    assert len(m.worldspawn.brushes) == 6
    assert [e.classname for e in m.entities[1:]] == [
        "light", "info_player_start", "info_player_start",
        "info_player_deathmatch", "info_player_deathmatch",
    ]  # fmt: skip
    face = m.worldspawn.brushes[0].faces[0]
    assert face.texture == "DEV_FLOOR"
    assert face.u_axis == (0, -1, 0, 0)
    assert face.scale == (1, 1)
    assert m.entities[2].origin == (-384, -128, 36)


def test_box_brush_geometry():
    floor = read_map(TEST_BOX).worldspawn.brushes[0]
    geo = brush_geometry(floor)
    assert not geo.unbounded
    assert len(geo.vertices) == 8
    assert geo.vertices.min(axis=0).tolist() == [-528, -528, -16]
    assert geo.vertices.max(axis=0).tolist() == [528, 528, 0]
    assert all(len(v) == 4 for v in geo.face_vertices)


def test_face_plane_points_outward():
    # -X face of a box: normal should be -X
    plane = face_plane(((-64, -64, -16), (-64, -48, -16), (-64, -64, 0)))
    assert np.allclose(plane.normal, [-1, 0, 0]) and plane.dist == 64


def test_collinear_points_give_no_plane():
    assert face_plane(((0, 0, 0), (16, 0, 0), (32, 0, 0))) is None


def test_rejects_quake_format():
    text = '{\n"classname" "worldspawn"\n{\n( 0 0 0 ) ( 0 16 0 ) ( 0 0 16 ) TEX 0 0 0 1 1\n}\n}\n'
    with pytest.raises(MapParseError, match="Valve 220"):
        parse_map(text)


def test_first_entity_must_be_worldspawn():
    with pytest.raises(MapParseError, match="worldspawn"):
        parse_map('{\n"classname" "light"\n}\n')
