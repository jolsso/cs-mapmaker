"""Validate every reference map matching a prefix and summarise (calibration, phase 1b).

Usage: python -m mapforge.validate.reference_report [--prefix de_]
Writes build/reference_report.json and prints one row per map.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

from mapforge.config import load_config
from mapforge.refmaps import extract_archives, list_reference_maps
from mapforge.validate.run import validate_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="de_")
    args = parser.parse_args(argv)
    cfg = load_config()
    extract_archives(cfg)
    maps = {k: v for k, v in list_reference_maps(cfg).items() if k.startswith(args.prefix)}
    rows = []
    print(
        f"{'map':16} {'s':>5} {'err':>4} {'warn':>4}  {'reach T/CT per site':24} "
        f"{'design norms (info)':28} other rules"
    )
    for name, bsp in maps.items():
        t0 = time.monotonic()
        r = validate_map(cfg, name, reference_bsp=bsp)
        secs = time.monotonic() - t0
        sites = r["stats"].get("reachability", {}).get("sites", [])
        spawns = r["stats"]["entities"]["spawns"]
        reach = " ".join(
            f"{s['spawns_reaching']['T']}/{spawns['T']},{s['spawns_reaching']['CT']}/{spawns['CT']}"
            for s in sites
        )
        rules = Counter(f"{f['rule']}" for f in r["findings"])
        rows.append(
            {
                "map": name,
                "seconds": round(secs, 1),
                "ok": r["ok"],
                "summary": r["summary"],
                "rules": dict(rules),
                "sites": sites,
                "walkable": r["stats"].get("walkable"),
                "errors": [f for f in r["findings"] if f["severity"] == "error"],
            }
        )
        walk = r["stats"].get("walkable") or {}
        norms = (
            f"narrow {walk.get('narrow_passage_clusters', 0)} / "
            f"low {walk.get('low_ceiling_clusters', 0)} clusters"
        )
        rule_txt = ", ".join(
            f"{k}×{v}"
            for k, v in sorted(rules.items())
            if k not in ("narrow_passage", "low_ceiling")
        )
        s = r["summary"]
        print(
            f"{name:16} {secs:5.1f} {s['errors']:4} {s['warnings']:4}  {reach:24} "
            f"{norms:28} {rule_txt}"
        )
    out = cfg.path("build_dir") / "reference_report.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
