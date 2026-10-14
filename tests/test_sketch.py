"""Sketch strokes -> angled corridors (mapforge.sketch)."""

import copy
import math

import numpy as np
import pytest

from mapforge.generator.build import generate
from mapforge.generator.spec import SpecError, parse_layout
from mapforge.sketch import bends, corridors_from_stroke, simplify


def _wobbly(points, n=40, noise=20, seed=0):
    """A freehand line through `points`: n samples per stretch with hand jitter."""
    rng = np.random.default_rng(seed)
    out = []
    for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(
                [
                    ax + (bx - ax) * t + rng.normal(0, noise),
                    ay + (by - ay) * t + rng.normal(0, noise),
                ]
            )
    out.append(list(points[-1]))
    return out


def test_simplify_finds_the_bends_of_a_freehand_line():
    line = _wobbly([(0, 0), (300, 1200), (1500, 1700)])
    assert len(simplify(line, 96)) == 3
    vs = bends(line, 16, 128, 96)
    assert len(vs) == 3 and all(v % 16 == 0 for p in vs for v in p)
    assert math.dist(vs[1], (300, 1200)) < 80


BASE = {
    "name": "de_sketch",
    "areas": [
        {"name": "t_spawn", "rect": [-2048, -2048, -1536, -1536]},
        {"name": "ct_spawn", "rect": [2048, 2048, 2560, 2560]},
    ],
    "doors": [],
    "spawns": {"T": {"area": "t_spawn", "count": 10}, "CT": {"area": "ct_spawn", "count": 10}},
}


def test_stroke_becomes_corridors_and_knees_that_generate():
    pieces = corridors_from_stroke(_wobbly([(0, 0), (300, 1200), (1500, 1700)]), "s1")
    assert len(pieces["corridors"]) == 2 and len(pieces["areas"]) == 1
    data = copy.deepcopy(BASE)
    data["areas"] += pieces["areas"]
    data["corridors"] = pieces["corridors"]
    data["doors"] += pieces["doors"]
    lay = parse_layout(data)
    assert lay.areas["s1_1"].poly is not None  # angled: 1:4 and 12:5
    generate(lay)  # every door shares a wall with its knee


def test_short_stroke_and_45_degree_bends_are_refused():
    with pytest.raises(SpecError, match="too short"):
        corridors_from_stroke([[0, 0], [100, 50]], "s2")
    with pytest.raises(SpecError, match="45"):
        corridors_from_stroke([[0, 0], [600, 640], [1240, 1240]], "s3", tolerance=8)
