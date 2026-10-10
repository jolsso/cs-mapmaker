"""Brush geometry from face planes: vertices, per-face polygons, validity."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from mapforge.mapfile.parser import Brush

EPS = 1e-3
# Planes far outside any GoldSrc map; a vertex on them means the brush is open (unbounded).
BOUND = 1 << 17


@dataclass(frozen=True)
class Plane:
    normal: np.ndarray  # unit vector, pointing out of the brush
    dist: float


@dataclass
class BrushGeometry:
    planes: list[Plane | None]  # None = degenerate (collinear) face points
    vertices: np.ndarray  # (n, 3)
    face_vertices: list[np.ndarray]  # per face: (k, 3) vertices lying on that plane
    unbounded: bool


def face_plane(points: tuple) -> Plane | None:
    """Quake convention: normal = (p0 - p1) x (p2 - p1), pointing out of the brush."""
    p0, p1, p2 = (np.asarray(p, dtype=np.float64) for p in points)
    n = np.cross(p0 - p1, p2 - p1)
    length = np.linalg.norm(n)
    if length < 1e-9:
        return None
    n = n / length
    return Plane(normal=n, dist=float(n @ p0))


def brush_geometry(brush: Brush) -> BrushGeometry:
    planes = [face_plane(f.points) for f in brush.faces]
    valid = [p for p in planes if p is not None]
    bounds = [
        Plane(np.array(v, dtype=np.float64), BOUND) for v in np.vstack([np.eye(3), -np.eye(3)])
    ]
    all_planes = valid + bounds

    normals = np.array([p.normal for p in all_planes])
    dists = np.array([p.dist for p in all_planes])
    verts = []
    for i, j, k in combinations(range(len(all_planes)), 3):
        a = normals[[i, j, k]]
        if abs(np.linalg.det(a)) < 1e-9:
            continue
        v = np.linalg.solve(a, dists[[i, j, k]])
        if np.all(normals @ v - dists <= EPS):
            verts.append(v)
    vertices = np.unique(np.round(np.array(verts), 4), axis=0) if verts else np.zeros((0, 3))

    unbounded = bool(len(vertices)) and bool(np.any(np.abs(vertices) >= BOUND - EPS))
    face_vertices = []
    for p in planes:
        if p is None or not len(vertices):
            face_vertices.append(np.zeros((0, 3)))
            continue
        on = np.abs(vertices @ p.normal - p.dist) <= EPS
        face_vertices.append(vertices[on])
    return BrushGeometry(
        planes=planes, vertices=vertices, face_vertices=face_vertices, unbounded=unbounded
    )
