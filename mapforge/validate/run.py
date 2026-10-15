"""Validate a map: compile result, .map geometry, engine limits, entities, corridors.

Usage: python -m mapforge.validate.run --map test_box [--profile fast] [--no-compile]
Writes build/<map>/validation.json; exits 1 if any finding is an error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from mapforge.bsp.reader import read_bsp
from mapforge.compile.run import CompileError, compile_map
from mapforge.config import Config, deep_merge, load_config
from mapforge.mapfile.parser import MapParseError, read_map
from mapforge.refmaps import extract_archives, find_reference_bsp, reference_dirs
from mapforge.validate import checks
from mapforge.validate.checks import ERROR, Finding
from mapforge.validate.timings import route_timings
from mapforge.validate.walk import build_walk_graph


def map_rules(cfg: Config, map_name: str) -> dict[str, Any]:
    rules = cfg.data["validate"]["rules"]
    override = cfg.path("maps_dir") / map_name / "validate.yaml"
    if override.is_file():
        rules = deep_merge(rules, (yaml.safe_load(override.read_text()) or {}).get("rules", {}))
    return rules


def validate_map(cfg: Config, map_name: str, reference_bsp: Path | None = None) -> dict[str, Any]:
    """Validate build/<map>/ (compile output + .map), or only a reference .bsp if given."""
    vcfg = cfg.data["validate"]
    out_dir = cfg.path("build_dir") / map_name
    src = cfg.path("maps_dir") / map_name / "src" / f"{map_name}.map"
    findings: list[Finding] = []
    stats: dict[str, Any] = {}

    compile_json = out_dir / "compile.json"
    report = None
    mapfile = None
    if reference_bsp is not None:
        # Reference map: only the compiled .bsp exists (no source, no compile.json).
        bsp_path = reference_bsp
        bsp = read_bsp(bsp_path)
    else:
        report = json.loads(compile_json.read_text()) if compile_json.is_file() else None
        findings += checks.check_compile(report)
        try:
            mapfile = read_map(src)
        except (OSError, MapParseError) as exc:
            findings.append(Finding("map_parse", ERROR, f"Cannot read {src.name}: {exc}", "map"))
        if mapfile is not None:
            findings += checks.check_geometry(
                mapfile, int(vcfg["grid"]), float(vcfg["world_bounds"])
            )
            stats["brushes"] = len(mapfile.brushes())
            from mapforge.wad.repeat import findings as repeat_findings

            findings += [Finding(d["rule"], d["severity"], d["message"], "map")
                         for d in repeat_findings(mapfile, cfg)]  # fmt: skip
        bsp_path = out_dir / f"{map_name}.bsp"
        bsp = read_bsp(bsp_path) if report and report.get("ok") and bsp_path.is_file() else None
    if bsp is not None:
        limit_findings, usage = checks.check_limits(
            bsp,
            vcfg["engine_limits"],
            report,
            vcfg.get("compiler_table_rows", []),
            float(vcfg["limit_error_pct"]),
            float(vcfg["limit_warn_pct"]),
            # Reference maps are known to work; headroom is our policy for our own maps.
            policy_severity=checks.WARNING if reference_bsp is not None else ERROR,
        )
        findings += limit_findings
        stats["limits"] = usage
        wcfg = vcfg["walk"]
        origins, teams = checks.spawn_origins(bsp.entities)
        graph = build_walk_graph(
            bsp,
            origins,
            cell=float(wcfg["cell"]),
            z_step=float(wcfg["z_step"]),
            max_step=float(wcfg["max_step"]),
            max_drop=float(wcfg["max_drop"]),
            jump_height=float(wcfg.get("jump_height", 54)),
            crouch=bool(wcfg.get("crouch", True)),
        )
        reach_findings, stats["reachability"] = checks.check_reachability(bsp, graph, teams)
        findings += reach_findings
        stats["timings"] = route_timings(bsp, graph, teams)
        findings += checks.check_timings(
            stats["timings"],
            vcfg["timings"],
            checks.INFO if reference_bsp is not None else checks.WARNING,
        )
        from mapforge.validate.design import design_findings, design_stats

        layout_file = cfg.path("maps_dir") / map_name / "layout.yaml"
        layout = (
            yaml.safe_load(layout_file.read_text(encoding="utf-8"))
            if reference_bsp is None and layout_file.is_file()
            else None
        )
        # design rules need a real de_ map: two teams' spawns and bomb sites
        if (
            checks.map_type(map_name) == "de"
            and {"T", "CT"} <= set(teams)
            and not vcfg["design"].get("off")
        ):
            stats["design"] = design_stats(bsp, graph, origins, teams, layout)
            findings += design_findings(stats["design"], vcfg["design"], reference_bsp is not None)
        corridor_findings, stats["walkable"] = checks.check_corridors(
            graph,
            bsp,
            {**vcfg["corridors"], "max_step": wcfg["max_step"]},
            severity=checks.INFO if reference_bsp is not None else checks.WARNING,
        )
        findings += corridor_findings

    if bsp is not None:
        entities = bsp.entities
    elif mapfile is not None:
        entities = [e.properties for e in mapfile.entities]
    else:
        entities = []
    mtype = checks.map_type(map_name)
    entity_findings, stats["entities"] = checks.check_entities(
        entities, map_rules(cfg, map_name), mtype, bsp
    )
    findings += entity_findings

    errors = sum(f.severity == ERROR for f in findings)
    warnings = sum(f.severity == checks.WARNING for f in findings)
    result = {
        "map": map_name,
        "map_type": mtype or None,
        "source": "reference" if reference_bsp is not None else "map",
        "ok": errors == 0,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "info": len(findings) - errors - warnings,
        },
        "findings": [f.to_dict() for f in findings],
        "stats": stats,
        "inputs": {
            "map": None if reference_bsp is not None else src.as_posix(),
            "bsp": bsp_path.as_posix() if bsp else None,
            "compile_json": compile_json.as_posix() if report else None,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def print_summary(result: dict[str, Any], path: Path) -> None:
    s = result["summary"]
    status = "OK" if result["ok"] else "FAILED"
    print(f"validate {result['map']}: {status} ({s['errors']} errors, {s['warnings']} warnings)")
    for f in result["findings"]:
        loc = f" @ {f['location']}" if "location" in f else ""
        line = f" (line {f['line']})" if "line" in f else ""
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}{loc}{line}")
    print(f"Wrote {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    parser.add_argument("--profile", default="fast")
    parser.add_argument("--no-compile", action="store_true", help="reuse build/<map>/ as is")
    parser.add_argument(
        "--source",
        choices=["map", "reference"],
        default="map",
        help="map: compile maps/<map>/ (default); reference: validate a third-party .bsp only",
    )
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.source == "reference":
        extract_archives(cfg)
        bsp = find_reference_bsp(cfg, args.map)
        if bsp is None:
            dirs = ", ".join(str(d) for d in reference_dirs(cfg)) or "(none found)"
            print(f"reference map {args.map}.bsp not found in: {dirs}", file=sys.stderr)
            return 1
        result = validate_map(cfg, args.map, reference_bsp=bsp)
        print_summary(result, cfg.path("build_dir") / args.map / "validation.json")
        return 0 if result["ok"] else 1
    if not args.no_compile:
        try:
            compile_map(cfg, args.map, args.profile)
        except CompileError as exc:
            print(f"compile failed: {exc}", file=sys.stderr)  # validation reports the details
    result = validate_map(cfg, args.map)
    print_summary(result, cfg.path("build_dir") / args.map / "validation.json")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    from mapforge.site.build import refresh_site  # lazy: avoids an import cycle

    code = main()
    refresh_site()  # keep the local website (build/site) current
    sys.exit(code)
