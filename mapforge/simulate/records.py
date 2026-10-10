"""Tracker CSV files (docs/TRACKER_SPEC.md): schema check, loading, plant-site assignment."""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

TEAMS = {"T", "CT"}
EVENT_TYPES = {
    "kill",
    "damage",
    "bomb_plant",
    "bomb_defuse",
    "bomb_explode",
    "round_end",
    "first_contact",
}
REASONS = {"elimination", "bomb", "defuse", "time", "draw"}


def _team(v: str) -> str:
    if v not in TEAMS:
        raise ValueError(f"team {v!r}")
    return v


def _opt_team(v: str) -> str:
    if v and v not in TEAMS:
        raise ValueError(f"team {v!r}")
    return v


def _bit(v: str) -> int:
    if v not in ("0", "1"):
        raise ValueError(f"0/1 expected, got {v!r}")
    return int(v)


def _choice(options: set[str], allow_empty: bool = False) -> Callable[[str], str]:
    def check(v: str) -> str:
        if v not in options and not (allow_empty and v == ""):
            raise ValueError(f"{v!r} not in {sorted(options)}")
        return v

    return check


Schema = list[tuple[str, Callable[[str], Any]]]
POSITIONS: Schema = [
    ("run_id", str),
    ("round", int),
    ("t", float),
    ("player_id", int),
    ("team", _team),
    ("alive", _bit),
    ("x", float),
    ("y", float),
    ("z", float),
    ("yaw", float),
    ("pitch", float),
    ("hp", int),
    ("weapon", str),
]
EVENTS: Schema = [
    ("run_id", str),
    ("round", int),
    ("t", float),
    ("type", _choice(EVENT_TYPES)),
    ("actor_id", int),
    ("actor_team", _opt_team),
    ("target_id", int),
    ("target_team", _opt_team),
    ("ax", float),
    ("ay", float),
    ("az", float),
    ("tx", float),
    ("ty", float),
    ("tz", float),
    ("weapon", str),
    ("extra", str),
]
ROUNDS: Schema = [
    ("run_id", str),
    ("round", int),
    ("start_time", float),
    ("end_time", float),
    ("winner", _opt_team),
    ("reason", _choice(REASONS)),
    ("plant_site", str),
    ("t_alive_end", int),
    ("ct_alive_end", int),
    ("humans_on_team", int),
    ("t_players", int),
    ("ct_players", int),
]
SCHEMAS = {"positions.csv": POSITIONS, "events.csv": EVENTS, "rounds.csv": ROUNDS}


def read_csv(path: Path, schema: Schema, errors: list[str], max_errors: int = 20) -> list[dict]:
    """Typed rows; schema violations are appended to `errors` (the row is skipped)."""
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        want = [name for name, _ in schema]
        if header != want:
            errors.append(f"{path.name}: header {header} != {want}")
            return rows
        for line_no, raw in enumerate(reader, start=2):
            if len(raw) != len(schema):
                if len(errors) < max_errors:
                    errors.append(f"{path.name}:{line_no}: {len(raw)} columns, want {len(schema)}")
                continue
            try:
                rows.append({name: conv(v) for (name, conv), v in zip(schema, raw, strict=True)})
            except ValueError as e:
                if len(errors) < max_errors:
                    errors.append(f"{path.name}:{line_no}: {e}")
    return rows


def load_run(run_dir: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """All three files of one server run -> ({file stem: rows}, schema errors)."""
    errors: list[str] = []
    data: dict[str, list[dict]] = {}
    for name, schema in SCHEMAS.items():
        path = run_dir / name
        if not path.is_file():
            errors.append(f"{name}: missing")
            data[name[:-4]] = []
            continue
        data[name[:-4]] = read_csv(path, schema, errors)
    return data, errors


def valid_round(r: dict, bots_per_team: int) -> bool:
    """A round counts for metrics: it has a winner, no humans played, both teams were full."""
    return (
        r["winner"] in TEAMS
        and r["humans_on_team"] == 0
        and r["t_players"] >= bots_per_team
        and r["ct_players"] >= bots_per_team
    )


def site_of(point: np.ndarray, sites: list[list[tuple[np.ndarray, np.ndarray]]], labels: list[str]):
    """Label of the bomb site nearest to `point` (distance to its boxes)."""
    best, label = float("inf"), ""
    for boxes, lab in zip(sites, labels, strict=True):
        for lo, hi in boxes:
            d = float(np.linalg.norm(np.maximum(0, np.maximum(lo - point, point - hi))))
            if d < best:
                best, label = d, lab
    return label


def assign_plant_sites(data: dict[str, list[dict]], bsp: Any) -> None:
    """Fill empty rounds.plant_site from the bomb_plant position and the map's bomb sites."""
    from mapforge.validate.walk import bomb_sites, site_labels

    sites, labels = bomb_sites(bsp), site_labels(bsp)
    if not sites:
        return
    plants = {
        (e["run_id"], e["round"]): np.array([e["ax"], e["ay"], e["az"]])
        for e in data["events"]
        if e["type"] == "bomb_plant"
    }
    for r in data["rounds"]:
        key = (r["run_id"], r["round"])
        if key in plants and not r["plant_site"]:
            r["plant_site"] = site_of(plants[key], sites, labels)
