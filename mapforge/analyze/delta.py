"""Delta report: this measurement against a baseline (previous/best version).

A change only counts when it is above the noise (docs/FITNESS.md -> Statistik): for metrics
with an interval, the two intervals must not overlap; for the rest, |change| >= `min_change`.
The verdict is judged by the distance to the target range, not the raw value.
"""

from __future__ import annotations

from typing import Any

MIN_CHANGE = {"dead_zone_share": 0.01, "max_kill_cell_share": 0.02}


def _overlap(a: list, b: list) -> bool:
    if None in a or None in b:
        return True
    return not (a[1] < b[0] or b[1] < a[0])


def compare(cur: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"metrics": {}}
    for key, m in cur["metrics"].items():
        b = base.get("metrics", {}).get(key)
        if not b or m["value"] is None or b["value"] is None:
            continue
        change = round(m["value"] - b["value"], 3)
        if m["ci"][0] is not None and b["ci"][0] is not None:
            noise = _overlap(m["ci"], b["ci"])
        else:
            noise = abs(change) < MIN_CHANGE.get(key, 0.01)
        d0, d1 = b.get("distance"), m.get("distance")
        if noise or d0 is None or d1 is None or d0 == d1:
            verdict = "støj" if noise else "uændret ift. mål"
        else:
            verdict = "bedre" if d1 < d0 else "værre"
        out["metrics"][key] = {
            "before": b["value"],
            "after": m["value"],
            "change": change,
            "distance_before": d0,
            "distance_after": d1,
            "verdict": verdict,
        }
    s0, s1 = base.get("score"), cur.get("score")
    out["score"] = {"before": s0, "after": s1}
    worse = [k for k, v in out["metrics"].items() if v["verdict"] == "værre"]
    better = [k for k, v in out["metrics"].items() if v["verdict"] == "bedre"]
    out["better"], out["worse"] = better, worse
    out["verdict"] = "værre" if worse and not better else "bedre" if better and not worse else (
        "blandet" if better else "støj")  # fmt: skip
    return out
