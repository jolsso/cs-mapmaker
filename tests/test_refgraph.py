"""BSP -> topology segmentation (mapforge.refgraph) on a synthetic walk graph."""

import numpy as np

from mapforge import refgraph as rg


def _floor(cells: set[tuple[int, int]], cell: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Walk nodes on a flat floor (8-unit grid) with two-way edges to the 4 neighbours."""
    idx = {c: i for i, c in enumerate(sorted(cells))}
    feet = np.array([[x * cell, y * cell, 0.0] for x, y in sorted(cells)])
    edges = [
        (i, idx[(x + dx, y + dy)])
        for (x, y), i in idx.items()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        if (x + dx, y + dy) in idx
    ]
    return feet, np.array(edges, dtype=np.int64)


def _rooms(feet: np.ndarray, edges: np.ndarray) -> np.ndarray:
    pid = rg._patches(feet, edges)
    n = int(pid.max()) + 1
    ce = pid[edges]
    directed = {(int(a), int(b)) for a, b in ce if a != b}
    nb: list[set[int]] = [set() for _ in range(n)]
    for a, b in directed:
        if (b, a) in directed:
            nb[a].add(b)
    d = np.zeros(n, dtype=np.int64)
    np.maximum.at(d, pid, rg._clearance(feet, edges, 8.0))
    return rg._merge_small(rg._watershed(nb, d), nb)[pid]


def _box(x0: int, y0: int, x1: int, y1: int) -> set[tuple[int, int]]:
    return {(x, y) for x in range(x0, x1) for y in range(y0, y1)}


def test_two_rooms_and_a_door_are_two_nodes():
    # two 384x384 rooms, joined by a 64-wide, 64-long doorway
    west, east = _box(0, 0, 48, 48), _box(56, 0, 104, 48)
    door = _box(48, 20, 56, 28)
    feet, edges = _floor(west | east | door)
    room = _rooms(feet, edges)
    assert len(set(room.tolist())) == 2
    xs = feet[:, 0]
    assert len(set(room[xs < 200].tolist())) == 1 and len(set(room[xs > 600].tolist())) == 1
    assert room[np.argmin(xs)] != room[np.argmax(xs)]


def test_a_crate_does_not_split_a_room():
    # one 512x512 room with a 64x64 crate in the middle: still one room
    floor = _box(0, 0, 64, 64) - _box(28, 28, 36, 36)
    feet, edges = _floor(floor)
    assert len(set(_rooms(feet, edges).tolist())) == 1


def test_clearance_counts_units_to_the_edge():
    feet, edges = _floor(_box(0, 0, 9, 9))  # 9x9 nodes: the centre is 4 cells from the edge
    d = rg._clearance(feet, edges, 8.0)
    centre = np.flatnonzero((feet[:, 0] == 32) & (feet[:, 1] == 32))[0]
    assert d[centre] == 32 and d.min() == 0


def test_runs_cover_the_cells():
    cells = np.array([[0, 0], [1, 0], [3, 0], [0, 1]])
    runs = rg._runs(cells)
    area = sum((r[1][0] - r[0][0]) * (r[2][1] - r[1][1]) for r in runs)
    assert len(runs) == 3 and area == 4 * rg.CELL * rg.CELL


def test_a_spawn_on_a_site_gets_its_own_room():
    # one open room; the CT spawn at the west end, the bomb target at the east end
    feet, edges = _floor(_box(0, 0, 96, 32))
    pid = rg._patches(feet, edges)
    n = int(pid.max()) + 1
    nb = [set() for _ in range(n)]
    for a, b in pid[edges]:
        if a != b:
            nb[a].add(int(b))
    room = np.zeros(n, dtype=np.int64)
    west, east = pid[np.argmin(feet[:, 0])], pid[np.argmax(feet[:, 0])]
    split = rg._split_shared(room, nb, {"CT": np.array([west]), "A": np.array([east])})
    assert split[west] != split[east] and len(set(split.tolist())) == 2
