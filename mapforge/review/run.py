"""Review (pre-sim gate): deterministic checks, then Claude looks at the renders.

Usage (on the host, where `claude` is installed and logged in):
    uv run python -m mapforge.review.run --map de_dust2 [--model sonnet] [--dry-run]

Reads build/<map>/validation.json and build/<map>/renders/index.json; writes
build/<map>/review.json. Exit 0 = pass, 1 = fail, 2 = could not review.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mapforge.config import Config, load_config

SEVERITIES = ("critical", "major", "minor")
BLOCKING = ("critical", "major")

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "where": {"type": "string"},
                    "what": {"type": "string"},
                    "image": {"type": "string"},
                },
                "required": ["severity", "where", "what", "image"],
            },
        },
    },
    "required": ["summary", "findings"],
}


def validation_summary(v: dict[str, Any]) -> str:
    """Compact, model-readable digest of validation.json (no huge arrays)."""
    lines = [f"ok={v['ok']} summary={v['summary']}"]
    for f in v["findings"]:
        if f["severity"] in ("error", "warning"):
            loc = f" @ {f['location']}" if "location" in f else ""
            lines.append(f"- [{f['severity']}] {f['rule']}: {f['message']}{loc}")
    reach = v.get("stats", {}).get("reachability", {}).get("sites", [])
    for s in reach:
        lines.append(
            f"- site {s['site']} centre {s['centre']}: spawns reaching {s['spawns_reaching']}"
        )
    ents = v.get("stats", {}).get("entities", {})
    if ents:
        lines.append(
            f"- entities: spawns {ents.get('spawns')}, bomb sites {ents.get('bomb_sites')}"
        )
    return "\n".join(lines)


def build_prompt(cfg: Config, map_name: str, validation: dict, index: dict, renders: Path) -> str:
    rcfg = cfg.root / "config" / "review"
    template = (rcfg / "prompt.md").read_text(encoding="utf-8")
    checklist = (rcfg / "checklist.md").read_text(encoding="utf-8")
    images = "\n".join(
        f"- {(renders / i['file']).resolve().as_posix()} — {i['purpose']}" for i in index["images"]
    )
    layout_path = cfg.path("maps_dir") / map_name / "layout.yaml"
    layout = (
        layout_path.read_text(encoding="utf-8")
        if layout_path.is_file()
        else "(ingen layout-spec – vurdér kun mod tjeklisten)"
    )
    b = index.get("brightness", {})
    extra = (
        f"\nLysstyrke: {len(b.get('dark_zones', []))} mørke zoner (luma < {b.get('dark_luma')})."
    )
    if index.get("missing_textures"):
        extra += f"\nManglende teksturer (vises som checkerboard): {index['missing_textures']}"
    return template.format(
        map=map_name,
        images=images,
        validation=validation_summary(validation) + extra,
        layout=layout,
        checklist=checklist,
    )


def call_claude(
    prompt: str, add_dir: Path, model: str | None, timeout: int, auth: str = "login"
) -> dict[str, Any]:
    exe = shutil.which("claude")
    if exe is None:
        raise RuntimeError("`claude` not found: run the review on the host, not in the container")
    cmd = [
        exe, "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
        "--allowedTools", "Read", "--add-dir", str(add_dir), "--no-session-persistence",
    ]  # fmt: skip
    if model:
        cmd += ["--model", model]
    env = dict(os.environ)
    if auth == "login":
        # An ANTHROPIC_API_KEY in the environment takes precedence over the claude.ai login;
        # drop it for this call only (the user's environment is not changed).
        env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        env=env,
    )  # fmt: skip
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"claude exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        ) from None
    if proc.returncode != 0 or envelope.get("is_error"):
        raise RuntimeError(f"claude error: {envelope.get('result')}")
    answer = envelope.get("structured_output")
    if answer is None:  # fall back to the text result
        answer = json.loads(envelope.get("result", "{}"))
    return {"answer": answer, "envelope": {k: envelope.get(k) for k in
            ("model", "total_cost_usd", "duration_ms", "num_turns", "session_id")}}  # fmt: skip


def review_map(cfg: Config, map_name: str, model: str | None, dry_run: bool) -> dict[str, Any]:
    build = cfg.path("build_dir") / map_name
    renders = build / "renders"
    vpath, ipath = build / "validation.json", renders / "index.json"
    for p in (vpath, ipath):
        if not p.is_file():
            raise RuntimeError(f"missing {p}: run `./mf validate` and `./mf render` first")
    validation = json.loads(vpath.read_text(encoding="utf-8"))
    index = json.loads(ipath.read_text(encoding="utf-8"))
    t0 = time.monotonic()
    result: dict[str, Any] = {"map": map_name, "stage": "deterministic"}

    if not validation["ok"]:
        errors = [f for f in validation["findings"] if f["severity"] == "error"]
        result.update(
            passed=False,
            summary=f"Validation has {len(errors)} error(s); visual review skipped.",
            findings=[
                {
                    "severity": "critical",
                    "where": str(f.get("location", "-")),
                    "what": f"{f['rule']}: {f['message']}",
                    "image": "validation.json",
                }
                for f in errors
            ],  # fmt: skip
        )
    else:
        prompt = build_prompt(cfg, map_name, validation, index, renders)
        (build / "review_prompt.md").write_text(prompt, encoding="utf-8")
        result["stage"] = "visual"
        if dry_run:
            result.update(passed=None, summary="dry run: prompt written, Claude not called",
                          findings=[])  # fmt: skip
        else:
            timeout = int(cfg.data.get("review", {}).get("timeout_s", 600))
            auth = cfg.data.get("review", {}).get("auth", "login")
            got = call_claude(prompt, renders.resolve(), model, timeout, auth)
            answer = got["answer"]
            findings = [f for f in answer.get("findings", []) if f.get("severity") in SEVERITIES]
            result.update(
                passed=not any(f["severity"] in BLOCKING for f in findings),
                summary=answer.get("summary", ""),
                findings=findings,
                claude=got["envelope"],
            )
    result["seconds"] = round(time.monotonic() - t0, 1)
    (build / "review.json").write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                       encoding="utf-8")  # fmt: skip
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    parser.add_argument("--model", default=None, help="claude model alias, e.g. sonnet / opus")
    parser.add_argument("--dry-run", action="store_true", help="write the prompt, skip Claude")
    args = parser.parse_args(argv)
    cfg = load_config()
    try:
        r = review_map(cfg, args.map, args.model or cfg.data.get("review", {}).get("model"),
                       args.dry_run)  # fmt: skip
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"review failed to run: {exc}", file=sys.stderr)
        return 2
    verdict = {True: "PASS", False: "FAIL", None: "DRY RUN"}[r["passed"]]
    print(f"review {args.map}: {verdict} ({r['stage']}, {r['seconds']} s) – {r['summary']}")
    for f in r["findings"]:
        print(f"  [{f['severity']}] {f['where']}: {f['what']} ({f['image']})")
    return 0 if r["passed"] or r["passed"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
