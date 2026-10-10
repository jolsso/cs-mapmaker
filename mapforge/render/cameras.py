"""Camera presets: automatic (spawns, site approaches) plus config/cameras/<map>.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from mapforge.bsp.reader import Bsp
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
        purpose = f"{team} spawn at eye height, looking towards the map centre"
        cams.append(CameraSpec(f"spawn_{team.lower()}", _t(eye), _t(centre), fov, purpose))

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
        # Walk back from the site entry until we are `approach` units (straight line) away.
        entry = feet[path[-1]]
        pick = path[0]
        for node in reversed(path):
            if np.linalg.norm(feet[node, :2] - entry[:2]) >= approach:
                pick = node
                break
        eye = feet[pick] + [0, 0, EYE]
        target = np.r_[site_centre[:2], entry[2] + 32]
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
