"""Analysis (phase 5): simulation CSV -> metrics.json, heatmaps, report.md, delta.

Input: a simulation dir (default build/<map>/sim/, from `./mf simulate`) with simulation.json;
the top-down base image from `./mf render` (build/<map>/renders/topdown_raw.png).
Output: <out>/metrics.json, <out>/report.md, <out>/heatmaps/*.png (default build/<map>/analysis/).
Delta: against --baseline <metrics.json>, else the newest history version of another .bsp that
has an analysis.

Usage: python -m mapforge.analyze.run --map de_forge01 [--sim DIR] [--out DIR] [--baseline FILE]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from mapforge.analyze.delta import compare
from mapforge.analyze.metrics import compute
from mapforge.config import Config, load_config
from mapforge.simulate.records import assign_plant_sites, load_run, valid_round

NAMES = {
    "t_winrate": "T-winrate",
    "site_split_a": "Andel plants på A",
    "first_contact_s": "Første kontakt (median, s)",
    "dead_zone_share": "Døde zoner (andel af gangbart areal)",
    "max_kill_cell_share": "Kill-koncentration (største celle)",
    "round_length_median_s": "Rundelængde (median, s)",
}


def local(cfg: Config, path: str) -> Path:
    """A path written inside the container (/work/...) as a path in this checkout."""
    p = Path(path)
    if p.is_file():
        return p
    parts = p.parts
    if "work" in parts:
        q = cfg.root.joinpath(*parts[parts.index("work") + 1 :])
        if q.is_file():
            return q
    return p


def load_simulation(sim_dir: Path) -> tuple[dict, dict[str, list[dict]], list[str]]:
    """simulation.json + the merged data of its counted batches (not the graph/smoke runs)."""
    sim = json.loads((sim_dir / "simulation.json").read_text(encoding="utf-8"))
    merged: dict[str, list[dict]] = {"positions": [], "events": [], "rounds": []}
    errors: list[str] = []
    for group in sim.get("batches") or []:
        for rounds_csv in sorted((sim_dir / group).rglob("rounds.csv")):
            data, errs = load_run(rounds_csv.parent)
            errors += errs
            for k in merged:
                merged[k] += data[k]
    return sim, merged, errors


def walkable_xy(cfg: Config, bsp: Any) -> np.ndarray:
    from mapforge.validate.checks import spawn_origins
    from mapforge.validate.walk import build_walk_graph

    w = cfg.data["validate"]["walk"]
    origins, _ = spawn_origins(bsp.entities)
    graph = build_walk_graph(
        bsp, origins, cell=16, z_step=float(w["z_step"]), max_step=float(w["max_step"]),
        max_drop=float(w["max_drop"]), jump_height=float(w["jump_height"]),
    )  # fmt: skip
    return graph.standing()[:, :2]


def heatmaps(
    cfg: Config, map_name: str, bsp: Any, data: dict, keys: set, out: Path, sigma: float
) -> list[dict]:
    """PNG heatmaps on the raw top-down render; [] if the map has not been rendered."""
    from mapforge.render.overlay import heatmap
    from mapforge.render.topdown import TopDownView, annotate

    renders = cfg.path("build_dir") / map_name / "renders"
    index_file = renders / "index.json"
    if not index_file.is_file():
        return []
    base = json.loads(index_file.read_text(encoding="utf-8"))["base_for_overlays"]
    (x0, y0, x1, y1), (w, h) = base["view"]["world_rect"], base["view"]["size"]
    view = TopDownView(x0, y0, x1, y1, w, h)
    img = Image.open(renders / base["file"]).convert("RGB")
    inrun = lambda r: (r["run_id"], r["round"]) in keys  # noqa: E731
    pos = [p for p in data["positions"] if p["alive"] and inrun(p)]
    ev = [e for e in data["events"] if inrun(e)]
    first: dict[tuple, dict] = {}
    for e in ev:
        if e["type"] == "first_contact":
            first.setdefault((e["run_id"], e["round"]), e)
    layers = [
        ("traffic_t.png", "Trafik T (positioner)", [(p["x"], p["y"]) for p in pos if p["team"] == "T"]),
        ("traffic_ct.png", "Trafik CT (positioner)", [(p["x"], p["y"]) for p in pos if p["team"] == "CT"]),
        ("kills.png", "Kills (hvor dræberen stod)", [(e["ax"], e["ay"]) for e in ev if e["type"] == "kill" and e["actor_team"]]),
        ("deaths.png", "Deaths (hvor offeret døde)", [(e["tx"], e["ty"]) for e in ev if e["type"] == "kill"]),
        ("first_contact.png", "Første kontakt (begge spillere)",
         [(e["ax"], e["ay"]) for e in first.values()] + [(e["tx"], e["ty"]) for e in first.values()]),
    ]  # fmt: skip
    hdir = out / "heatmaps"
    hdir.mkdir(parents=True, exist_ok=True)
    made = []
    for name, title, pts in layers:
        xy = np.array(pts, dtype=np.float64).reshape(-1, 2)
        im = heatmap(img, view, xy, sigma_units=sigma) if len(xy) else img
        annotate(np.asarray(im), view, bsp, f"{map_name} - {title} (n={len(xy)})").save(hdir / name)
        made.append({"file": f"heatmaps/{name}", "purpose": title, "n": len(xy)})
    return made


def draw_dead_zones(cfg: Config, map_name: str, bsp: Any, cells: list, size: float, out: Path):
    from mapforge.render.topdown import TopDownView, annotate

    renders = cfg.path("build_dir") / map_name / "renders"
    if not (renders / "index.json").is_file():
        return None
    base = json.loads((renders / "index.json").read_text(encoding="utf-8"))["base_for_overlays"]
    (x0, y0, x1, y1), (w, h) = base["view"]["world_rect"], base["view"]["size"]
    view = TopDownView(x0, y0, x1, y1, w, h)
    im = Image.open(renders / base["file"]).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    for cx, cy in cells:
        (ax, ay), (bx, by) = view.to_px(
            np.array([[cx - size / 2, cy + size / 2], [cx + size / 2, cy - size / 2]])
        )
        d.rectangle([ax, ay, bx, by], fill=(230, 30, 30, 140))
    name = "heatmaps/dead_zones.png"
    annotate(np.asarray(im), view, bsp, f"{map_name} - døde zoner (rød, n={len(cells)})").save(
        out / name
    )
    return {
        "file": name,
        "purpose": "Døde zoner: gangbare celler med ~ingen trafik",
        "n": len(cells),
    }


def find_baseline(cfg: Config, map_name: str, bsp_sha: str) -> Path | None:
    from mapforge.history import versions

    for v in reversed(versions(cfg, map_name)):
        meta = json.loads((v / "meta.json").read_text(encoding="utf-8"))
        if meta.get("bsp_sha256") != bsp_sha and (v / "analysis" / "metrics.json").is_file():
            return v / "analysis" / "metrics.json"
    return None


def report_md(m: dict, delta: dict | None) -> str:
    lines = [f"# Analyse – {m['map']}", ""]
    enough = "nok" if m["enough_rounds"] else f"for få (FITNESS kræver {m['min_rounds']})"
    lines += [f"{m['rounds']} gyldige bot-runder ({enough}). Score {m['score']} (0 = alle mål ramt)."
              + (" Alle mål ramt." if m["targets_met"] else ""), ""]  # fmt: skip
    lines += ["| Metrik | Værdi | 95 %-interval | Mål | Afstand | n |", "|---|---|---|---|---|---|"]
    for k, v in m["metrics"].items():
        ci = "–" if v["ci"][0] is None else f"{v['ci'][0]}–{v['ci'][1]}"
        lines.append(
            f"| {NAMES.get(k, k)} | {v['value']} | {ci} | {v['target']} | {v['distance']} | {v['n']} |"
        )
    lines += ["", f"Rundeårsager: {m['round_reasons']}. Plants: {m['plants']['by_site']}."
              f" Kills pr. runde: {m['kills']['per_round']}.", ""]  # fmt: skip
    if m["kills"]["top_cells"]:
        top = ", ".join(
            f"({c['x']:.0f}, {c['y']:.0f}) {c['share']:.0%}" for c in m["kills"]["top_cells"][:3]
        )
        lines.append(
            f"Flest kills (offerets position, celler à {m['cells']['kill']} units): {top}."
        )
    lines.append(f"Døde zoner: {m['dead_zones']['count']} af {m['dead_zones']['walkable_cells']} gangbare "
                 f"celler à {m['cells']['dead_zone']} units (under {m['dead_zones']['threshold']} samples).")  # fmt: skip
    if delta:
        lines += ["", f"## Delta mod {delta['baseline']}", "",
                  f"Samlet: **{delta['verdict']}** (score {delta['score']['before']} → {delta['score']['after']}).", "",
                  "| Metrik | Før | Efter | Ændring | Vurdering |", "|---|---|---|---|---|"]  # fmt: skip
        for k, v in delta["metrics"].items():
            lines.append(
                f"| {NAMES.get(k, k)} | {v['before']} | {v['after']} | {v['change']:+} | {v['verdict']} |"
            )
    lines += ["", "Heatmaps: " + ", ".join(h["file"] for h in m["heatmaps"]) if m["heatmaps"] else
              "Ingen heatmaps (render mappet først).", "",
              "Goodhart: tallene beskriver, hvordan YaPB-bots spiller – ikke mennesker."]  # fmt: skip
    return "\n".join(lines) + "\n"


def analyze(cfg: Config, map_name: str, sim_dir: Path, out: Path, baseline: Path | None) -> dict:
    from mapforge.bsp.reader import read_bsp
    from mapforge.decide.policy import load_fitness

    acfg = cfg.data["analyze"]
    sim, data, errors = load_simulation(sim_dir)
    bsp = read_bsp(local(cfg, sim["bsp"]))
    assign_plant_sites(data, bsp, acfg.get("site_names", {}).get(map_name))
    per_team = int(sim.get("bots_per_team", cfg.data["simulate"]["bots_per_team"]))
    valid = [r for r in data["rounds"] if valid_round(r, per_team)]
    keys = {(r["run_id"], r["round"]) for r in valid}
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    fitness = load_fitness(cfg.root)
    walk = walkable_xy(cfg, bsp)
    m: dict[str, Any] = {"map": map_name, "bsp_sha256": sim.get("bsp_sha256"), "simulation": {
        k: sim.get(k) for k in ("image", "timescale", "servers", "bots_per_team", "stop_reason", "wall_s")}}  # fmt: skip
    m |= compute(data, valid, walk, fitness, acfg, float(cfg.data["simulate"]["confidence"]))
    m["cells"] = {"dead_zone": acfg["dead_zone_cell"], "kill": acfg["kill_cell"]}
    m["schema_errors"] = errors[:50]
    m["rounds_logged"] = len(data["rounds"])
    m["heatmaps"] = heatmaps(cfg, map_name, bsp, data, keys, out, float(acfg["heat_sigma"]))
    dz = draw_dead_zones(
        cfg, map_name, bsp, m["dead_zones"]["cells"], float(acfg["dead_zone_cell"]), out
    )
    if dz:
        m["heatmaps"].append(dz)
    base_file = baseline or find_baseline(cfg, map_name, sim.get("bsp_sha256", ""))
    delta = None
    if base_file and base_file.is_file():
        delta = compare(m, json.loads(base_file.read_text(encoding="utf-8")))
        delta["baseline"] = (
            base_file.relative_to(cfg.root).as_posix()
            if base_file.is_relative_to(cfg.root)
            else str(base_file)
        )
    m["delta"] = delta
    (out / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "report.md").write_text(report_md(m, delta), encoding="utf-8")
    return m


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    parser.add_argument("--sim", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None)
    args = parser.parse_args(argv)
    cfg = load_config()
    build = cfg.path("build_dir") / args.map
    sim_dir = args.sim or build / "sim"
    if not (sim_dir / "simulation.json").is_file():
        print(f"no simulation in {sim_dir} (run ./mf simulate MAP={args.map})", file=sys.stderr)
        return 1
    out = args.out or build / "analysis"
    m = analyze(cfg, args.map, sim_dir, out, args.baseline)
    if args.out is None:
        from mapforge.history import snapshot

        snapshot(cfg, args.map)
    print(f"analyze {args.map}: {m['rounds']} rounds, score {m['score']}, "
          f"targets met: {m['targets_met']} -> {out / 'report.md'}")  # fmt: skip
    return 0


if __name__ == "__main__":
    from mapforge.site.build import refresh_site  # lazy: avoids an import cycle

    code = main()
    refresh_site()
    sys.exit(code)
