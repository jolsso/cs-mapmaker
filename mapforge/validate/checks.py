"""Validation checks. Each returns a list of Findings; errors fail the iteration (FITNESS.md)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, Bsp
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.parser import MapFile
from mapforge.validate.walk import WalkGraph, bomb_sites, nodes_touching

ERROR = "error"
WARNING = "warning"
INFO = "info"  # design-norm notes on reference maps; never fails, not counted

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
    policy_severity: str = ERROR,
) -> tuple[list[Finding], list[dict[str, Any]]]:
    """> 100 % exceeds the engine (error); > error_pct breaks the FITNESS headroom policy."""
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
        if u["pct"] > 100:
            rule, sev, why = "limit_exceeded", ERROR, "exceeds the engine limit"
        elif u["pct"] > error_pct:
            rule, sev, why = "limit", policy_severity, f"above the {error_pct:g} % headroom policy"
        elif u["pct"] > warn_pct:
            rule, sev, why = "limit", WARNING, f"above {warn_pct:g} %"
        else:
            continue
        out.append(
            Finding(
                rule,
                sev,
                f"{u['name']}: {u['used']}/{u['max']} ({u['pct']:.1f} %), {why}",
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
    # Several adjacent func_bomb_target brushes form one site (de_prodigy, de_torn).
    n_sites = len(bomb_sites(bsp)) if bsp is not None else len(bombs)
    need_bombs = (
        int((rules.get("bomb_targets") or {}).get(mtype, 0))
        if isinstance(rules.get("bomb_targets"), dict)
        else int(rules.get("bomb_targets") or 0)
    )
    if need_bombs and n_sites != need_bombs:
        out.append(
            Finding(
                "bomb_targets",
                ERROR,
                f"{n_sites} bomb sites ({len(bombs)} bomb target entities), "
                f"{mtype}_ maps need exactly {need_bombs}",
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
        "bomb_sites": n_sites,
        "buyzones": {**buy, "implicit": implicit_buy},
        "entities": len(entities),
    }
    return out, stats


# --- walkable space (clip hull 1 = standing player) ------------------------------------------


def spawn_origins(entities: list[dict[str, str]]) -> tuple[np.ndarray, list[str]]:
    """Origins of all T and CT spawns (n, 3) and their team per row."""
    rows, teams = [], []
    for e in entities:
        team = {T_SPAWN: "T", CT_SPAWN: "CT"}.get(e.get("classname", ""))
        o = _origin(e)
        if team and o is not None:
            rows.append(o)
            teams.append(team)
    return (np.array(rows) if rows else np.zeros((0, 3))), teams


def check_reachability(
    bsp: Bsp, graph: WalkGraph, teams: list[str]
) -> tuple[list[Finding], dict[str, Any]]:
    """FITNESS hard requirement: every spawn can reach both bomb sites (on foot)."""
    out = []
    sites = []
    for n, boxes in enumerate(bomb_sites(bsp), start=1):
        targets = np.unique(np.concatenate([nodes_touching(graph, lo, hi) for lo, hi in boxes]))
        lo = np.min([b[0] for b in boxes], axis=0)
        hi = np.max([b[1] for b in boxes], axis=0)
        can_reach = graph.reverse_reachable(targets)
        centre = (lo + hi) / 2
        site = {"site": n, "centre": _xyz(centre), "bbox": [_xyz(lo), _xyz(hi)],
                "standable_cells": len(targets), "spawns_reaching": {"T": 0, "CT": 0}}  # fmt: skip
        stuck_at: dict[str, list[list[float]]] = {"T": [], "CT": []}
        for seed, team in zip(graph.seeds, teams, strict=True):
            if seed is not None and can_reach[seed]:
                site["spawns_reaching"][team] += 1
            elif seed is not None:
                stuck_at[team].append(_xyz(graph.feet[seed]))
        for team, where in stuck_at.items():
            if where:
                out.append(
                    Finding(
                        "unreachable_site",
                        ERROR,
                        f"{len(where)} {team} spawn(s) cannot walk to bomb site {n} "
                        f"(centre {_xyz(centre)})",
                        "bsp",
                        location=where[0],
                        details={"site": n, "spawns": where[:10]},
                    )
                )
        if not len(targets):
            out.append(
                Finding(
                    "site_not_standable",
                    ERROR,
                    f"No reachable place to stand inside bomb site {n} (centre {_xyz(centre)})",
                    "bsp",
                    location=_xyz(centre),
                )
            )
        sites.append(site)
    for seed, team in zip(graph.seeds, teams, strict=True):
        if seed is None:
            out.append(
                Finding(
                    "spawn_unplaced",
                    WARNING,
                    f"A {team} spawn has no ground below it within the drop limit",
                    "bsp",
                )
            )
    return out, {"sites": sites}


def _runs(keys: dict[tuple[int, int], list[float]], axis: int, max_step: float) -> dict:
    """Per spot: (length in cells, walled) of its contiguous walkable run along one axis.

    `walled` is True when the column just beyond both ends of the run has no walkable spot
    at all (a wall or solid). A run that ends at a drop or ledge (a lower floor next to it)
    is not walled, so ledges and catwalk edges are not mistaken for narrow corridors.
    """
    run_of: dict[tuple[int, int, float], int] = {}
    members: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    next_id = 0
    step = (1, 0) if axis == 0 else (0, 1)
    for ix, iy in sorted(keys, key=lambda k: (k[1 - axis], k[axis])):
        prev = (ix - step[0], iy - step[1])
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
    walled = {}
    for rid, cells in members.items():
        first, last = cells[0], cells[-1]
        before = (first[0] - step[0], first[1] - step[1])
        after = (last[0] + step[0], last[1] + step[1])
        walled[rid] = before not in keys and after not in keys
    return {k: (len(members[r]), walled[r]) for k, r in run_of.items()}


def check_corridors(
    graph: WalkGraph, bsp: Bsp, cfg: dict[str, Any], severity: str = WARNING
) -> tuple[list[Finding], dict[str, Any]]:
    """Narrow passages and low ceilings where players can actually walk (graph nodes).

    These are design norms (CLAUDE.md), not validity: `severity` is a warning for our maps
    and info for reference maps.
    """
    cell = graph.cell
    min_w, min_h, max_step = (
        float(cfg["min_width"]),
        float(cfg["min_height"]),
        float(cfg["max_step"]),
    )
    min_cells = int(cfg.get("min_cluster_cells", 4))
    max_reported = int(cfg.get("max_reported", 20))
    spots = graph.standing()
    if not len(spots):
        return [Finding("no_walkable_space", ERROR, "No place where a player can stand", "bsp")], {}

    keys: dict[tuple[int, int], list[float]] = defaultdict(list)
    for x, y, z in spots:
        keys[(int(round(x / cell)), int(round(y / cell)))].append(float(z))
    run_x = _runs(keys, 0, max_step)
    run_y = _runs(keys, 1, max_step)
    # Free span of hull centres is between (n-1)*cell and n*cell; the passage is that plus the
    # 32-unit hull. Use the generous end so only clearly narrow passages are flagged. Only
    # runs with a wall at both ends count as a passage width.
    width = {}
    for k in run_x:
        spans = [n * cell + 32 for n, walled in (run_x[k], run_y[k]) if walled]
        width[k] = min(spans) if spans else float("inf")

    head = spots + np.array([0.0, 0.0, min_h - 72])
    low = bsp.point_contents(head, hull=1) == CONTENTS_SOLID
    low_keys = {
        (int(round(x / cell)), int(round(y / cell)), float(z))
        for (x, y, z), is_low in zip(spots, low, strict=True)
        if is_low
    }
    narrow_keys = {k for k, w in width.items() if w < min_w}

    findings = []
    stats: dict[str, Any] = {
        "reachable_cells": len(spots),
        "walkable_area_units2": int(len(spots) * cell * cell),
    }
    for rule, cells, text in (
        ("narrow_passage", narrow_keys, f"narrower than {min_w:g} units"),
        ("low_ceiling", low_keys, f"lower than {min_h:g} units"),
    ):
        clusters = [c for c in _clusters(cells, max_step) if len(c) >= min_cells]
        stats[f"{rule}_cells"] = sum(len(c) for c in clusters)
        stats[f"{rule}_clusters"] = len(clusters)
        for cluster in clusters[:max_reported]:
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
                    severity,
                    f"Passage {text} around {_xyz(centre)} (feet height)",
                    "bsp",
                    location=_xyz(centre),
                    details=details,
                )
            )
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
