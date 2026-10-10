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
from mapforge.validate import checks
from mapforge.validate.checks import ERROR, Finding


def map_rules(cfg: Config, map_name: str) -> dict[str, Any]:
    rules = cfg.data["validate"]["rules"]
    override = cfg.path("maps_dir") / map_name / "validate.yaml"
    if override.is_file():
        rules = deep_merge(rules, (yaml.safe_load(override.read_text()) or {}).get("rules", {}))
    return rules


def validate_map(cfg: Config, map_name: str) -> dict[str, Any]:
    vcfg = cfg.data["validate"]
    out_dir = cfg.path("build_dir") / map_name
    src = cfg.path("maps_dir") / map_name / "src" / f"{map_name}.map"
    findings: list[Finding] = []
    stats: dict[str, Any] = {}

    compile_json = out_dir / "compile.json"
    report = json.loads(compile_json.read_text()) if compile_json.is_file() else None
    findings += checks.check_compile(report)

    mapfile = None
    try:
        mapfile = read_map(src)
    except (OSError, MapParseError) as exc:
        findings.append(Finding("map_parse", ERROR, f"Cannot read {src.name}: {exc}", "map"))
    if mapfile is not None:
        findings += checks.check_geometry(mapfile, int(vcfg["grid"]), float(vcfg["world_bounds"]))
        stats["brushes"] = len(mapfile.brushes())

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
        )
        findings += limit_findings
        stats["limits"] = usage
        corridor_findings, stats["walkable"] = checks.check_corridors(bsp, vcfg["corridors"])
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
    result = {
        "map": map_name,
        "map_type": mtype or None,
        "ok": errors == 0,
        "summary": {"errors": errors, "warnings": len(findings) - errors},
        "findings": [f.to_dict() for f in findings],
        "stats": stats,
        "inputs": {
            "map": src.as_posix(),
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
    args = parser.parse_args(argv)
    cfg = load_config()
    if not args.no_compile:
        try:
            compile_map(cfg, args.map, args.profile)
        except CompileError as exc:
            print(f"compile failed: {exc}", file=sys.stderr)  # validation reports the details
    result = validate_map(cfg, args.map)
    print_summary(result, cfg.path("build_dir") / args.map / "validation.json")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
