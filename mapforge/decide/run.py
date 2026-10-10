"""Decide (step 8): collect an iteration, emit the prompt, check the returned plan.

Usage:
  python -m mapforge.decide.run --map de_dust2 --emit      # new runs/<map>/<NNN>/ + prompt
  python -m mapforge.decide.run --map de_dust2 --answer    # check plan.json in the latest run

The Claude Code session (or a subagent) reads <run>/decide_prompt.md and writes plan.json and
NOTES.md. --answer checks the plan against config/fitness.yaml (mapforge.decide.policy) and
writes <run>/decision.json. Nothing is applied here: that is the orchestrator's job (phase 6).
Exit 0 = plan accepted as is, 1 = changes rejected / plan invalid, 2 = could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from mapforge.config import Config, load_config
from mapforge.decide.policy import PLAN_SCHEMA, check_plan, load_fitness
from mapforge.runs import collect, iterations, new_iteration


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def toolbox_text(fitness: dict[str, Any]) -> str:
    lines = []
    for name, spec in fitness["allowed_changes"].items():
        limits = {k: v for k, v in spec.items() if k not in ("description", "params")}
        extra = f" – grænser: {limits}" if limits else ""
        lines.append(f"- `{name}`: {spec['description']}; params {spec['params']}{extra}")
    locked = yaml.safe_dump(fitness.get("locked", {}), allow_unicode=True, sort_keys=False)
    return "\n".join(lines) + f"\n\nLåste beslutninger (config/fitness.yaml):\n```yaml\n{locked}```"


def emit(cfg: Config, map_name: str) -> Path:
    run_dir = new_iteration(cfg, map_name)
    manifest = collect(cfg, map_name, run_dir)
    root = cfg.root
    rel_run = _rel(run_dir, root)
    files = "\n".join(f"- {rel_run}/{f}" for f in manifest["files"])
    notes = ", ".join(_rel(p, root) for p in reversed(manifest["previous_notes"])) or "(ingen)"
    template = (root / "config" / "decide" / "prompt.md").read_text(encoding="utf-8")
    prompt = template.format(
        map=map_name,
        run_dir=rel_run,
        stage=json.dumps(manifest["stage"], indent=2, ensure_ascii=False),
        files=files,
        notes=notes,
        toolbox=toolbox_text(load_fitness(root)),
    )
    (run_dir / "decide_prompt.md").write_text(prompt, encoding="utf-8")
    (run_dir / "plan_schema.json").write_text(json.dumps(PLAN_SCHEMA, indent=2), encoding="utf-8")
    return run_dir


def answer(cfg: Config, run_dir: Path, phase: float) -> dict[str, Any]:
    plan_path = run_dir / "plan.json"
    if not plan_path.is_file():
        raise RuntimeError(f"no plan.json in {run_dir}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    verdict = check_plan(plan, load_fitness(cfg.root), phase)
    decision = {
        **verdict.to_dict(),
        "escalate": bool(plan.get("escalate")),
        "escalation_reason": plan.get("escalation_reason", ""),
        "notes_present": (run_dir / "NOTES.md").is_file(),
        "applied": False,  # dry run until the orchestrator (phase 6) applies accepted changes
    }
    if not decision["notes_present"]:
        decision["errors"] = [*decision["errors"], "NOTES.md missing"]
        decision["ok"] = False
    (run_dir / "decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False),
                                           encoding="utf-8")  # fmt: skip
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--emit", action="store_true")
    group.add_argument("--answer", nargs="?", const="", metavar="RUN_DIR",
                       help="default: the latest runs/<map>/<NNN>/")  # fmt: skip
    args = parser.parse_args(argv)
    cfg = load_config()
    phase = float(cfg.data.get("decide", {}).get("phase", 3))
    try:
        if args.emit:
            run_dir = emit(cfg, args.map)
            print(f"decide {args.map}: prompt ready in {_rel(run_dir, cfg.root)}/decide_prompt.md "
                  f"-> write plan.json + NOTES.md there, then --answer")  # fmt: skip
            return 0
        runs = iterations(cfg, args.map)
        run_dir = Path(args.answer) if args.answer else (runs[-1] if runs else None)
        if run_dir is None:
            raise RuntimeError(f"no runs for {args.map}; use --emit first")
        d = answer(cfg, run_dir, phase)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"decide failed to run: {exc}", file=sys.stderr)
        return 2
    status = "ACCEPTED" if d["ok"] else "REJECTED PARTS"
    esc = f" · ESCALATE: {d['escalation_reason']}" if d["escalate"] else ""
    print(f"decide {args.map}: {status} – {len(d['accepted'])} accepted, "
          f"{len(d['rejected'])} rejected{esc}")  # fmt: skip
    for r in d["rejected"]:
        print(f"  rejected {r.get('type')}: {r['reason']}")
    for e in d["errors"]:
        print(f"  error: {e}")
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    from mapforge.site.build import refresh_site  # lazy: avoids an import cycle

    code = main()
    refresh_site()  # keep the local website (build/site) current
    sys.exit(code)
