"""Iteration directories runs/<map>/<NNN>/: the Decide input contract (ARCHITECTURE.md -> 8).

Everything an iteration was decided on is copied here, so it can be reproduced and audited:
layout.yaml, <map>.map + map.diff, compile/validation/review JSON, renders, stage.json.
"""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path
from typing import Any

from mapforge.config import Config
from mapforge.review.run import input_hashes


def runs_root(cfg: Config, map_name: str) -> Path:
    return cfg.root / cfg.data["paths"].get("runs_dir", "runs") / map_name


def iterations(cfg: Config, map_name: str) -> list[Path]:
    root = runs_root(cfg, map_name)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit())


def new_iteration(cfg: Config, map_name: str) -> Path:
    existing = iterations(cfg, map_name)
    n = int(existing[-1].name) + 1 if existing else 1
    path = runs_root(cfg, map_name) / f"{n:03d}"
    path.mkdir(parents=True)
    return path


def stage_of(build: Path) -> dict[str, Any]:
    """How far the fast/slow loop got for the current build, and what is next."""

    def load(name: str) -> dict | None:
        p = build / name
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    compile_, validation, review, metrics = (
        load("compile.json"), load("validation.json"), load("review.json"), load("metrics.json")
    )  # fmt: skip
    stage: dict[str, Any] = {
        "compile_ok": None if compile_ is None else compile_.get("ok"),
        "validate_ok": None if validation is None else validation.get("ok"),
        "review_passed": None if review is None else review.get("passed"),
        "metrics": metrics is not None,
    }
    if compile_ is not None and not compile_.get("ok"):
        stage.update(reached="compile", why="compile failed", next="fix")
    elif validation is None:
        stage.update(reached="none", why="not validated", next="validate")
    elif not validation["ok"]:
        stage.update(reached="validate", why="hard requirements fail", next="fix")
    elif review is None:
        stage.update(reached="validate", why="not reviewed", next="review")
    elif review.get("inputs") != input_hashes(build):
        stale = "review is stale: renders or validation changed since"
        stage.update(review_passed=None, reached="validate", why=stale, next="review")
    elif not review.get("passed"):
        stage.update(reached="review", why="review found critical/major problems", next="fix")
    elif metrics is None:
        stage.update(reached="review", why="passed the fast loop", next="simulate")
    else:
        stage.update(reached="simulate", why="measured", next="improve or stop")
    return stage


def collect(cfg: Config, map_name: str, run_dir: Path) -> dict[str, Any]:
    """Copy the current build's inputs into run_dir; return a manifest of what is there."""
    build = cfg.path("build_dir") / map_name
    files: list[str] = []
    for name in ("compile.json", "validation.json", "review.json", "metrics.json"):
        if (build / name).is_file():
            shutil.copy2(build / name, run_dir / name)
            files.append(name)
    renders = build / "renders"
    if (renders / "index.json").is_file():
        shutil.copytree(renders, run_dir / "renders",
                        ignore=shutil.ignore_patterns("demo_*", "topdown_raw.png"))  # fmt: skip
        files += [f"renders/{p.name}" for p in sorted((run_dir / "renders").iterdir())]
    map_dir = cfg.path("maps_dir") / map_name
    if (map_dir / "layout.yaml").is_file():
        shutil.copy2(map_dir / "layout.yaml", run_dir / "layout.yaml")
        files.append("layout.yaml")
    src = map_dir / "src" / f"{map_name}.map"
    if src.is_file():
        shutil.copy2(src, run_dir / src.name)
        files.append(src.name)
        prev = [p / src.name for p in iterations(cfg, map_name) if p != run_dir]
        prev = [p for p in prev if p.is_file()]
        if prev:
            diff = difflib.unified_diff(
                prev[-1].read_text(encoding="utf-8").splitlines(keepends=True),
                src.read_text(encoding="utf-8").splitlines(keepends=True),
                fromfile=f"previous/{src.name}", tofile=f"current/{src.name}",
            )  # fmt: skip
            (run_dir / "map.diff").write_text("".join(diff), encoding="utf-8")
            files.append("map.diff")
    stage = stage_of(build)
    (run_dir / "stage.json").write_text(json.dumps(stage, indent=2), encoding="utf-8")
    files.append("stage.json")
    notes = [
        p / "NOTES.md"
        for p in iterations(cfg, map_name)
        if p != run_dir and (p / "NOTES.md").is_file()
    ][-3:]
    return {"run_dir": run_dir, "files": files, "stage": stage, "previous_notes": notes}
