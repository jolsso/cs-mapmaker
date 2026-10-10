"""Version history per map: history/<map>/<NNN>/ with renders, validation, review, layout.

A new version is made when the compiled .bsp changes (sha256); rendering, validating or
reviewing the same .bsp again updates that version in place. The website shows the versions as
a thumbnail list (mapforge.site.build).

Usage: python -m mapforge.history --map de_forge01 [--note "..."]   # snapshot the current build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from mapforge.config import Config, load_config

COPY_FILES = ("validation.json", "review.json", "compile.json")


def history_root(cfg: Config, map_name: str) -> Path:
    return cfg.root / cfg.data["paths"].get("history_dir", "history") / map_name


def versions(cfg: Config, map_name: str) -> list[Path]:
    root = history_root(cfg, map_name)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit(root: Path) -> str | None:
    """HEAD commit without needing git (the container has none): read .git directly."""
    head = root / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            path = root / ".git" / ref[5:]
            if path.is_file():
                return path.read_text().strip()[:7]
            packed = root / ".git" / "packed-refs"
            for line in packed.read_text().splitlines() if packed.is_file() else []:
                if line.endswith(ref[5:]):
                    return line.split()[0][:7]
            return None
        return ref[:7]
    except OSError:
        return None


def bsp_of(cfg: Config, map_name: str) -> Path | None:
    """The .bsp the current build/<map>/ was made from (own map or reference map)."""
    build = cfg.path("build_dir") / map_name
    index = build / "renders" / "index.json"
    if index.is_file():
        bsp = Path(json.loads(index.read_text(encoding="utf-8")).get("bsp", ""))
        for candidate in (bsp, build / f"{map_name}.bsp"):
            if candidate.is_file():
                return candidate
            # index paths are container paths (/work/...); map them onto this checkout
            parts = candidate.parts
            if "build" in parts:
                local = cfg.root.joinpath(*parts[parts.index("build") :])
                if local.is_file():
                    return local
    own = build / f"{map_name}.bsp"
    return own if own.is_file() else None


def snapshot(cfg: Config, map_name: str, note: str | None = None) -> Path | None:
    """Record the current build of a map; returns the version dir (None if nothing to record)."""
    build = cfg.path("build_dir") / map_name
    renders = build / "renders"
    bsp = bsp_of(cfg, map_name)
    if bsp is None or not (renders / "index.json").is_file():
        return None
    sha = _sha(bsp)
    existing = versions(cfg, map_name)
    target = None
    for v in reversed(existing):
        meta = json.loads((v / "meta.json").read_text(encoding="utf-8"))
        if meta.get("bsp_sha256") == sha:
            target = v
            break
    if target is None:
        n = int(existing[-1].name) + 1 if existing else 1
        target = history_root(cfg, map_name) / f"{n:03d}"
        target.mkdir(parents=True)
        meta: dict[str, Any] = {
            "version": target.name,
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "bsp_sha256": sha,
            "git_commit": _git_commit(cfg.root),
            "notes": [],
        }
    else:
        meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
    # renders: replace with the current ones (same .bsp, possibly better cameras)
    if (target / "renders").exists():
        shutil.rmtree(target / "renders")
    shutil.copytree(renders, target / "renders", ignore=shutil.ignore_patterns("demo_*"))
    for name in COPY_FILES:
        if (build / name).is_file():
            shutil.copy2(build / name, target / name)
    layout = cfg.path("maps_dir") / map_name / "layout.yaml"
    if layout.is_file():
        shutil.copy2(layout, target / "layout.yaml")
    review = build / "review.json"
    if review.is_file():
        r = json.loads(review.read_text(encoding="utf-8"))
        meta["review_passed"] = r.get("passed")
        meta["review_summary"] = r.get("summary", "")
    validation = build / "validation.json"
    if validation.is_file():
        v = json.loads(validation.read_text(encoding="utf-8"))
        meta["validate_ok"] = v.get("ok")
        meta["timings"] = v.get("stats", {}).get("timings", [])
    meta["updated"] = time.strftime("%Y-%m-%d %H:%M")
    if note and note not in meta["notes"]:
        meta["notes"].append(note)
    (target / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    parser.add_argument("--note", default=None)
    args = parser.parse_args(argv)
    v = snapshot(load_config(), args.map, args.note)
    print(f"history {args.map}: {v if v else 'nothing to record (render first)'}")
    return 0 if v else 1


if __name__ == "__main__":
    sys.exit(main())
