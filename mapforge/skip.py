"""Skip the current loop iteration: maps/<map>/skip.json, written by the live API (the map page's
"Skip" button), acted on and deleted by the loop at its next step or simulation batch.

It lives in maps/ because that is the live container's only writable mount (like project.json).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def path_of(maps_dir: Path, map_name: str) -> Path:
    return maps_dir / map_name / "skip.json"


def request(maps_dir: Path, map_name: str, reason: str = "") -> dict[str, Any]:
    req = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": str(reason or "")[:300]}
    p = path_of(maps_dir, map_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(req) + "\n", encoding="utf-8")
    return req


def pending(maps_dir: Path, map_name: str) -> dict[str, Any] | None:
    p = path_of(maps_dir, map_name)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear(maps_dir: Path, map_name: str) -> None:
    path_of(maps_dir, map_name).unlink(missing_ok=True)
