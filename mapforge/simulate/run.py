"""Simulation: HLDS + YaPB bots play the map; the tracker plugin logs CSV (phase 4).

  1. Build/reuse the server image (docker/hlds/, mapforge.simulate.image).
  2. Smoke run (smoke_rounds on one server): server starts, YaPB graph exists, bots move and
     reach both bomb sites, CSV matches the schema. Stops here if it fails.
  3. Batches of batch_rounds split over `servers` parallel servers, until the early-stop rule
     (mapforge.simulate.stats) or max_rounds.

Output: <out>/{smoke,b01,b02,...}/<run_id>/ (CSV, server.log, demos) and <out>/simulation.json
(copied to build/<map>/simulation.json). Default <out> = build/<map>/sim/ (cleared per run);
the loop (phase 6) passes runs/<map>/<NNN>/sim.

Usage: python -m mapforge.simulate.run --map de_forge01 [--rounds N] [--smoke-only] [--watch]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from mapforge.config import Config, load_config
from mapforge.simulate.records import assign_plant_sites, load_run, valid_round
from mapforge.simulate.server import ServerJob, run_server
from mapforge.simulate.stats import stop_decision, summarize


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_bsp(cfg: Config, map_name: str, source: str) -> Path | None:
    if source == "reference":
        from mapforge.refmaps import extract_archives, find_reference_bsp

        extract_archives(cfg)
        return find_reference_bsp(cfg, map_name)
    bsp = cfg.path("build_dir") / map_name / f"{map_name}.bsp"
    return bsp if bsp.is_file() else None


def graph_cache(cfg: Config, map_name: str, bsp_sha: str) -> Path:
    """YaPB graph made for this exact .bsp (the analysis takes minutes; reuse it)."""
    return cfg.path("build_dir") / map_name / "yapb" / f"{bsp_sha[:16]}.graph"


def load_dir(sim_dir: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """Merge every server run under sim_dir (any depth) into one data set."""
    merged: dict[str, list[dict]] = {"positions": [], "events": [], "rounds": []}
    errors: list[str] = []
    for rounds_csv in sorted(sim_dir.rglob("rounds.csv")):
        data, errs = load_run(rounds_csv.parent)
        errors += [f"{rounds_csv.parent.name}/{e}" for e in errs]
        for k in merged:
            merged[k] += data[k]
    return merged, errors


def smoke_checks(data: dict[str, list[dict]], bsp: Any, rounds: int, per_team: int) -> dict:
    """Bots move and reach both bomb sites; enough valid rounds."""
    from mapforge.validate.walk import bomb_sites, site_labels

    valid = [r for r in data["rounds"] if valid_round(r, per_team)]
    tracks: dict[tuple, list] = {}
    for p in data["positions"]:
        if p["alive"]:
            tracks.setdefault((p["run_id"], p["round"], p["player_id"]), []).append(
                (p["x"], p["y"], p["z"])
            )
    moved = int(sum(np.ptp(np.array(v), axis=0)[:2].max() > 128 for v in tracks.values()))
    pts = np.array([(p["x"], p["y"], p["z"]) for p in data["positions"] if p["alive"]])
    reached: dict[str, int] = {}
    for boxes, label in zip(bomb_sites(bsp), site_labels(bsp), strict=True):
        n = 0
        for lo, hi in boxes:
            if len(pts):
                inside = np.all((pts >= lo - 32) & (pts <= hi + 32), axis=1)
                n += int(inside.sum())
        reached[label] = n
    checks = {
        "valid_rounds": {"ok": len(valid) >= rounds, "value": len(valid), "want": rounds},
        "bots_move": {
            "ok": bool(tracks) and moved >= 0.8 * len(tracks),
            "value": int(moved),
            "of": len(tracks),
        },
        "sites_reached": {
            "ok": bool(reached) and all(v > 0 for v in reached.values()),
            "samples_per_site": reached,
        },
    }
    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}


class Simulation:
    def __init__(self, cfg: Config, map_name: str, bsp: Path, out: Path, args: Any):
        import docker
        from mapforge.decide.policy import load_fitness
        from mapforge.simulate.image import build_info, ensure_image

        self.cfg, self.map_name, self.bsp, self.out = cfg, map_name, bsp, out
        self.sim = cfg.data["simulate"]
        fitness = load_fitness(cfg.root)
        self.targets = fitness["targets"]
        self.min_rounds = int(fitness.get("min_rounds", 100))
        self.max_rounds = int(args.rounds or self.sim["max_rounds"])
        self.timescale = float(self.sim["watch_timescale"] if args.watch else self.sim["timescale"])
        self.servers = 1 if args.watch else int(args.servers or self.sim["servers"])
        self.per_team = int(self.sim["bots_per_team"])
        self.client = docker.from_env(timeout=60)
        self.tag = ensure_image(cfg, self.client, log=self.log)
        self.build_info = build_info(self.client, self.tag)
        self.bsp_sha = _sha(bsp)
        self.graph = graph_cache(cfg, map_name, self.bsp_sha)
        from mapforge.bsp.reader import read_bsp

        self.bsp_data = read_bsp(bsp)

    def log(self, msg: str) -> None:
        print(msg, flush=True)

    def _job(self, group: str, index: int, rounds: int) -> ServerJob:
        demo_mode = self.sim.get("demo", "none")
        run_id = f"{group}s{index}"
        return ServerJob(
            map_name=self.map_name,
            run_id=run_id,
            rounds=rounds,
            out_dir=self.out / group / run_id,
            bsp=self.bsp,
            graph=self.graph if self.graph.is_file() else None,
            port=int(self.sim["base_port"]) + index if self.sim.get("bind") else None,
            demo=demo_mode == "all" or (demo_mode == "first_server" and index == 0),
            timescale=self.timescale,
        )

    def run_group(self, group: str, rounds: int, servers: int) -> list[dict]:
        per_server = math.ceil(rounds / servers)
        jobs = [self._job(group, i, per_server) for i in range(servers)]
        with ThreadPoolExecutor(max_workers=servers) as pool:
            statuses = list(
                pool.map(lambda j: run_server(self.client, self.tag, self.sim, j, self.log), jobs)
            )
        self._cache_graph(jobs)
        return statuses

    def _cache_graph(self, jobs: list[ServerJob]) -> None:
        if self.graph.is_file():
            return
        for j in jobs:
            made = j.out_dir / f"{self.map_name}.graph"
            if made.is_file():
                self.graph.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(made, self.graph)
                self.log(f"  YaPB graph cached: {self.graph}")
                return

    def data(self, groups: list[str]) -> tuple[dict[str, list[dict]], list[str]]:
        merged: dict[str, list[dict]] = {"positions": [], "events": [], "rounds": []}
        errors: list[str] = []
        for g in groups:
            d, e = load_dir(self.out / g)
            errors += e
            for k in merged:
                merged[k] += d[k]
        assign_plant_sites(merged, self.bsp_data)
        return merged, errors

    def run(self, smoke_only: bool, no_smoke: bool) -> dict[str, Any]:
        t0 = time.time()
        report: dict[str, Any] = {
            "map": self.map_name,
            "bsp": str(self.bsp),
            "bsp_sha256": self.bsp_sha,
            "image": self.tag,
            "build_info": self.build_info,
            "timescale": self.timescale,
            "servers": self.servers,
            "bots_per_team": self.per_team,
            "cvars": self.sim["cvars"],
            "targets": {k: self.targets[k] for k in ("t_winrate", "site_split_a")},
            "min_rounds": self.min_rounds,
            "max_rounds": self.max_rounds,
            "graph": str(self.graph) if self.graph.is_file() else None,
            "groups": [],
        }
        ok = True
        if not no_smoke:
            n = int(self.sim["smoke_rounds"])
            self.log(f"smoke: {n} rounds on 1 server (timescale {self.timescale}) ...")
            statuses = self.run_group("smoke", n, 1)
            data, errors = self.data(["smoke"])
            smoke = smoke_checks(data, self.bsp_data, n, self.per_team)
            smoke["schema_errors"] = errors
            smoke["ok"] = smoke["ok"] and not errors and all(s.get("done") for s in statuses)
            smoke["servers"] = statuses
            report["smoke"] = smoke
            report["groups"].append({"name": "smoke", "servers": statuses})
            self.log(f"smoke: {'OK' if smoke['ok'] else 'FAILED'} {json.dumps(smoke['checks'])}")
            ok = smoke["ok"]
        report["graph"] = str(self.graph) if self.graph.is_file() else None
        groups: list[str] = []
        stop_reason = "smoke failed" if not ok else ("smoke only" if smoke_only else "")
        summary: dict[str, Any] = {}
        while ok and not smoke_only:
            name = f"b{len(groups) + 1:02d}"
            remaining = self.max_rounds - (summary.get("rounds") or 0)
            rounds = min(int(self.sim["batch_rounds"]), max(remaining, 1))
            self.log(f"batch {name}: {rounds} rounds on {self.servers} servers ...")
            statuses = self.run_group(name, rounds, self.servers)
            groups.append(name)
            report["groups"].append({"name": name, "servers": statuses})
            data, errors = self.data(groups)
            valid = [r for r in data["rounds"] if valid_round(r, self.per_team)]
            summary = summarize(valid, float(self.sim["confidence"]), self.targets)
            summary["schema_errors"] = len(errors)
            summary["rounds_logged"] = len(data["rounds"])
            tw = summary["t_winrate"]
            self.log(
                f"  {summary['rounds']} valid rounds: T {tw['value']} {tw['ci']}, "
                f"A-plants {summary['site_split_a']['value']} {summary['site_split_a']['ci']}"
            )
            if errors:
                report["schema_errors"] = errors[:50]
            new_valid = sum(
                valid_round(r, self.per_team)
                for r in data["rounds"]
                if r["run_id"].startswith(name)
            )
            if new_valid == 0:
                stop_reason, ok = f"batch {name} produced no valid rounds", False
                break
            stop, stop_reason = stop_decision(summary, self.min_rounds, self.max_rounds)
            if stop:
                break
        report.update(
            ok=ok and not report.get("schema_errors"),
            stop_reason=stop_reason,
            batches=groups,
            summary=summary,
            demos=sorted(str(p.relative_to(self.out)) for p in self.out.rglob("*.dem")),
            wall_s=round(time.time() - t0, 1),
        )
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    parser.add_argument("--source", choices=["map", "reference"], default="map")
    parser.add_argument("--rounds", type=int, default=None, help="max valid rounds")
    parser.add_argument("--servers", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--no-smoke", action="store_true")
    parser.add_argument(
        "--watch", action="store_true", help="1 server in real time, to join as spectator"
    )
    args = parser.parse_args(argv)
    cfg = load_config()
    bsp = resolve_bsp(cfg, args.map, args.source)
    if bsp is None:
        print(f"no .bsp for {args.map} (compile it, or use --source reference)", file=sys.stderr)
        return 1
    out = args.out or cfg.path("build_dir") / args.map / "sim"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    report = Simulation(cfg, args.map, bsp, out, args).run(args.smoke_only, args.no_smoke)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    (out / "simulation.json").write_text(text, encoding="utf-8")
    (cfg.path("build_dir") / args.map / "simulation.json").write_text(text, encoding="utf-8")
    print(f"simulate {args.map}: {'OK' if report['ok'] else 'FAILED'} ({report['stop_reason']}),"
          f" {report['wall_s']} s -> {out / 'simulation.json'}")  # fmt: skip
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    from mapforge.site.build import refresh_site  # lazy: avoids an import cycle

    code = main()
    refresh_site()
    sys.exit(code)
