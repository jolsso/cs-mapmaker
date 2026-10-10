"""Validation checks. Each returns a list of Findings; errors fail the iteration (FITNESS.md)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, Bsp
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.parser import MapFile

ERROR = "error"
WARNING = "warning"

T_SPAWN = "info_player_deathmatch"
CT_SPAWN = "info_player_start"
BOMB_TARGETS = ("func_bomb_target", "info_bomb_target")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    source: str  # compile | map | bsp
    location: list[float] | None = None
    line: int | None = None  # line in the .map source
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _xyz(v: Any) -> list[float]:
    return [round(float(c), 3) + 0.0 for c in v]  # + 0.0 turns -0.0 into 0.0


# --- compile -------------------------------------------------------------------------------


def check_compile(report: dict[str, Any] | None) -> list[Finding]:
    if report is None:
        return [Finding("compile_missing", ERROR, "No compile.json; compile first", "compile")]
    out = []
    leak = report.get("leak")
    if leak:
        ent = leak.get("entity") or {}
        out.append(
            Finding(
                "leak",
                ERROR,
                f"Map leaks in hull {leak['hull']}: the playable space is open to the void. "
                f"The leak line starts at {ent.get('classname', '?')} and leaves the map near "
                f"{leak.get('first_point')}; seal the gap there.",
                "compile",
                location=leak.get("first_point"),
                details={
                    "entity": ent,
                    "line": leak.get("line"),
                    "pointfile": leak.get("pointfile"),
                },
            )
        )
    if not report.get("ok") and not leak:
        errors = report.get("errors") or []
        out.append(
            Finding(
                "compile_failed",
                ERROR,
                (report.get("failure") or "compile failed") + (f": {errors[0]}" if errors else ""),
                "compile",
                details={"step": report.get("failed_step"), "errors": report.get("errors")},
            )
        )
    for w in report.get("warnings", []):
        out.append(Finding("compile_warning", WARNING, w, "compile"))
    return out


# --- .map geometry --------------------------------------------------------------------------


def check_geometry(mapfile: MapFile, grid: int, bounds: float) -> list[Finding]:
    out = []
    for brush in mapfile.brushes():
        where = f"entity {brush.entity_index} brush {brush.brush_index}"
        geo = brush_geometry(brush)
        for face, plane in zip(brush.faces, geo.planes, strict=True):
            if plane is None:
                out.append(
                    Finding(
                        "degenerate_face",
                        ERROR,
                        f"{where}: face points are collinear, so they define no plane",
                        "map",
                        line=face.line,
                    )
                )
        if geo.unbounded or len(geo.vertices) < 4:
            out.append(
                Finding(
                    "invalid_brush",
                    ERROR,
                    f"{where}: face planes do not enclose a closed convex solid "
                    f"({'open/unbounded' if geo.unbounded else 'empty'}); "
                    "check for a flipped face (points in the wrong winding order)",
                    "map",
                    line=brush.line,
                )
            )
            continue
        for face, plane, verts in zip(brush.faces, geo.planes, geo.face_vertices, strict=True):
            if plane is not None and len(verts) < 3:
                out.append(
                    Finding(
                        "redundant_face",
                        ERROR,
                        f"{where}: face plane does not touch the brush (redundant or "
                        "non-convex brush definition)",
                        "map",
                        line=face.line,
                    )
                )
        off = geo.vertices[
            np.any(np.abs(geo.vertices - np.round(geo.vertices / grid) * grid) > 1e-3, axis=1)
        ]
        if len(off):
            out.append(
                Finding(
                    "off_grid",
                    ERROR,
                    f"{where}: {len(off)} vertices off the {grid}-unit grid",
                    "map",
                    location=_xyz(off[0]),
                    line=brush.line,
                    details={"vertices": [_xyz(v) for v in off[:8]]},
                )
            )
        outside = geo.vertices[np.any(np.abs(geo.vertices) > bounds, axis=1)]
        if len(outside):
            out.append(
                Finding(
                    "out_of_bounds",
                    ERROR,
                    f"{where}: vertices beyond ±{bounds:g} units",
                    "map",
                    location=_xyz(outside[0]),
                    line=brush.line,
                )
            )
    return out


# --- limits ---------------------------------------------------------------------------------


def check_limits(
    bsp: Bsp,
    engine_limits: dict[str, int],
    compile_report: dict[str, Any] | None,
    table_rows: list[str],
    error_pct: float,
    warn_pct: float,
) -> tuple[list[Finding], list[dict[str, Any]]]:
    usage = []
    counts = bsp.counts()
    for name, limit in engine_limits.items():
        used = counts[name]
        usage.append(
            {"name": name, "used": used, "max": limit, "pct": round(100 * used / limit, 2)}
        )
    for row in (compile_report or {}).get("limits", []):
        if row["name"] in table_rows:
            used = row["count"] if row["count"] is not None else row["memory"]
            usage.append(
                {"name": row["name"], "used": used, "max": row["max"] or row["max_memory"],
                 "pct": row["fullness_pct"], "source": "compiler"}
            )  # fmt: skip
    out = []
    for u in usage:
        if u["pct"] > error_pct:
            sev = ERROR
        elif u["pct"] > warn_pct:
            sev = WARNING
        else:
            continue
        out.append(
            Finding(
                "limit",
                sev,
                f"{u['name']}: {u['used']}/{u['max']} ({u['pct']:.1f} %)",
                "bsp",
                details=u,
            )
        )
    return out, usage


# --- entities -------------------------------------------------------------------------------


def map_type(map_name: str) -> str:
    prefix = map_name.split("_", 1)[0]
    return prefix if "_" in map_name else ""


def _origin(ent: dict[str, str]) -> np.ndarray | None:
    raw = ent.get("origin")
    return np.array([float(v) for v in raw.split()]) if raw else None


def check_entities(
    entities: list[dict[str, str]], rules: dict[str, Any], mtype: str, bsp: Bsp | None
) -> tuple[list[Finding], dict[str, Any]]:
    out = []
    by_class: dict[str, list[dict[str, str]]] = defaultdict(list)
    for e in entities:
        by_class[e.get("classname", "")].append(e)

    spawns = {"T": by_class[T_SPAWN], "CT": by_class[CT_SPAWN]}
    need = int(rules.get("spawns_per_team", 0))
    for team, ents in spawns.items():
        if len(ents) < need:
            out.append(
                Finding(
                    "spawn_count",
                    ERROR,
                    f"{team} has {len(ents)} spawns, needs at least {need} "
                    f"({T_SPAWN if team == 'T' else CT_SPAWN})",
                    "bsp" if bsp else "map",
                )
            )

    bombs = [e for c in BOMB_TARGETS for e in by_class[c]]
    need_bombs = (
        int((rules.get("bomb_targets") or {}).get(mtype, 0))
        if isinstance(rules.get("bomb_targets"), dict)
        else int(rules.get("bomb_targets") or 0)
    )
    if need_bombs and len(bombs) != need_bombs:
        out.append(
            Finding(
                "bomb_targets",
                ERROR,
                f"{len(bombs)} bomb targets, {mtype}_ maps need exactly {need_bombs}",
                "bsp" if bsp else "map",
            )
        )

    # func_buyzone "team": 1 = T, 2 = CT, 0/absent = both.
    buy = {"T": 0, "CT": 0}
    for e in by_class["func_buyzone"]:
        team = e.get("team", "0")
        if team in ("0", "1"):
            buy["T"] += 1
        if team in ("0", "2"):
            buy["CT"] += 1
    # A map with no func_buyzone at all is fine: the game creates buy zones around the
    # spawns (de_nuke, de_cold do this). Only a map that defines them for one team but not
    # the other is broken.
    implicit_buy = not by_class["func_buyzone"]
    need_buy = int(rules.get("buyzones_per_team", 0))
    for team, n in buy.items():
        if not implicit_buy and n < need_buy:
            out.append(
                Finding(
                    "buyzone_count",
                    ERROR,
                    f"{team} has {n} func_buyzone, needs at least {need_buy} (the other team "
                    "has explicit buy zones, so the game will not create implicit ones)",
                    "bsp" if bsp else "map",
                )
            )

    if bsp is not None:
        for team, ents in spawns.items():
            origins = [o for o in (_origin(e) for e in ents) if o is not None]
            if not origins:
                continue
            contents = bsp.point_contents(np.array(origins), hull=1)
            for o, c in zip(origins, contents, strict=True):
                if c == CONTENTS_SOLID:
                    out.append(
                        Finding(
                            "spawn_stuck",
                            ERROR,
                            f"{team} spawn at {_xyz(o)}: a standing player does not fit there "
                            "(inside or touching solid geometry)",
                            "bsp",
                            location=_xyz(o),
                        )
                    )

    stats = {
        "spawns": {t: len(e) for t, e in spawns.items()},
        "bomb_targets": len(bombs),
        "buyzones": {**buy, "implicit": implicit_buy},
        "entities": len(entities),
    }
    return out, stats


# --- corridors (clip hull 1 = standing player) ------------------------------------------------


def standing_spots(bsp: Bsp, cell: float, z_step: float) -> np.ndarray:
    """(n, 3) origins where a standing player fits with solid ground just below."""
    mins = bsp.models[0]["mins"].astype(np.float64)
    maxs = bsp.models[0]["maxs"].astype(np.float64)
    xs = np.arange(np.floor(mins[0] / cell) * cell, maxs[0] + cell, cell)
    ys = np.arange(np.floor(mins[1] / cell) * cell, maxs[1] + cell, cell)
    zs = np.arange(mins[2], maxs[2] + z_step, z_step)
    spots = []
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    cols = np.column_stack([gx.ravel(), gy.ravel()])
    chunk = max(1, 2_000_000 // len(zs))
    for i in range(0, len(cols), chunk):
        c = cols[i : i + chunk]
        pts = np.column_stack([np.repeat(c, len(zs), axis=0), np.tile(zs, len(c))])
        solid = (bsp.point_contents(pts, hull=1) == CONTENTS_SOLID).reshape(len(c), len(zs))
        stand = ~solid[:, 1:] & solid[:, :-1]
        ci, zi = np.nonzero(stand)
        spots.append(np.column_stack([c[ci], zs[zi + 1]]))
    return np.vstack(spots) if spots else np.zeros((0, 3))


def _runs(keys: dict[tuple[int, int], list[float]], axis: int, max_step: float) -> dict:
    """Length (in cells) of the contiguous walkable run through each spot along one axis."""
    run_of: dict[tuple[int, int, float], int] = {}
    members: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    next_id = 0
    for ix, iy in sorted(keys, key=lambda k: (k[1 - axis], k[axis])):
        prev = (ix - 1, iy) if axis == 0 else (ix, iy - 1)
        for z in keys[(ix, iy)]:
            rid = None
            for pz in keys.get(prev, []):
                if abs(pz - z) <= max_step and (prev[0], prev[1], pz) in run_of:
                    rid = run_of[(prev[0], prev[1], pz)]
                    break
            if rid is None:
                rid = next_id
                next_id += 1
            run_of[(ix, iy, z)] = rid
            members[rid].append((ix, iy, z))
    return {k: len(members[r]) for k, r in run_of.items()}


def check_corridors(bsp: Bsp, cfg: dict[str, Any]) -> tuple[list[Finding], dict[str, Any]]:
    cell, z_step = float(cfg["cell"]), float(cfg["z_step"])
    min_w, min_h, max_step = (
        float(cfg["min_width"]),
        float(cfg["min_height"]),
        float(cfg["max_step"]),
    )
    spots = standing_spots(bsp, cell, z_step)
    if not len(spots):
        return [Finding("no_walkable_space", ERROR, "No place where a player can stand", "bsp")], {}

    keys: dict[tuple[int, int], list[float]] = defaultdict(list)
    for x, y, z in spots:
        keys[(int(round(x / cell)), int(round(y / cell)))].append(float(z))
    run_x = _runs(keys, 0, max_step)
    run_y = _runs(keys, 1, max_step)
    # Free span of hull centres is between (n-1)*cell and n*cell; the passage is that plus the
    # 32-unit hull. Use the generous end so only clearly narrow passages are flagged.
    width = {k: min(run_x[k], run_y[k]) * cell + 32 for k in run_x}

    head = spots + np.array([0.0, 0.0, min_h - 72])
    low = bsp.point_contents(head, hull=1) == CONTENTS_SOLID
    low_keys = {
        (int(round(x / cell)), int(round(y / cell)), float(z))
        for (x, y, z), is_low in zip(spots, low, strict=True)
        if is_low
    }
    narrow_keys = {k for k, w in width.items() if w < min_w}

    findings = []
    for rule, cells, text in (
        ("narrow_passage", narrow_keys, f"narrower than {min_w:g} units"),
        ("low_ceiling", low_keys, f"lower than {min_h:g} units"),
    ):
        for cluster in _clusters(cells, max_step)[:20]:
            pts = np.array([(ix * cell, iy * cell, z - 36) for ix, iy, z in cluster])
            centre = pts[np.argmin(np.linalg.norm(pts - pts.mean(axis=0), axis=1))]
            details = {
                "cells": len(cluster),
                "bbox": [_xyz(pts.min(axis=0)), _xyz(pts.max(axis=0))],
            }
            if rule == "narrow_passage":
                details["min_width_estimate"] = min(width[k] for k in cluster)
            findings.append(
                Finding(
                    rule,
                    WARNING,
                    f"Passage {text} around {_xyz(centre)} (feet height)",
                    "bsp",
                    location=_xyz(centre),
                    details=details,
                )
            )
    stats = {
        "standing_cells": len(spots),
        "walkable_area_units2": int(len(spots) * cell * cell),
        "narrow_cells": len(narrow_keys),
        "low_ceiling_cells": len(low_keys),
    }
    return findings, stats


def _clusters(cells: set[tuple[int, int, float]], max_step: float) -> list[list]:
    """8-connected components (same floor within max_step), largest first."""
    by_xy: dict[tuple[int, int], list[float]] = defaultdict(list)
    for ix, iy, z in cells:
        by_xy[(ix, iy)].append(z)
    seen: set[tuple[int, int, float]] = set()
    clusters = []
    for start in cells:
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            ix, iy, z = stack.pop()
            comp.append((ix, iy, z))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for nz in by_xy.get((ix + dx, iy + dy), []):
                        n = (ix + dx, iy + dy, nz)
                        if n not in seen and abs(nz - z) <= max_step:
                            seen.add(n)
                            stack.append(n)
        clusters.append(comp)
    return sorted(clusters, key=len, reverse=True)
