"""Walkable graph of a BSP: where a player can go from the spawns.

Nodes are player positions on an x/y grid of `cell` units, in one of two stances: standing
(clip hull 1, 32x32x72) or crouching (hull 3, 32x32x36). Positions are stored as feet height
on an absolute `z_step` grid so the same floor always gets the same z.

Moves to each of the 4 neighbours, tried in order (the first that fits is used):
  1. walk, stepping up at most `max_step` (or level, if there is no head room for the step)
  2. jump onto something up to `jump_height` high (duck-jump)
  3. crouch under something
  4. duck-jump into a crouch-height opening (vents)
Walking off an edge is a (one-way) fall of up to `max_drop`. Ladders (func_ladder) connect
their bottom to their top. A crouching node stands up as soon as the standing hull fits.

Not modelled: horizontal jumps across gaps, swimming up, strafe/bunny tricks.
func_wall/func_wall_toggle brushes are solid; doors and breakables are passable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, HULL_SIZES, Bsp

SOLID_BRUSH_ENTITIES = ("func_wall", "func_wall_toggle")
DIRECTIONS = np.array([(1, 0), (-1, 0), (0, 1), (0, -1)])
STAND, CROUCH = 0, 1
HULL_OF = {STAND: 1, CROUCH: 3}
HALF = {s: np.array(HULL_SIZES[h][1], dtype=np.float64) for s, h in HULL_OF.items()}


@dataclass
class WalkGraph:
    feet: np.ndarray  # (n, 3) feet positions
    stance: np.ndarray  # (n,) STAND / CROUCH
    edges: np.ndarray  # (m, 2) src, dst
    seeds: list[int | None]  # node id per seed position (None = could not be placed)
    cell: float
    z_step: float

    @property
    def positions(self) -> np.ndarray:
        """Hull origins (feet + half height) of all nodes."""
        half_z = np.where(self.stance == STAND, HALF[STAND][2], HALF[CROUCH][2])
        return self.feet + np.column_stack([np.zeros((len(self.feet), 2)), half_z])

    def standing(self) -> np.ndarray:
        """Origins of the standing nodes only (for corridor checks)."""
        return self.feet[self.stance == STAND] + [0.0, 0.0, HALF[STAND][2]]

    def reverse_reachable(self, targets: np.ndarray) -> np.ndarray:
        """Bool mask of nodes from which any target node can be reached."""
        n = len(self.feet)
        mask = np.zeros(n, dtype=bool)
        mask[targets] = True
        if not len(self.edges) or not len(targets):
            return mask
        order = np.argsort(self.edges[:, 1], kind="stable")
        src = self.edges[order, 0]
        starts = np.searchsorted(self.edges[order, 1], np.arange(n + 1))
        queue = deque(int(t) for t in targets)
        while queue:
            v = queue.popleft()
            for u in src[starts[v] : starts[v + 1]]:
                if not mask[u]:
                    mask[u] = True
                    queue.append(int(u))
        return mask


class _Solid:
    """Solidity of a clip hull: world model plus solid brush entities."""

    def __init__(self, bsp: Bsp, stance: int) -> None:
        self.bsp = bsp
        self.hull = HULL_OF[stance]
        half = HALF[stance]
        self.extra: list[tuple[int, np.ndarray, np.ndarray, np.ndarray]] = []
        for ent in bsp.entities:
            model = ent.get("model", "")
            if ent.get("classname") in SOLID_BRUSH_ENTITIES and model.startswith("*"):
                i = int(model[1:])
                origin = np.array([float(v) for v in ent.get("origin", "0 0 0").split()])
                m = bsp.models[i]
                lo = m["mins"].astype(np.float64) + origin - half
                hi = m["maxs"].astype(np.float64) + origin + half
                self.extra.append((i, origin, lo, hi))

    def __call__(self, pts: np.ndarray) -> np.ndarray:
        if not len(pts):
            return np.zeros(0, dtype=bool)
        solid = self.bsp.point_contents(pts, hull=self.hull) == CONTENTS_SOLID
        for i, origin, lo, hi in self.extra:
            near = np.all((pts >= lo) & (pts <= hi), axis=1) & ~solid
            if near.any():
                c = self.bsp.point_contents(pts[near] - origin, hull=self.hull, model=i)
                solid[np.flatnonzero(near)[c == CONTENTS_SOLID]] = True
        return solid


def _settle(solid: _Solid, xy: np.ndarray, ztop: np.ndarray, depth: float, zs: float) -> np.ndarray:
    """Lowest free origin z on the z grid above solid, searching down from ztop; nan if none."""
    out = np.full(len(xy), np.nan)
    if not len(xy):
        return out
    top = np.floor(ztop / zs) * zs
    k = int(np.ceil(depth / zs)) + 1
    grid = top[:, None] - np.arange(k)[None, :] * zs
    s = solid(np.column_stack([np.repeat(xy, k, axis=0), grid.ravel()])).reshape(len(xy), k)
    first = np.argmax(s, axis=1)
    rows = np.flatnonzero(~s[:, 0] & s.any(axis=1) & (first > 0))
    out[rows] = grid[rows, first[rows] - 1]
    return out


def _ladders(bsp: Bsp) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for ent in bsp.entities:
        model = ent.get("model", "")
        if ent.get("classname") == "func_ladder" and model.startswith("*"):
            m = bsp.models[int(model[1:])]
            out.append((m["mins"].astype(np.float64), m["maxs"].astype(np.float64)))
    return out


class _Builder:
    def __init__(self, bsp: Bsp, cell: float, z_step: float) -> None:
        self.solid = {s: _Solid(bsp, s) for s in (STAND, CROUCH)}
        self.cell, self.z_step = cell, z_step
        self.keys: dict[tuple[int, int, int, int], int] = {}
        self.feet: list[tuple[float, float, float]] = []
        self.stance: list[int] = []
        self.edges: list[np.ndarray] = []

    def add(self, xy: np.ndarray, feet_z: np.ndarray, stance: int) -> tuple[np.ndarray, np.ndarray]:
        """Node ids for positions (appending new ones) and a mask of the new ones."""
        ix = np.round(xy[:, 0] / self.cell).astype(np.int64)
        iy = np.round(xy[:, 1] / self.cell).astype(np.int64)
        iz = np.round(feet_z / self.z_step).astype(np.int64)
        ids = np.empty(len(ix), dtype=np.int64)
        new = np.zeros(len(ix), dtype=bool)
        for j, key in enumerate(zip(ix.tolist(), iy.tolist(), iz.tolist(), strict=True)):
            k = (*key, stance)
            nid = self.keys.get(k)
            if nid is None:
                nid = len(self.feet)
                self.keys[k] = nid
                self.feet.append((key[0] * self.cell, key[1] * self.cell, key[2] * self.z_step))
                self.stance.append(stance)
                new[j] = True
            ids[j] = nid
        return ids, new

    def link(self, src: np.ndarray, dst: np.ndarray) -> None:
        keep = src != dst
        if keep.any():
            self.edges.append(np.column_stack([src[keep], dst[keep]]))

    def land(
        self, src: np.ndarray, xy: np.ndarray, ztop: np.ndarray, stance: int, window: float,
        max_drop: float,
    ) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
        """Settle hulls released at (xy, ztop) onto the ground; link and return new node ids."""
        solid = self.solid[stance]
        z = _settle(solid, xy, ztop, window, self.z_step)
        fall = np.isnan(z)
        if fall.any():
            z[fall] = _settle(solid, xy[fall], ztop[fall], max_drop, self.z_step)
        ok = ~np.isnan(z)
        if not ok.any():
            return np.zeros(0, dtype=np.int64), ok
        dst, new = self.add(xy[ok], z[ok] - HALF[stance][2], stance)
        self.link(src[ok], dst)
        return dst[new], ok


def build_walk_graph(
    bsp: Bsp,
    seeds: np.ndarray,
    cell: float = 8,
    z_step: float = 4,
    max_step: float = 18,
    max_drop: float = 1024,
    jump_height: float = 54,
    crouch: bool = True,
    max_nodes: int = 3_000_000,
) -> WalkGraph:
    """Flood-fill from seed positions (e.g. spawn origins, standing hull origins)."""
    b = _Builder(bsp, cell, z_step)
    stand, duck = b.solid[STAND], b.solid[CROUCH]
    hz = {s: HALF[s][2] for s in (STAND, CROUCH)}
    ladders = _ladders(bsp)
    nd = len(DIRECTIONS)

    seeds = np.asarray(seeds, dtype=np.float64).reshape(-1, 3)
    # Snap each seed to the nearest grid point where it can stand; a spawn close to a wall
    # (de_prodigy has one 4 units off) may need the grid point on its other side.
    sxy = np.round(seeds[:, :2] / cell) * cell
    sz = np.full(len(seeds), np.nan)
    corners = [(fx, fy) for fx in (np.floor, np.ceil) for fy in (np.floor, np.ceil)]
    cands = [np.round(seeds[:, :2] / cell) * cell] + [
        np.column_stack([fx(seeds[:, 0] / cell), fy(seeds[:, 1] / cell)]) * cell
        for fx, fy in corners
    ]
    for cand in cands:  # rounding first, then the four surrounding grid corners
        todo = np.isnan(sz)
        if not todo.any():
            break
        z = _settle(stand, cand[todo], seeds[todo, 2] + max_step, max_step + max_drop, z_step)
        hit = np.flatnonzero(todo)[~np.isnan(z)]
        sz[hit] = z[~np.isnan(z)]
        sxy[hit] = cand[hit]
    seed_ids: list[int | None] = [None] * len(seeds)
    placed = np.flatnonzero(~np.isnan(sz))
    frontier = np.zeros(0, dtype=np.int64)
    if len(placed):
        ids, _ = b.add(sxy[placed], sz[placed] - hz[STAND], STAND)
        for j, nid in zip(placed, ids, strict=True):
            seed_ids[int(j)] = int(nid)
        frontier = np.unique(ids)

    while len(frontier) and len(b.feet) < max_nodes:
        st = np.array(b.stance)[frontier]
        feet_all = np.array(b.feet)[frontier]
        new_ids = []
        for s in (STAND, CROUCH):
            f_ids = frontier[st == s]
            if not len(f_ids):
                continue
            feet = feet_all[st == s]
            if s == CROUCH:
                # Stand up where the standing hull fits; such nodes are expanded standing.
                fits = ~stand(feet + [0, 0, hz[STAND]])
                if fits.any():
                    up, new = b.add(feet[fits, :2], feet[fits, 2], STAND)
                    b.link(f_ids[fits], up)
                    new_ids.append(up[new])
                f_ids, feet = f_ids[~fits], feet[~fits]
                if not len(f_ids):
                    continue
            solid, h = b.solid[s], hz[s]
            origin = feet + [0, 0, h]
            src = np.repeat(f_ids, nd)
            nxy = np.repeat(origin[:, :2], nd, axis=0) + np.tile(DIRECTIONS * cell, (len(f_ids), 1))
            oz = np.repeat(origin[:, 2], nd)
            # 1. walk (step up if there is head room for it)
            step_ok = np.repeat(~solid(origin + [0, 0, max_step]), nd)
            ztop = oz + np.where(step_ok, max_step, 0.0)
            free = ~solid(np.column_stack([nxy, ztop]))
            got, _ = b.land(src[free], nxy[free], ztop[free], s, 2 * max_step + 36, max_drop)
            new_ids.append(got)
            blocked = ~free
            if s == STAND and jump_height > 0 and blocked.any():
                # 2. jump onto something (needs head room above the start)
                jump_ok = np.repeat(~stand(origin + [0, 0, jump_height]), nd) & blocked
                jz = oz + jump_height
                fj = jump_ok & ~stand(np.column_stack([nxy, jz]))
                got, _ = b.land(src[fj], nxy[fj], jz[fj], STAND, jump_height + 36, max_drop)
                new_ids.append(got)
                blocked &= ~fj
            if s == STAND and crouch and blocked.any():
                # 3. crouch under something, 4. duck-jump into a crouch-height opening
                cz = feet[:, 2].repeat(nd) + hz[CROUCH]
                for lift in (max_step, jump_height):
                    if not blocked.any():
                        break
                    z = cz + lift
                    fc = blocked & ~duck(np.column_stack([nxy, z]))
                    got, _ = b.land(src[fc], nxy[fc], z[fc], CROUCH, lift + 36, max_drop)
                    new_ids.append(got)
                    blocked &= ~fc
            for lo, hi in ladders:
                at = (
                    np.all((origin[:, :2] >= lo[:2] - 32) & (origin[:, :2] <= hi[:2] + 32), axis=1)
                    & (feet[:, 2] >= lo[2] - 36)
                    & (feet[:, 2] <= hi[2])
                )
                if not at.any():
                    continue
                for d in np.vstack([[0, 0], DIRECTIONS]):
                    lxy = origin[at, :2] + d * cell
                    top = np.full(int(at.sum()), hi[2] + hz[STAND] + 1)
                    got, _ = b.land(f_ids[at], lxy, top, STAND, hz[STAND] + 36, max_drop)
                    new_ids.append(got)
        frontier = np.unique(np.concatenate(new_ids)) if new_ids else np.zeros(0, dtype=np.int64)

    edges = np.unique(np.vstack(b.edges), axis=0) if b.edges else np.zeros((0, 2), dtype=np.int64)
    return WalkGraph(
        feet=np.array(b.feet) if b.feet else np.zeros((0, 3)),
        stance=np.array(b.stance, dtype=np.int64),
        edges=edges,
        seeds=seed_ids,
        cell=cell,
        z_step=z_step,
    )


def bomb_target_boxes(bsp: Bsp) -> list[tuple[np.ndarray, np.ndarray]]:
    """(mins, maxs) per bomb target entity: brush bbox for func_bomb_target, ±64 for info_."""
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


def bomb_sites(bsp: Bsp, merge_gap: float = 128) -> list[list[tuple[np.ndarray, np.ndarray]]]:
    """Group bomb target boxes into sites: boxes closer than merge_gap belong together.

    Maps often build one site from several func_bomb_target brushes (de_prodigy, de_torn).
    """
    boxes = bomb_target_boxes(bsp)
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (alo, ahi), (blo, bhi) = boxes[i], boxes[j]
            gap = np.maximum(0, np.maximum(alo - bhi, blo - ahi))
            if np.all(gap <= merge_gap):
                parent[find(i)] = find(j)
    groups: dict[int, list[tuple[np.ndarray, np.ndarray]]] = {}
    for i, box in enumerate(boxes):
        groups.setdefault(find(i), []).append(box)
    return list(groups.values())


def nodes_touching(graph: WalkGraph, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Node ids whose player box (either stance) overlaps the box (lo, hi)."""
    if not len(graph.feet):
        return np.zeros(0, dtype=np.int64)
    height = np.where(graph.stance == STAND, 72.0, 36.0)
    p = graph.feet
    hit = (
        np.all((p[:, :2] + 16 >= lo[:2]) & (p[:, :2] - 16 <= hi[:2]), axis=1)
        & (p[:, 2] + height >= lo[2])
        & (p[:, 2] <= hi[2])
    )
    return np.flatnonzero(hit)
