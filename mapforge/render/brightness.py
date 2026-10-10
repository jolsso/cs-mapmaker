"""Brightness where players stand: the compiled lightmap of the floor under each walk cell.

For each standing node, the floor face is found among the faces of the BSP leaf just above
the feet (an upward-facing face whose plane passes through the feet and whose polygon
contains the point); its lightmap is sampled there. Works under bridges and on every level.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from mapforge.bsp.reader import Bsp
from mapforge.validate.walk import STAND, WalkGraph

# Rec. 601 luma of the lightmap RGB (0-255).
LUMA = np.array([0.299, 0.587, 0.114])


@dataclass
class Brightness:
    feet: np.ndarray  # (n, 3) standing positions that got a value
    luma: np.ndarray  # (n,) lightmap luma 0-255 at the floor
    unknown: int  # standing nodes where no floor face/lightmap was found


def _inside(poly: np.ndarray, pts: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Points (projected on the face plane) inside a convex polygon, either winding."""
    signs = []
    for a, b in zip(poly, np.roll(poly, -1, axis=0), strict=True):
        edge = b - a
        signs.append(np.cross(edge, pts - a) @ normal)
    s = np.array(signs)
    return np.all(s >= -1e-3, axis=0) | np.all(s <= 1e-3, axis=0)


def floor_brightness(bsp: Bsp, graph: WalkGraph) -> Brightness:
    stand = np.flatnonzero(graph.stance == STAND)
    feet = graph.feet[stand]
    leaves = bsp.point_leaf(feet + [0, 0, 1])
    normals = bsp.planes["normal"].astype(np.float64)
    dists = bsp.planes["dist"].astype(np.float64)

    by_leaf: dict[int, list[int]] = defaultdict(list)
    for i, leaf in enumerate(leaves.tolist()):
        by_leaf[leaf].append(i)

    luma = np.full(len(feet), np.nan)
    for leaf, rows in by_leaf.items():
        lf = bsp.leafs[leaf]
        first, count = int(lf["firstmarksurface"]), int(lf["nummarksurfaces"])
        rows = np.array(rows)
        for fi in bsp.marksurfaces[first : first + count]:
            face = bsp.faces[fi]
            n = normals[face["planenum"]] * (-1 if face["side"] else 1)
            d = dists[face["planenum"]] * (-1 if face["side"] else 1)
            if n[2] < 0.7 or face["lightofs"] < 0:
                continue
            todo = rows[np.isnan(luma[rows])]
            if not len(todo):
                break
            p = feet[todo]
            # floor height of the face plane at each (x, y)
            z = (d - p[:, 0] * n[0] - p[:, 1] * n[1]) / n[2]
            near = np.abs(z - p[:, 2]) <= 6
            if not near.any():
                continue
            cand = todo[near]
            pts = np.column_stack([feet[cand, :2], z[near]])
            poly = bsp.face_vertices(int(fi)).astype(np.float64)
            hit = _inside(poly, pts, n)
            if not hit.any():
                continue
            cand, pts = cand[hit], pts[hit]
            lm = bsp.face_lightmap(int(fi))
            if lm is None:
                continue
            vecs = bsp.texinfo[face["texinfo"]]["vecs"].astype(np.float64)
            st = pts @ vecs[:, :3].T + vecs[:, 3]
            verts_st = poly @ vecs[:, :3].T + vecs[:, 3]
            mins = np.floor(verts_st.min(axis=0) / 16)
            ij = np.clip(
                np.round(st / 16 - mins).astype(int), 0, [lm.shape[1] - 1, lm.shape[0] - 1]
            )
            luma[cand] = lm[ij[:, 1], ij[:, 0]] @ LUMA
    ok = ~np.isnan(luma)
    return Brightness(feet=feet[ok], luma=luma[ok], unknown=int((~ok).sum()))


def dark_zones(b: Brightness, threshold: float, cell: float, min_cells: int) -> list[dict]:
    """Clusters (8-connected on the walk grid, same floor) of cells darker than threshold."""
    dark = b.feet[b.luma < threshold]
    keys = {(int(round(x / cell)), int(round(y / cell))): z for x, y, z in dark}
    seen: set[tuple[int, int]] = set()
    zones = []
    for start in keys:
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            k = stack.pop()
            comp.append(k)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nk = (k[0] + dx, k[1] + dy)
                    if nk in keys and nk not in seen and abs(keys[nk] - keys[k]) <= 18:
                        seen.add(nk)
                        stack.append(nk)
        if len(comp) >= min_cells:
            pts = np.array([(kx * cell, ky * cell, keys[(kx, ky)]) for kx, ky in comp])
            zones.append({
                "cells": len(comp),
                "area_units2": int(len(comp) * cell * cell),
                "centre": [round(float(v), 1) for v in pts.mean(axis=0)],
                "bbox": [[round(float(v), 1) for v in pts.min(axis=0)],
                         [round(float(v), 1) for v in pts.max(axis=0)]],
            })  # fmt: skip
    return sorted(zones, key=lambda z: -z["cells"])
