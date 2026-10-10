"""Running confidence intervals and the early-stop rule for simulation batches.

Rule (docs/FITNESS.md, min_rounds): a result *inside* the target range needs the full
min_rounds before it counts; a result clearly *outside* (the whole interval misses the range)
is decided early, since more rounds cannot rescue it and the loop should change the map.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any


def wilson(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; (0, 1) when n == 0."""
    if n == 0:
        return 0.0, 1.0
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _relation(ci: tuple[float, float], target: list[float]) -> str:
    lo, hi = ci
    if hi < target[0] or lo > target[1]:
        return "outside"
    if lo >= target[0] and hi <= target[1]:
        return "inside"
    return "open"


def summarize(rounds: list[dict], confidence: float, targets: dict[str, list[float]]) -> dict:
    """Proportions with intervals over valid rounds; `rounds` are rows of rounds.csv."""
    n = len(rounds)
    t_wins = sum(r["winner"] == "T" for r in rounds)
    plants = [r["plant_site"] for r in rounds if r["plant_site"]]
    a = sum(p == "A" for p in plants)
    out: dict[str, Any] = {"rounds": n, "t_wins": t_wins, "plants": len(plants), "plants_a": a}
    for key, k, m in (("t_winrate", t_wins, n), ("site_split_a", a, len(plants))):
        ci = wilson(k, m, confidence)
        out[key] = {
            "value": round(k / m, 3) if m else None,
            "ci": [round(ci[0], 3), round(ci[1], 3)],
            "n": m,
            "target": targets.get(key),
            "relation": _relation(ci, targets[key]) if key in targets and m else "open",
        }
    return out


def stop_decision(summary: dict, min_rounds: int, max_rounds: int) -> tuple[bool, str]:
    n = summary["rounds"]
    if n >= max_rounds:
        return True, f"max_rounds ({max_rounds}) reached"
    keys = ("t_winrate", "site_split_a")
    for k in keys:
        if summary[k]["relation"] == "outside":
            return True, f"{k} decided outside the target range"
    if n >= min_rounds and all(summary[k]["relation"] == "inside" for k in keys):
        return True, f"targets decided inside after {n} rounds"
    return False, ""
