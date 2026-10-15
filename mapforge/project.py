"""A map project's state, set by the human under Input on the map page: open (the default) or
closed ("afsluttet": no new wishes, the loop does not run). maps/<map>/project.json."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATES = ("open", "closed")


def _file(maps_dir: Path, map_name: str) -> Path:
    return maps_dir / map_name / "project.json"


def load(maps_dir: Path, map_name: str) -> dict[str, Any]:
    try:
        data = json.loads(_file(maps_dir, map_name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {"state": data.get("state") if data.get("state") in STATES else "open",
            "changed": data.get("changed")}  # fmt: skip


def is_closed(maps_dir: Path, map_name: str) -> bool:
    return load(maps_dir, map_name)["state"] == "closed"


def set_state(maps_dir: Path, map_name: str, state: str) -> dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"state: one of {', '.join(STATES)}")
    if not (maps_dir / map_name).is_dir():
        raise ValueError(f"unknown map {map_name!r}")
    data = {"state": state, "changed": time.strftime("%Y-%m-%d %H:%M")}
    _file(maps_dir, map_name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def load_all(maps_dir: Path) -> dict[str, dict[str, Any]]:
    if not maps_dir.is_dir():
        return {}
    return {d.name: load(maps_dir, d.name) for d in sorted(maps_dir.iterdir()) if d.is_dir()}
