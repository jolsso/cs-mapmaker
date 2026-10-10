"""Walkable graph of a BSP: where a standing player can go from the spawns.

Nodes are standing positions (hull 1 origins, 36 above the feet) on an x/y grid of `cell`
units; z is on an absolute `z_step` grid so the same floor always gets the same z. Edges are
moves to a 4-neighbour: step up to `max_step`, walk/step down, or fall (one-way) up to
`max_drop`. Ladders (func_ladder) connect their bottom to their top.

Not modelled (so the graph is conservative): jumping, crouch-only passages, swimming up.
func_wall/func_wall_toggle brushes are solid; doors and breakables are passable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, HULL_SIZES, Bsp

SOLID_BRUSH_ENTITIES = ("func_wall", "func_wall_toggle")
DIRECTIONS = np.array([(1, 0), (-1, 0), (0, 1), (0, -1)])
HALF = np.array(HULL_SIZES[1][1], dtype=np.float64)  # (16, 16, 36)


@dataclass
class WalkGraph:
    positions: np.ndarray  # (n, 3) hull-1 origins
    keys: dict[tuple[int, int, int], int]  # (ix, iy, iz) -> node id
    edges: np.ndarray  # (m, 2) src, dst
    seeds: list[int | None]  # node id per seed position (None = could not be placed)
    cell: float
    z_step: float

    def reverse_reachable(self, targets: np.ndarray) -> np.ndarray:
        """Bool mask of nodes from which any target node can be reached."""
        n = len(self.positions)
        mask = np.zeros(n, dtype=bool)
        if not len(self.edges) or not len(targets):
            mask[targets] = True
            return mask
        order = np.argsort(self.edges[:, 1], kind="stable")
        src = self.edges[order, 0]
        starts = np.searchsorted(self.edges[order, 1], np.arange(n + 1))
        queue = deque(int(t) for t in targets)
        mask[targets] = True
        while queue:
            v = queue.popleft()
            for u in src[starts[v] : starts[v + 1]]:
                if not mask[u]:
                    mask[u] = True
                    queue.append(int(u))
        return mask


class _Solid:
    """Hull-1 solidity: world model plus solid brush entities (with their own clip hulls)."""

    def __init__(self, bsp: Bsp) -> None:
        self.bsp = bsp
        self.extra: list[tuple[int, np.ndarray, np.ndarray, np.ndarray]] = []
        for ent in bsp.entities:
            model = ent.get("model", "")
            if ent.get("classname") in SOLID_BRUSH_ENTITIES and model.startswith("*"):
                i = int(model[1:])
                origin = np.array([float(v) for v in ent.get("origin", "0 0 0").split()])
                m = bsp.models[i]
                lo = m["mins"].astype(np.float64) + origin - HALF
                hi = m["maxs"].astype(np.float64) + origin + HALF
                self.extra.append((i, origin, lo, hi))

    def __call__(self, pts: np.ndarray) -> np.ndarray:
        solid = self.bsp.point_contents(pts, hull=1) == CONTENTS_SOLID
        for i, origin, lo, hi in self.extra:
            near = np.all((pts >= lo) & (pts <= hi), axis=1) & ~solid
            if near.any():
                c = self.bsp.point_contents(pts[near] - origin, hull=1, model=i)
                solid[np.flatnonzero(near)[c == CONTENTS_SOLID]] = True
        return solid


def _settle(solid: _Solid, xy: np.ndarray, ztop: np.ndarray, depth: float, zs: float) -> np.ndarray:
    """Standing z below each (x, y, ztop), searching down `depth` units; nan if none.

    Samples lie on the absolute z grid, so the result is the lowest empty grid z above solid.
    """
    out = np.full(len(xy), np.nan)
    if not len(xy):
        return out
    top = np.floor(ztop / zs) * zs
    k = int(np.ceil(depth / zs)) + 1
    zs_grid = top[:, None] - np.arange(k)[None, :] * zs
    pts = np.column_stack([np.repeat(xy, k, axis=0), zs_grid.ravel()])
    s = solid(pts).reshape(len(xy), k)
    ok = ~s[:, 0]  # the start point itself must be free
    first = np.argmax(s, axis=1)  # first solid sample (0 if none)
    found = ok & s.any(axis=1) & (first > 0)
    rows = np.flatnonzero(found)
    out[rows] = zs_grid[rows, first[rows] - 1]
    return out


def _ladders(bsp: Bsp) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for ent in bsp.entities:
        model = ent.get("model", "")
        if ent.get("classname") == "func_ladder" and model.startswith("*"):
            m = bsp.models[int(model[1:])]
            out.append((m["mins"].astype(np.float64), m["maxs"].astype(np.float64)))
    return out


def build_walk_graph(
    bsp: Bsp,
    seeds: np.ndarray,
    cell: float = 8,
    z_step: float = 4,
    max_step: float = 18,
    max_drop: float = 1024,
    max_nodes: int = 2_000_000,
) -> WalkGraph:
    """Flood-fill from seed positions (e.g. spawn origins) over standing positions."""
    solid = _Solid(bsp)
    ladders = _ladders(bsp)
    keys: dict[tuple[int, int, int], int] = {}
    positions: list[np.ndarray] = []
    edges: list[np.ndarray] = []

    def add(ix: np.ndarray, iy: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Node ids for (ix, iy, z); new nodes are appended. Returns ids and new mask."""
        iz = np.round(z / z_step).astype(np.int64)
        ids = np.empty(len(ix), dtype=np.int64)
        new = np.zeros(len(ix), dtype=bool)
        for j, key in enumerate(zip(ix.tolist(), iy.tolist(), iz.tolist(), strict=True)):
            nid = keys.get(key)
            if nid is None:
                nid = len(keys)
                keys[key] = nid
                positions.append(np.array([key[0] * cell, key[1] * cell, key[2] * z_step]))
                new[j] = True
            ids[j] = nid
        return ids, new

    # Seeds: snap to the grid and settle onto the ground just below.
    seeds = np.asarray(seeds, dtype=np.float64).reshape(-1, 3)
    sx = np.round(seeds[:, 0] / cell).astype(np.int64)
    sy = np.round(seeds[:, 1] / cell).astype(np.int64)
    sxy = np.column_stack([sx * cell, sy * cell]).astype(np.float64)
    sz = _settle(solid, sxy, seeds[:, 2] + max_step, max_step + max_drop, z_step)
    seed_ids: list[int | None] = [None] * len(seeds)
    placed = np.flatnonzero(~np.isnan(sz))
    frontier = np.zeros(0, dtype=np.int64)
    if len(placed):
        ids, new = add(sx[placed], sy[placed], sz[placed])
        for j, nid in zip(placed, ids, strict=True):
            seed_ids[int(j)] = int(nid)
        frontier = np.unique(ids)

    while len(frontier) and len(keys) < max_nodes:
        pos = np.array([positions[i] for i in frontier])
        # Candidate moves: 4 neighbours, plus ladder tops for nodes standing at a ladder.
        src = np.repeat(frontier, len(DIRECTIONS))
        nxy = np.repeat(pos[:, :2], len(DIRECTIONS), axis=0) + np.tile(
            DIRECTIONS * cell, (len(pos), 1)
        )
        base_z = np.repeat(pos[:, 2], len(DIRECTIONS))
        # Step up only if there is head room above the current spot; else stay level.
        up_ok = ~solid(np.column_stack([pos[:, :2], pos[:, 2] + max_step]))
        ztop = base_z + np.where(np.repeat(up_ok, len(DIRECTIONS)), max_step, 0.0)
        for lo, hi in ladders:
            at = (
                np.all((pos[:, :2] >= lo[:2] - 32) & (pos[:, :2] <= hi[:2] + 32), axis=1)
                & (pos[:, 2] >= lo[2] - 72)
                & (pos[:, 2] <= hi[2] + 36)
            )
            if at.any():
                f = frontier[at]
                lp = pos[at]
                for d in np.vstack([[0, 0], DIRECTIONS]):
                    src = np.append(src, f)
                    nxy = np.vstack([nxy, lp[:, :2] + d * cell])
                    ztop = np.append(ztop, np.full(len(f), hi[2] + 37))
                    base_z = np.append(base_z, np.full(len(f), hi[2] + 37))

        # The move happens at ztop: the target column must be free there.
        free = ~solid(np.column_stack([nxy, ztop]))
        src, nxy, ztop = src[free], nxy[free], ztop[free]
        z = _settle(solid, nxy, ztop, 2 * max_step + 36, z_step)
        fall = np.isnan(z)
        if fall.any():
            z[fall] = _settle(solid, nxy[fall], ztop[fall], max_drop, z_step)
        ok = ~np.isnan(z)
        src, nxy, z = src[ok], nxy[ok], z[ok]
        ix = np.round(nxy[:, 0] / cell).astype(np.int64)
        iy = np.round(nxy[:, 1] / cell).astype(np.int64)
        dst, new = add(ix, iy, z)
        keep = dst != src
        edges.append(np.column_stack([src[keep], dst[keep]]))
        frontier = np.unique(dst[new])

    e = np.unique(np.vstack(edges), axis=0) if edges else np.zeros((0, 2), dtype=np.int64)
    return WalkGraph(
        positions=np.array(positions) if positions else np.zeros((0, 3)),
        keys=keys,
        edges=e,
        seeds=seed_ids,
        cell=cell,
        z_step=z_step,
    )


def bomb_target_boxes(bsp: Bsp) -> list[tuple[np.ndarray, np.ndarray]]:
    """(mins, maxs) per bomb target: brush bbox for func_bomb_target, ±64 for info_ ones."""
    boxes = []
    for ent in bsp.entities:
        cls = ent.get("classname")
        model = ent.get("model", "")
        if cls == "func_bomb_target" and model.startswith("*"):
            m = bsp.models[int(model[1:])]
            boxes.append((m["mins"].astype(np.float64), m["maxs"].astype(np.float64)))
        elif cls == "info_bomb_target" and "origin" in ent:
            o = np.array([float(v) for v in ent["origin"].split()])
            boxes.append((o - 64, o + 64))
    return boxes


def nodes_touching(graph: WalkGraph, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Node ids whose standing player box overlaps the box (lo, hi)."""
    p = graph.positions
    if not len(p):
        return np.zeros(0, dtype=np.int64)
    hit = np.all((p + HALF >= lo) & (p - HALF <= hi), axis=1)
    return np.flatnonzero(hit)
