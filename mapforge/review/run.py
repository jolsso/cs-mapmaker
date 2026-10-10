"""Review (pre-sim gate): deterministic checks, then a visual review of the renders by Claude.

Three ways to run the visual part; all use the same prompt, schema and pass rule:
  --emit             write build/<map>/review_prompt.md + review_schema.json and stop. The
                     Claude Code session (or a subagent it starts) reads the prompt and the
                     images and writes its JSON answer to build/<map>/review_answer.json.
  --answer [FILE]    read that answer, check it against the schema, decide pass/fail.
  --headless         call `claude -p` (unattended runs; needs `claude` on this machine).
Default (no flag) = review.executor in config (session -> --emit).

Reads build/<map>/validation.json and renders/index.json; writes build/<map>/review.json.
Exit 0 = pass (or prompt emitted), 1 = fail, 2 = could not review.
"""

from __future__ import annotations

import argparse
import hashlib
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


def _shown(path: Path, root: Path) -> str:
    """Path relative to the repo root when inside it (works from host and container)."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


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
        f"- {_shown(renders / i['file'], cfg.root)} — {i['purpose']}" for i in index["images"]
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
        env=env, cwd=add_dir,
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


REVIEW_INPUTS = ("validation.json", "renders/index.json")


def input_hashes(build: Path) -> dict[str, str | None]:
    """sha256 of the files a review was made from; a later mismatch means the review is stale."""
    out: dict[str, str | None] = {}
    for name in REVIEW_INPUTS:
        p = build / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    return out


def check_answer(answer: Any) -> dict[str, Any]:
    """Validate a review answer against SCHEMA (by hand: no jsonschema dependency)."""
    if not isinstance(answer, dict) or not isinstance(answer.get("summary"), str):
        raise RuntimeError("answer must be an object with a string 'summary'")
    findings = answer.get("findings")
    if not isinstance(findings, list):
        raise RuntimeError("answer.findings must be a list")
    for i, f in enumerate(findings):
        keys = ("severity", "where", "what", "image")
        missing = [k for k in keys if not isinstance(f.get(k), str)]
        if missing:
            raise RuntimeError(f"finding {i} lacks string field(s): {missing}")
        if f["severity"] not in SEVERITIES:
            raise RuntimeError(f"finding {i}: severity must be one of {SEVERITIES}")
    return answer


def review_map(
    cfg: Config,
    map_name: str,
    mode: str = "emit",
    model: str | None = None,
    answer_path: Path | None = None,
) -> dict[str, Any]:
    """mode: 'emit' (write prompt), 'answer' (score an answer file) or 'headless' (claude -p)."""
    build = cfg.path("build_dir") / map_name
    renders = build / "renders"
    vpath, ipath = build / "validation.json", renders / "index.json"
    for p in (vpath, ipath):
        if not p.is_file():
            raise RuntimeError(f"missing {p}: run `./mf validate` and `./mf render` first")
    validation = json.loads(vpath.read_text(encoding="utf-8"))
    index = json.loads(ipath.read_text(encoding="utf-8"))
    t0 = time.monotonic()
    result: dict[str, Any] = {"map": map_name, "stage": "deterministic", "executor": None}

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
            ],
        )
    else:
        result["stage"] = "visual"
        prompt = build_prompt(cfg, map_name, validation, index, renders)
        (build / "review_prompt.md").write_text(prompt, encoding="utf-8")
        (build / "review_schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
        if mode == "emit":
            answer_at = _shown(build / "review_answer.json", cfg.root)
            result.update(
                passed=None,
                executor="session",
                summary=f"prompt written; answer to {answer_at}, then --answer",
                findings=[],
            )
        else:
            if mode == "answer":
                path = answer_path or build / "review_answer.json"
                answer = check_answer(json.loads(path.read_text(encoding="utf-8")))
                result["executor"] = "session"
            elif mode == "headless":
                rcfg = cfg.data.get("review", {})
                got = call_claude(
                    prompt, cfg.root, model, int(rcfg.get("timeout_s", 600)),
                    rcfg.get("auth", "login"),
                )  # fmt: skip
                answer = check_answer(got["answer"])
                result.update(executor="headless", claude=got["envelope"])
            else:
                raise RuntimeError(f"unknown review mode {mode!r}")
            findings = answer["findings"]
            result.update(
                passed=not any(f["severity"] in BLOCKING for f in findings),
                summary=answer["summary"],
                findings=findings,
            )
    result["seconds"] = round(time.monotonic() - t0, 1)
    result["inputs"] = input_hashes(build)
    if result["passed"] is not None:
        (build / "review.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--emit", action="store_true", help="write prompt + schema and stop")
    group.add_argument(
        "--answer", nargs="?", const="", metavar="FILE",
        help="score an answer (default build/<map>/review_answer.json)",
    )  # fmt: skip
    group.add_argument("--headless", action="store_true", help="call `claude -p`")
    parser.add_argument("--model", default=None, help="claude model alias (headless only)")
    args = parser.parse_args(argv)
    cfg = load_config()
    rcfg = cfg.data.get("review", {})
    if args.answer is not None:
        mode = "answer"
    elif args.headless:
        mode = "headless"
    elif args.emit:
        mode = "emit"
    else:
        mode = "headless" if rcfg.get("executor") == "headless" else "emit"
    try:
        r = review_map(
            cfg, args.map, mode, args.model or rcfg.get("model"),
            Path(args.answer) if args.answer else None,
        )  # fmt: skip
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"review failed to run: {exc}", file=sys.stderr)
        return 2
    verdict = {True: "PASS", False: "FAIL", None: "PROMPT READY"}[r["passed"]]
    print(f"review {args.map}: {verdict} ({r['stage']}, {r['seconds']} s) - {r['summary']}")
    for f in r["findings"]:
        print(f"  [{f['severity']}] {f['where']}: {f['what']} ({f['image']})")
    return 0 if r["passed"] or r["passed"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
