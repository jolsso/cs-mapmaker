"""Geometric design rules from the design research (docs/DESIGN_GUIDE.md §9): what bots cannot
judge, measured on the compiled map.

- rotation: site A <-> B on foot (string-pulled, 250 u/s), against the C4 timer
- sight lines: spawn <-> spawn and spawn -> site (eye height, hull 0 line of sight)
- territory: share of the walkable area a team reaches first (travel time from its spawns)
- sight-line spread: longest view per standing spot (rays at eye height): long (AWP) and close
  (CQB) fighting must both exist
- layout graph (our maps only, from layout.yaml): entrances per site, 4-way junctions,
  Ølsted's complexity C = three-way junctions + room entrances

All thresholds are in config/pipeline.yaml -> validate.design and calibrated on the official maps.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from mapforge.bsp.reader import CONTENTS_SOLID, Bsp
from mapforge.validate.timings import RUN_SPEED, path_length
from mapforge.validate.walk import STAND, WalkGraph, bomb_sites, nodes_touching, site_labels

EYE = 64.0  # eye height above the feet (standing view offset 28 over the 36 hull centre)


def los(bsp: Bsp, a: np.ndarray, b: np.ndarray, step: float = 12.0) -> bool:
    """True if nothing solid (hull 0) lies on the straight line a -> b."""
    n = max(2, int(np.linalg.norm(b - a) / step))
    pts = a[None, :] + (b - a)[None, :] * np.linspace(0, 1, n)[:, None]
    return not np.any(bsp.point_contents(pts, hull=0) == CONTENTS_SOLID)


def _dists(graph: WalkGraph, sources: list[int]) -> np.ndarray:
    """Multi-source BFS over the walk graph (cells ~ equal step), in graph cells."""
    n = len(graph.feet)
    dist = np.full(n, np.inf)
    if not sources or not len(graph.edges):
        return dist
    order = np.argsort(graph.edges[:, 0], kind="stable")
    dst = graph.edges[order, 1]
    starts = np.searchsorted(graph.edges[order, 0], np.arange(n + 1))
    frontier = np.array(sorted(set(sources)), dtype=np.int64)
    dist[frontier] = 0
    d = 0
    while len(frontier):
        d += 1
        lo, hi = starts[frontier], starts[frontier + 1]
        cnt = hi - lo
        if not cnt.sum():
            break
        # all out-edges of the frontier, vectorised
        idx = np.repeat(lo - np.concatenate([[0], np.cumsum(cnt)[:-1]]), cnt) + np.arange(cnt.sum())
        nxt = np.unique(dst[idx])
        nxt = nxt[np.isinf(dist[nxt])]
        dist[nxt] = d
        frontier = nxt
    return dist


def rotation(bsp: Bsp, graph: WalkGraph) -> list[dict[str, Any]]:
    """Shortest on-foot time between every pair of bomb sites (site centre to site)."""
    sites = bomb_sites(bsp)
    labels = site_labels(bsp)
    nodes = [
        np.unique(np.concatenate([nodes_touching(graph, lo, hi) for lo, hi in boxes]))
        for boxes in sites
    ]
    out = []
    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            if not len(nodes[i]) or not len(nodes[j]):
                continue
            centre = np.mean([(lo + hi) / 2 for lo, hi in sites[i]], axis=0)
            src = int(
                nodes[i][np.argmin(np.linalg.norm(graph.feet[nodes[i], :2] - centre[:2], axis=1))]
            )
            path = graph.shortest_path(src, nodes[j])
            if path:
                out.append({"sites": f"{labels[i]}-{labels[j]}",
                            "seconds": round(path_length(bsp, graph.feet[path]) / RUN_SPEED, 1)})  # fmt: skip
    return out


def spawn_sightlines(
    bsp: Bsp, origins: np.ndarray, teams: list[str], max_pairs: int = 64
) -> dict[str, Any]:
    """Spawn <-> spawn and spawn -> site lines of sight at eye height."""
    eye = origins + [0, 0, EYE - 36]  # origins are hull centres (feet + 36)
    t = eye[[i for i, x in enumerate(teams) if x == "T"]]
    ct = eye[[i for i, x in enumerate(teams) if x == "CT"]]
    rng = np.random.default_rng(0)

    def sample(a: np.ndarray, k: int) -> np.ndarray:
        return a[rng.choice(len(a), size=min(k, len(a)), replace=False)] if len(a) else a

    seen = []
    for a in sample(t, 8):
        for b in sample(ct, 8):
            if los(bsp, a, b):
                seen.append([a.round().tolist(), b.round().tolist()])
    site_seen: dict[str, int] = {}
    for boxes, label in zip(bomb_sites(bsp), site_labels(bsp), strict=True):
        pts = []
        for lo, hi in boxes:
            c = (lo + hi) / 2
            for dx in (-0.3, 0, 0.3):
                for dy in (-0.3, 0, 0.3):
                    pts.append(
                        [c[0] + dx * (hi[0] - lo[0]), c[1] + dy * (hi[1] - lo[1]), lo[2] + EYE]
                    )
        hits = 0
        for team_pts, team in ((t, "T"), (ct, "CT")):
            if team != "T":
                continue  # attackers must not see a site from their spawn
            for a in sample(team_pts, 8):
                hits += sum(los(bsp, a, np.array(p)) for p in pts[:max_pairs])
        site_seen[label] = hits
    return {
        "spawn_to_spawn": seen[:5],
        "spawn_to_spawn_pairs": len(seen),
        "t_spawn_to_site": site_seen,
    }


def territory(graph: WalkGraph, teams: list[str]) -> dict[str, Any]:
    """Share of walkable nodes a team reaches first (walk-graph steps from its spawns)."""
    seeds = {
        team: [s for s, t in zip(graph.seeds, teams, strict=True) if t == team and s is not None]
        for team in ("T", "CT")
    }
    dt, dc = _dists(graph, seeds["T"]), _dists(graph, seeds["CT"])
    reach = np.isfinite(dt) | np.isfinite(dc)
    n = int(reach.sum()) or 1
    t_first = int(((dt < dc) & reach).sum())
    ct_first = int(((dc < dt) & reach).sum())
    return {"t_share": round(t_first / n, 3), "ct_share": round(ct_first / n, 3), "nodes": n}


def sightline_spread(
    bsp: Bsp,
    graph: WalkGraph,
    grid: float = 96,
    rays: int = 16,
    max_len: float = 4096,
    step: float = 24,
) -> dict[str, Any]:
    """Longest view (units) from standing spots on a coarse grid, rays at eye height."""
    st = graph.feet[graph.stance == STAND]
    if not len(st):
        return {"spots": 0}
    keys = np.round(st[:, :2] / grid)
    _, idx = np.unique(keys, axis=0, return_index=True)
    spots = st[idx] + [0, 0, EYE]
    ang = np.linspace(0, 2 * math.pi, rays, endpoint=False)
    dirs = np.column_stack([np.cos(ang), np.sin(ang), np.zeros(rays)])
    ts = np.arange(step, max_len + step, step)
    longest = np.zeros(len(spots))
    for d in dirs:
        pts = spots[:, None, :] + ts[None, :, None] * d[None, None, :]
        solid = (bsp.point_contents(pts.reshape(-1, 3), hull=0) == CONTENTS_SOLID).reshape(
            len(spots), len(ts)
        )
        first = np.where(solid.any(axis=1), solid.argmax(axis=1), len(ts))
        longest = np.maximum(longest, ts[np.clip(first - 1, 0, len(ts) - 1)] * (first > 0))
    return {
        "spots": int(len(spots)),
        "max": float(longest.max()),
        "p50": float(np.percentile(longest, 50)),
        "share_long": round(float((longest >= 1500).mean()), 3),
        "share_close": round(float((longest < 500).mean()), 3),
    }


def layout_graph(layout: dict[str, Any]) -> dict[str, Any]:
    """Topology from layout.yaml: entrances per site, junctions, Ølsted's C = n + r."""
    from mapforge.generator.spec import expand_macros

    layout = expand_macros(layout, int(layout.get("grid", 16)))
    raw = {a["name"]: a for a in layout.get("areas", [])}
    # areas that touch (no wall between them) are one room: an L-room, a split-level hall
    group = {n: n for n in raw}

    def find(n: str) -> str:
        while group[n] != n:
            n = group[n]
        return n

    names = list(raw)
    for i, n in enumerate(names):
        a = raw[n]
        for m in names[i + 1 :]:
            b = raw[m]
            (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = a["rect"], b["rect"]
            fa, fb = a.get("floor", 0), b.get("floor", 0)
            z_overlap = min(fa + a.get("height", 192), fb + b.get("height", 192)) > max(fa, fb)
            touch_x = (ax1 == bx0 or bx1 == ax0) and min(ay1, by1) > max(ay0, by0)
            touch_y = (ay1 == by0 or by1 == ay0) and min(ax1, bx1) > max(ax0, bx0)
            if z_overlap and (touch_x or touch_y):
                ra, rb = find(n), find(m)
                if ra != rb:  # keep the site / spawn as the room's name
                    keep, drop = (
                        (ra, rb)
                        if raw[ra].get("role") in ("site", "t_spawn", "ct_spawn")
                        else (rb, ra)
                    )
                    group[drop] = keep
    areas = {n: raw[n] for n in raw if find(n) == n}
    degree = {n: 0 for n in areas}
    walk_doors = [
        (find(d["between"][0]), find(d["between"][1]))
        for d in layout.get("doors", [])
        if d.get("kind", "door") != "window"  # a window is a sightline, not an entrance
    ] + [(find(h["lower"]), find(h["upper"])) for h in layout.get("hatches", []) or []]
    for a, b in walk_doors:
        degree[a] += 1
        degree[b] += 1
    sites = layout.get("sites", {})
    site_areas = {k: find(v["area"] if isinstance(v, dict) else v) for k, v in sites.items()}
    # a door into a dead end (a closet, an office only reachable from the site) is part of the
    # site, not a way in
    entrances = {
        k: sum(1 for x, y in walk_doors if a in (x, y) and degree[y if x == a else x] > 1)
        for k, a in site_areas.items()
    }
    ct_areas = {a for a, x in areas.items() if x.get("role") == "ct_spawn"}
    # a site's CT entrance: a door to an area that CT reaches without crossing the site (direct
    # neighbour of the CT spawn area or the spawn itself)
    neighbours: dict[str, set[str]] = {n: set() for n in areas}
    for a, b in walk_doors:
        neighbours[a].add(b)
        neighbours[b].add(a)
    ct_side = set(ct_areas) | {n for c in ct_areas for n in neighbours[c]}
    ct_entrance = {k: bool(neighbours.get(a, set()) & ct_side) for k, a in site_areas.items()}
    junction = {
        n: d
        for n, d in degree.items()
        if areas[n].get("role") not in ("site", "t_spawn", "ct_spawn")
    }
    four_way = sorted(n for n, d in junction.items() if d >= 4)
    three_way = sum(1 for d in junction.values() if d == 3)
    room_entrances = sum(
        degree[n] for n, a in areas.items() if a.get("role") in ("site", "room", "mid")
    )
    return {
        "site_entrances": entrances,
        "site_ct_entrance": ct_entrance,
        "four_way": four_way,
        "three_way": three_way,
        "complexity_c": three_way + room_entrances,
    }


def design_findings(stats: dict[str, Any], cfg: dict[str, Any], reference: bool) -> list:
    """Findings for the design rules (severity: info on reference maps)."""
    from mapforge.validate.checks import ERROR, INFO, WARNING, Finding

    def sev(level: str) -> str:
        return INFO if reference else {"error": ERROR, "warning": WARNING}.get(level, WARNING)

    out = []
    lo, hi = cfg["rotation_s"]
    for r in stats.get("rotation", []):
        if not lo <= r["seconds"] <= hi:
            what = (
                "fast: CT can stack one site and still retake"
                if r["seconds"] < lo
                else "slow: a planted bomb cannot be retaken in time"
            )
            out.append(
                Finding(
                    "rotation_time",
                    sev("warning"),
                    f"rotation {r['sites']} takes {r['seconds']} s (norm {lo}-{hi} s): too {what}",
                    "bsp",
                    details=r,
                )
            )
    sl = stats.get("spawn_sightlines", {})
    if sl.get("spawn_to_spawn_pairs"):
        out.append(Finding("spawn_sightline", sev(cfg.get("spawn_to_spawn", "error")),
                           f"T and CT spawns see each other ({sl['spawn_to_spawn_pairs']} of 64 sampled pairs)", "bsp",
                           location=sl["spawn_to_spawn"][0][0], details={"pairs": sl["spawn_to_spawn"]}))  # fmt: skip
    for site, hits in sl.get("t_spawn_to_site", {}).items():
        if hits:
            out.append(Finding("spawn_sees_site", sev(cfg.get("t_spawn_to_site", "warning")),
                               f"site {site} is visible from the T spawn ({hits} sight lines)", "bsp"))  # fmt: skip
    terr = stats.get("territory", {})
    big = max(terr.get("t_share", 0), terr.get("ct_share", 0))
    if big > cfg["territory_max_share"]:
        team = "T" if terr["t_share"] > terr["ct_share"] else "CT"
        out.append(
            Finding(
                "territory",
                sev("error"),
                f"{team} reaches {big:.0%} of the map first (> {cfg['territory_max_share']:.0%})",
                "bsp",
                details=terr,
            )
        )
    if terr.get("t_share", 0) > cfg.get("max_t_share", 1) and big <= cfg["territory_max_share"]:
        out.append(
            Finding(
                "territory_t_heavy",
                sev("warning"),
                f"T reaches {terr['t_share']:.0%} of the map first (official maps: 29-54 %; sites should sit closer to CT)",
                "bsp",
                details=terr,
            )
        )
    sp = stats.get("sightlines", {})
    if sp.get("spots"):
        if sp["share_long"] < cfg["min_share_long"]:
            out.append(
                Finding(
                    "no_long_sightline",
                    sev("warning"),
                    f"almost no long sight lines (>= {cfg['long_sightline_units']} u: {sp['share_long']:.1%} of spots): no AWP fights",
                    "bsp",
                    details=sp,
                )
            )
        if sp["share_close"] < cfg["min_share_close"]:
            out.append(
                Finding(
                    "no_close_quarters",
                    sev("warning"),
                    f"almost no close-quarters spots (< {cfg['close_sightline_units']} u: {sp['share_close']:.1%}): no CQB fights",
                    "bsp",
                    details=sp,
                )
            )
    lg = stats.get("layout_graph")
    if lg:
        a, b = cfg["site_entrances"]
        for site, n in lg["site_entrances"].items():
            if not a <= n <= b:
                out.append(
                    Finding(
                        "site_entrances",
                        sev("warning"),
                        f"site {site} has {n} entrances (norm {a}-{b})",
                        "map",
                    )
                )
            if not lg["site_ct_entrance"].get(site):
                out.append(
                    Finding(
                        "site_no_ct_entrance",
                        sev("warning"),
                        f"site {site} has no entrance from the CT side (retake route)",
                        "map",
                    )
                )
        for name in lg["four_way"]:
            out.append(
                Finding(
                    "four_way_junction",
                    sev(cfg.get("four_way", "warning")),
                    f"{name} is a 4-way junction (Ølsted: too many choices on a route)",
                    "map",
                )
            )
    return out


def design_stats(
    bsp: Bsp, graph: WalkGraph, origins: np.ndarray, teams: list[str], layout: dict[str, Any] | None
) -> dict[str, Any]:
    out = {
        "rotation": rotation(bsp, graph),
        "spawn_sightlines": spawn_sightlines(bsp, origins, teams),
        "territory": territory(graph, teams),
        "sightlines": sightline_spread(bsp, graph),
    }
    if layout:
        out["layout_graph"] = layout_graph(layout)
    return out
