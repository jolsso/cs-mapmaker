"""Route timings: how long each team needs from spawn to each bomb site.

Shortest walk-graph path from every spawn to the site, string-pulled (line of sight with a
standing hull) to a realistic running line, converted to seconds at knife/C4 speed (250 u/s,
ReGameDLL KNIFE_MAX_SPEED / C4_MAX_SPEED). The median spawn per team is reported, since teams
move together; min/max show the spread inside a spawn.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, Bsp
from mapforge.validate.walk import WalkGraph, bomb_sites, nodes_touching, site_labels

RUN_SPEED = 250.0  # units/s with knife or C4 (ReGameDLL weapons.h)


def _clear(bsp: Bsp, a: np.ndarray, b: np.ndarray, max_rise: float = 18) -> bool:
    """A standing player can run straight from a to b (hull 1 free along the segment, floor
    under it not dropping or rising sharply is checked by the caller's path)."""
    if abs(a[2] - b[2]) > max_rise:
        return False
    n = max(2, int(np.linalg.norm(b - a) / 16))
    pts = a[None, :] + (b - a)[None, :] * np.linspace(0, 1, n)[:, None]
    return not np.any(bsp.point_contents(pts + [0, 0, 36], hull=1) == CONTENTS_SOLID)


def path_length(bsp: Bsp, pts: np.ndarray) -> float:
    """Length of a grid path after string pulling (skip nodes while a straight run is clear)."""
    if len(pts) < 2:
        return 0.0
    total, i = 0.0, 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        # largest j reachable in a straight line (search back from the far end in big steps)
        step = max(1, (j - i) // 8)
        while j > i + 1 and not _clear(bsp, pts[i], pts[j]):
            j = max(i + 1, j - step)
            step = max(1, step // 2) if step > 1 else 1
        total += float(np.linalg.norm(pts[j] - pts[i]))
        i = j
    return total


def route_timings(bsp: Bsp, graph: WalkGraph, teams: list[str]) -> list[dict[str, Any]]:
    out = []
    labels = site_labels(bsp)
    for n, boxes in enumerate(bomb_sites(bsp), start=1):
        targets = np.unique(np.concatenate([nodes_touching(graph, lo, hi) for lo, hi in boxes]))
        if not len(targets):
            continue
        row: dict[str, Any] = {"site": labels[n - 1]}
        for team in ("T", "CT"):
            secs = []
            seeds = [
                s for s, t in zip(graph.seeds, teams, strict=True) if t == team and s is not None
            ]
            for s in seeds[:: max(1, len(seeds) // 6)]:  # sample a few spawns per team
                path = graph.shortest_path(s, targets)
                if path:
                    secs.append(path_length(bsp, graph.feet[path]) / RUN_SPEED)
            if secs:
                row[team] = {
                    "median_s": round(float(np.median(secs)), 1),
                    "min_s": round(min(secs), 1),
                    "max_s": round(max(secs), 1),
                }
        if "T" in row and "CT" in row:
            row["ct_lead_s"] = round(row["T"]["median_s"] - row["CT"]["median_s"], 1)
        out.append(row)
    return out
