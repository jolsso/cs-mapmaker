"""Camera presets: automatic (spawns, site approaches) plus config/cameras/<map>.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from mapforge.bsp.reader import CONTENTS_SOLID, Bsp
from mapforge.validate.checks import spawn_origins
from mapforge.validate.walk import WalkGraph, bomb_sites, nodes_touching

EYE = 64.0  # eye height above the feet when standing (view_ofs 28 above the hull origin)


@dataclass(frozen=True)
class CameraSpec:
    name: str
    eye: tuple[float, float, float]
    target: tuple[float, float, float]
    fov: float
    purpose: str

    def to_dict(self) -> dict:
        return {"name": self.name, "eye": [round(v, 1) for v in self.eye],
                "target": [round(v, 1) for v in self.target], "fov": self.fov,
                "purpose": self.purpose}  # fmt: skip


def free_distance(bsp: Bsp, eye: np.ndarray, dirs: np.ndarray, max_dist: float = 4096,
                  step: float = 16) -> np.ndarray:  # fmt: skip
    """Distance along each unit direction (n, 3) until hull 0 hits solid."""
    ts = np.arange(step, max_dist + step, step)
    pts = eye[None, None, :] + dirs[:, None, :] * ts[None, :, None]
    solid = (bsp.point_contents(pts.reshape(-1, 3)) == CONTENTS_SOLID).reshape(len(dirs), -1)
    hit = solid.any(axis=1)
    return np.where(hit, ts[np.argmax(solid, axis=1)], max_dist)


def line_of_sight(bsp: Bsp, a: np.ndarray, b: np.ndarray, step: float = 16) -> bool:
    """True if the segment a-b crosses no solid (hull 0)."""
    n = max(2, int(np.linalg.norm(b - a) / step))
    pts = a[None, :] + (b - a)[None, :] * np.linspace(0, 1, n)[:, None]
    return not np.any(bsp.point_contents(pts) == CONTENTS_SOLID)


def best_view(bsp: Bsp, eye: np.ndarray, prefer: np.ndarray, n: int = 24) -> np.ndarray:
    """Target point in the horizontal direction with the longest free sight line from eye;
    near-ties go to the direction closest to `prefer`."""
    yaw = np.linspace(0, 2 * np.pi, n, endpoint=False)
    dirs = np.column_stack([np.cos(yaw), np.sin(yaw), np.zeros(n)])
    dist = free_distance(bsp, eye, dirs)
    to = prefer[:2] - eye[:2]
    to = to / (np.linalg.norm(to) or 1)
    score = dist * (1 + 0.25 * (dirs[:, :2] @ to))
    best = int(np.argmax(score))
    return eye + dirs[best] * min(float(dist[best]), 1024)


def _t(v: np.ndarray) -> tuple[float, float, float]:
    return (float(v[0]), float(v[1]), float(v[2]))


def auto_cameras(
    bsp: Bsp, graph: WalkGraph, approach: float = 600, fov: float = 65
) -> list[CameraSpec]:
    """Spawn views towards the map centre, and the T approach onto each bomb site."""
    origins, teams = spawn_origins(bsp.entities)
    feet = graph.feet
    centre = np.r_[np.median(feet[:, :2], axis=0), np.median(feet[:, 2]) + EYE]
    cams = []
    for team in ("T", "CT"):
        rows = [i for i, t in enumerate(teams) if t == team]
        if not rows:
            continue
        seed_feet = [feet[graph.seeds[i]] for i in rows if graph.seeds[i] is not None]
        if not seed_feet:
            continue
        eye = np.mean(seed_feet, axis=0) + [0, 0, EYE]
        target = best_view(bsp, eye, centre)
        purpose = (f"{team} spawn at eye height, looking along the longest open sight line "
                   "(towards the map centre on near-ties)")  # fmt: skip
        cams.append(CameraSpec(f"spawn_{team.lower()}", _t(eye), _t(target), fov, purpose))

    t_seeds = [
        graph.seeds[i] for i, t in enumerate(teams) if t == "T" and graph.seeds[i] is not None
    ]
    for n, boxes in enumerate(bomb_sites(bsp), start=1):
        lo = np.min([b[0] for b in boxes], axis=0)
        hi = np.max([b[1] for b in boxes], axis=0)
        site_centre = (lo + hi) / 2
        targets = np.unique(np.concatenate([nodes_touching(graph, a, b) for a, b in boxes]))
        if not t_seeds or not len(targets):
            continue
        path = graph.shortest_path(t_seeds[0], targets)
        if not path:
            continue
        # Walk back from the site entry; take the farthest point within `approach` units that
        # still sees the site centre (hull-0 line of sight), so the camera never faces a wall.
        entry = feet[path[-1]]
        target = np.r_[site_centre[:2], entry[2] + 32]
        pick = path[0]
        best = -1.0
        for node in reversed(path):
            d = float(np.linalg.norm(feet[node, :2] - entry[:2]))
            if d > approach * 1.5:
                break
            eye = feet[node] + [0, 0, EYE]
            if d >= approach / 2 and d > best and line_of_sight(bsp, eye, target):
                best, pick = d, node
            if d >= approach and best >= 0:
                break
        eye = feet[pick] + [0, 0, EYE]
        cams.append(CameraSpec(f"site{n}_approach", _t(eye), _t(target), fov,
                               f"Attacker's view onto bomb site {n} from ~{approach:g} units "
                               "along the shortest walk from T spawn"))  # fmt: skip
    return cams


def configured_cameras(path: Path) -> list[CameraSpec]:
    """Cameras from config/cameras/<map>.yaml: [{name, eye, target, fov?, purpose?}]."""
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        CameraSpec(
            name=c["name"],
            eye=tuple(float(v) for v in c["eye"]),
            target=tuple(float(v) for v in c["target"]),
            fov=float(c.get("fov", 65)),
            purpose=c.get("purpose", "configured camera"),
        )
        for c in data.get("cameras", [])
    ]
