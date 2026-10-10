"""Gameplay metrics from tracker data (docs/FITNESS.md -> "Gameplay-mål"), with intervals.

Every metric is {"value", "ci", "n", "target", "distance"}; distance = 0 inside the target
range, else the gap to the nearest bound divided by the range width. The score is the weighted
sum of distances (config/fitness.yaml -> weights); 0 = all targets met.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from mapforge.simulate.stats import wilson


def bootstrap_median(values: list[float], resamples: int, confidence: float = 0.95, seed: int = 0):
    """Median with a percentile-bootstrap interval (fixed seed: reproducible)."""
    if not values:
        return None, [None, None]
    v = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    meds = np.median(rng.choice(v, size=(resamples, len(v)), replace=True), axis=1)
    a = (1 - confidence) / 2
    return float(np.median(v)), [float(np.quantile(meds, a)), float(np.quantile(meds, 1 - a))]


def distance(value: float | None, target: list[float] | None) -> float | None:
    if value is None or target is None:
        return None
    lo, hi = target
    width = (hi - lo) or 1.0
    if value < lo:
        return (lo - value) / width
    if value > hi:
        return (value - hi) / width
    return 0.0


def _metric(value, ci, n, target) -> dict[str, Any]:
    r = lambda x: None if x is None else round(float(x), 3)  # noqa: E731
    return {
        "value": r(value),
        "ci": [r(ci[0]), r(ci[1])],
        "n": n,
        "target": target,
        "distance": r(distance(value, target)),
    }


def first_contacts(events: list[dict], rounds: list[dict]) -> list[float]:
    """Seconds from round start to the first enemy damage, per round (rounds without: skipped).

    Uses the plugin's first_contact event; falls back to the first damage between teams.
    """
    keys = {(r["run_id"], r["round"]) for r in rounds}
    first: dict[tuple, float] = {}
    for e in events:
        key = (e["run_id"], e["round"])
        if key not in keys:
            continue
        if e["type"] == "first_contact" or (
            e["type"] == "damage"
            and e["actor_team"]
            and e["target_team"]
            and e["actor_team"] != e["target_team"]
        ):
            first[key] = min(first.get(key, float("inf")), e["t"])
    return sorted(first.values())


def _cells(xy: np.ndarray, size: float) -> np.ndarray:
    return np.floor(np.asarray(xy, dtype=np.float64)[:, :2] / size).astype(np.int64)


def dead_zones(
    walk_xy: np.ndarray,
    pos_xy: np.ndarray,
    cell: float,
    min_frac: float,
    node_spacing: float = 16,
    min_cover: float = 0.5,
) -> dict:
    """Share of walkable 2-D cells with ~no traffic, and those cells (world centres).

    A cell counts as walkable when at least `min_cover` of it holds walk-graph nodes (spaced
    `node_spacing`): thin strips along walls are not floor bots would use.
    """
    walk: set[tuple] = set()
    if len(walk_xy):
        uniq = np.unique(np.round(np.asarray(walk_xy)[:, :2] / node_spacing), axis=0) * node_spacing
        cells, n = np.unique(_cells(uniq, cell), axis=0, return_counts=True)
        need = min_cover * (cell / node_spacing) ** 2
        walk = {tuple(c) for c, k in zip(cells, n, strict=True) if k >= need}
    counts: dict[tuple, int] = {}
    if len(pos_xy):
        cells, n = np.unique(_cells(pos_xy, cell), axis=0, return_counts=True)
        counts = {tuple(c): int(k) for c, k in zip(cells, n, strict=True)}
    if not walk:
        return {"share": None, "cells": [], "walkable_cells": 0, "threshold": None}
    mean = sum(counts.get(c, 0) for c in walk) / len(walk)
    threshold = max(1.0, min_frac * mean)
    dead = sorted(c for c in walk if counts.get(c, 0) < threshold)
    return {
        "share": len(dead) / len(walk),
        "walkable_cells": len(walk),
        "threshold": round(threshold, 2),
        "cells": [[(c[0] + 0.5) * cell, (c[1] + 0.5) * cell] for c in dead],
    }


def kill_concentration(kill_xy: np.ndarray, cell: float, top: int = 5) -> dict:
    """Largest share of all kills (victim positions) inside one cell, plus the top cells."""
    if not len(kill_xy):
        return {"share": None, "kills": 0, "top": []}
    cells, n = np.unique(_cells(kill_xy, cell), axis=0, return_counts=True)
    order = np.argsort(-n)[:top]
    return {
        "share": float(n.max() / n.sum()),
        "kills": int(n.sum()),
        "top": [
            {"x": float((cells[i][0] + 0.5) * cell), "y": float((cells[i][1] + 0.5) * cell),
             "kills": int(n[i]), "share": round(float(n[i] / n.sum()), 3)}
            for i in order
        ],
    }  # fmt: skip


def compute(
    data: dict[str, list[dict]],
    valid: list[dict],
    walk_xy: np.ndarray,
    fitness: dict[str, Any],
    acfg: dict[str, Any],
    confidence: float = 0.95,
) -> dict[str, Any]:
    """All FITNESS gameplay metrics over the valid rounds.

    `targets` are scored; `diagnostics` keep a reference band for display but never count.
    """
    scored = fitness["targets"]
    targets = {**fitness.get("diagnostics", {}), **scored}
    keys = {(r["run_id"], r["round"]) for r in valid}
    n = len(valid)
    t_wins = sum(r["winner"] == "T" for r in valid)
    plants = [r["plant_site"] for r in valid if r["plant_site"]]
    plants_a = sum(p == "A" for p in plants)
    contact = first_contacts(data["events"], valid)
    lengths = [r["end_time"] - r["start_time"] for r in valid]
    boot = int(acfg["bootstrap"])
    pos = np.array(
        [(p["x"], p["y"]) for p in data["positions"]
         if p["alive"] and (p["run_id"], p["round"]) in keys]
    ).reshape(-1, 2)  # fmt: skip
    kills = np.array(
        [(e["tx"], e["ty"]) for e in data["events"]
         if e["type"] == "kill" and (e["run_id"], e["round"]) in keys]
    ).reshape(-1, 2)  # fmt: skip
    dz = dead_zones(walk_xy, pos, float(acfg["dead_zone_cell"]), float(acfg["dead_zone_min_frac"]))
    kc = kill_concentration(kills, float(acfg["kill_cell"]))

    metrics = {
        "t_winrate": _metric(t_wins / n if n else None, wilson(t_wins, n, confidence), n,
                             targets.get("t_winrate")),
        "site_split_a": _metric(plants_a / len(plants) if plants else None,
                                wilson(plants_a, len(plants), confidence), len(plants),
                                targets.get("site_split_a")),
        "first_contact_s": _metric(*bootstrap_median(contact, boot, confidence), len(contact),
                                   targets.get("first_contact_s")),
        "dead_zone_share": _metric(dz["share"], [None, None], dz["walkable_cells"],
                                   targets.get("dead_zone_share")),
        "max_kill_cell_share": _metric(kc["share"], [None, None], kc["kills"],
                                       targets.get("max_kill_cell_share")),
        "round_length_median_s": _metric(*bootstrap_median(lengths, boot, confidence), n,
                                         targets.get("round_length_median_s")),
    }  # fmt: skip
    weights = fitness.get("weights", {})
    parts = {
        k: metrics[k]["distance"] for k in weights if metrics.get(k, {}).get("distance") is not None
    }
    score = sum(weights[k] * d for k, d in parts.items()) if parts else None
    # per-round series for charts (site), in play order
    contact_by: dict[tuple, float] = {}
    for e in data["events"]:
        key = (e["run_id"], e["round"])
        if key in keys and e["type"] == "first_contact":
            contact_by[key] = min(contact_by.get(key, float("inf")), e["t"])
    series = [
        {"run": r["run_id"], "round": r["round"], "winner": r["winner"], "reason": r["reason"],
         "site": r["plant_site"], "length_s": round(r["end_time"] - r["start_time"], 1),
         "contact_s": round(contact_by[(r["run_id"], r["round"])], 1)
         if (r["run_id"], r["round"]) in contact_by else None}
        for r in sorted(valid, key=lambda r: (r["run_id"], r["round"]))
    ]  # fmt: skip
    reasons: dict[str, int] = {}
    for r in valid:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {
        "series": series,
        "rounds": n,
        "min_rounds": int(fitness.get("min_rounds", 100)),
        "enough_rounds": n >= int(fitness.get("min_rounds", 100)),
        "metrics": metrics,
        "score": None if score is None else round(score, 4),
        "score_parts": {k: round(weights[k] * d, 4) for k, d in parts.items()},
        "targets_met": all(metrics[k]["distance"] == 0 for k in metrics if k in scored),
        "diagnostics": sorted(k for k in metrics if k not in scored),
        "round_reasons": reasons,
        "plants": {"A": plants_a, "other": len(plants) - plants_a,
                   "by_site": {s: plants.count(s) for s in sorted(set(plants))}},
        "kills": {"total": kc["kills"], "per_round": round(kc["kills"] / n, 2) if n else None,
                  "top_cells": kc["top"]},
        "dead_zones": {k: dz[k] for k in ("walkable_cells", "threshold")} | {
            "cells": dz["cells"], "count": len(dz["cells"])},
    }  # fmt: skip
