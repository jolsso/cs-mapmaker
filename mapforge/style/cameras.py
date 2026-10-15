"""Style-review cameras from a map's layout: every area, every chokepoint and site entrance seen
from both sides, and every landmark seen from inside its zone. Eye height 64 (a standing
player); positions that would sit in a solid are nudged or dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, Bsp
from mapforge.generator.build import door_box
from mapforge.generator.spec import Layout
from mapforge.render.cameras import EYE, CameraSpec, free_distance, line_of_sight

FOV = 70.0
BIG_ROOM = 640  # both sides at least this long: four views instead of two
DOOR_BACK = 256  # door views stand this far from the opening
LANDMARK_RANGE = (256, 512)  # distance from a landmark that a view looks at it from


@dataclass
class StyleCam:
    cam: CameraSpec
    kind: str  # area | door | landmark
    area: str
    zone: str | None
    subject: str  # what the image is about (area, door or landmark name)
    extra: dict[str, Any] = field(default_factory=dict)


def _empty(bsp: Bsp, pts: np.ndarray) -> np.ndarray:
    return bsp.point_contents(np.asarray(pts, dtype=np.float64).reshape(-1, 3)) != CONTENTS_SOLID


def _spot(bsp: Bsp, a, x: float, y: float) -> np.ndarray | None:
    """An eye point at (x, y) or the nearest free one around it inside the area (feet and eye
    both clear of solids), else None."""
    x0, y0, x1, y1 = a.rect
    for r in (0, 48, 96, 160, 256):
        for k in range(8 if r else 1):
            t = 2 * math.pi * k / 8
            px, py = x + r * math.cos(t), y + r * math.sin(t)
            if not (x0 + 24 <= px <= x1 - 24 and y0 + 24 <= py <= y1 - 24) or not a.inside(px, py):
                continue
            eye = np.array([px, py, a.floor + EYE])
            if _empty(bsp, [eye, eye - [0, 0, EYE - 16]]).all():
                return eye
    return None


def _look(eye: np.ndarray, d: np.ndarray, dist: float) -> tuple[float, float, float]:
    t = eye + d * dist
    return (float(t[0]), float(t[1]), float(t[2]))


def area_cameras(layout: Layout, bsp: Bsp) -> list[StyleCam]:
    out = []
    for a in layout.areas.values():
        x0, y0, x1, y1 = a.rect
        cx, cy = a.centroid() if a.poly else ((x0 + x1) / 2, (y0 + y1) / 2)
        eye = _spot(bsp, a, cx, cy)
        if eye is None:
            continue
        w, d = x1 - x0, y1 - y0
        if min(w, d) >= BIG_ROOM:
            dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        else:
            dirs = [(1, 0), (-1, 0)] if w >= d else [(0, 1), (0, -1)]
        vecs = np.array([[dx, dy, 0.0] for dx, dy in dirs])
        free = free_distance(bsp, eye, vecs, max_dist=2048)
        names = {(1, 0): "east", (-1, 0): "west", (0, 1): "north", (0, -1): "south"}
        for (dx, dy), v, f in zip(dirs, vecs, free, strict=True):
            if f < 128:
                continue  # facing a wall at arm's length
            name = f"area_{a.name}_{names[(dx, dy)]}"
            cam = CameraSpec(name, tuple(map(float, eye)), _look(eye, v, min(f, 768)), FOV,
                             f"{a.name} from its middle, looking {names[(dx, dy)]}")  # fmt: skip
            out.append(StyleCam(cam, "area", a.name, a.zone, a.name))
    return out


def door_cameras(layout: Layout, bsp: Bsp, doors: set[str]) -> list[StyleCam]:
    """Both sides of each named door, looking through it from DOOR_BACK units back."""
    out = []
    for door in layout.doors:
        if door.name not in doors:
            continue
        (lo, hi) = door_box(door, layout.areas, layout.wall)
        centre = (np.array(lo) + np.array(hi)) / 2
        through = 0 if (hi[0] - lo[0]) < (hi[1] - lo[1]) else 1  # the thin axis of the opening
        for side, name in zip((-1, 1), door.between, strict=False):
            a = layout.areas[name]
            # stand in the area on this side of the opening
            for sgn in (-1, 1):
                p = centre.copy()
                p[through] += sgn * DOOR_BACK
                if a.inside(p[0], p[1]):
                    break
            else:
                continue
            eye = _spot(bsp, a, p[0], p[1])
            if eye is None:
                continue
            target = np.array([centre[0], centre[1], a.floor + EYE])
            if not line_of_sight(bsp, eye, target):
                continue
            cam = CameraSpec(f"door_{door.name}_from_{a.name}", tuple(map(float, eye)),
                             tuple(map(float, target)), FOV,
                             f"{door.name} seen from {a.name}, {DOOR_BACK} back")  # fmt: skip
            out.append(StyleCam(cam, "door", a.name, a.zone, door.name, {"side": side}))
    return out


def landmark_cameras(layout: Layout, bsp: Bsp, landmarks: list[dict]) -> list[StyleCam]:
    """Each landmark that is a cover item, seen from inside its area at a readable distance."""
    out = []
    covers = {c.name: c for c in layout.cover}
    for lm in landmarks:
        c = covers.get(str(lm.get("element", "")))
        if c is None:
            continue
        a = layout.areas[c.area]
        target = np.array([c.pos[0], c.pos[1], a.floor + c.z + min(c.size[2], 96) / 2])
        best = None
        for dist in LANDMARK_RANGE[::-1]:
            for k in range(16):
                t = 2 * math.pi * k / 16
                eye = _spot(bsp, a, c.pos[0] + dist * math.cos(t), c.pos[1] + dist * math.sin(t))
                if eye is None:
                    continue
                # the target sits inside the landmark: test the sight line up to its surface
                to = target - eye
                front = target - to / np.linalg.norm(to) * (max(c.size[:2]) / 2 + 16)
                if not line_of_sight(bsp, eye, front):
                    continue
                d = float(np.linalg.norm(eye[:2] - target[:2]))
                if d >= LANDMARK_RANGE[0] and (best is None or d > best[0]):
                    best = (d, eye)
            if best:
                break
        if best is None:
            continue
        eye = best[1]
        label = f"landmark {lm.get('name', c.name)} ({c.name}) in {a.name}"
        cam = CameraSpec(f"landmark_{c.name}", tuple(map(float, eye)), tuple(map(float, target)),
                         FOV, label)  # fmt: skip
        out.append(StyleCam(cam, "landmark", a.name, a.zone, str(lm.get("name", c.name))))
    return out


def style_cameras(layout: Layout, raw: dict[str, Any], bsp: Bsp) -> list[StyleCam]:
    """All style cameras: areas, chokepoint + site-entrance doors, landmarks."""
    sites = set(layout.sites.values())
    doors = {c["door"] for c in raw.get("chokes", []) or [] if c.get("door")}
    doors |= {d.name for d in layout.doors if d.walkable and sites & set(d.between)}
    landmarks = list(raw.get("landmarks", []) or [])
    return (
        area_cameras(layout, bsp)
        + door_cameras(layout, bsp, doors)
        + landmark_cameras(layout, bsp, landmarks)
    )
