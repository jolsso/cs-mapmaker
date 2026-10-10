"""Parse compile.log (+ .lin pointfile) into the structured compile.json."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

STEP_RESULT = re.compile(r"^\[(\w+)\] exit=(-?\d+) time=([\d.]+)s$", re.MULTILINE)
WARNING = re.compile(r"^Warning:\s*(.*)$", re.MULTILINE)
ERROR = re.compile(r"^(?:\w+: )?Error:\s*(.*)$", re.MULTILINE)
LEAK_HULL = re.compile(r"=== LEAK in hull (\d+) ===")
LEAK_ENTITY = re.compile(
    r"^Entity (\S+) at \(\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)", re.MULTILINE
)
TABLE_HEADER = "Object names  Objects/Maxobjs  Memory / Maxmem  Fullness"
TABLE_ROW = re.compile(
    r"^(\*?\s?\w+)\s+(\d+|\[variable\])(?:/(\d+))?\s+(\d+)/(\d+)\s+\(\s*([\d.]+)%\)"
)
TEXTURES_REFERENCED = re.compile(r"^(\d+) textures referenced", re.MULTILINE)
WADS_REQUIRED = re.compile(r"^(\d+) wad files required to run the map", re.MULTILINE)


def _vec(parts: list[str]) -> list[float]:
    return [float(p) for p in parts]


def parse_lin(path: Path) -> list[list[float]]:
    """A .lin file is a polyline of 'x y z - x y z' segments; return its points in order."""
    points: list[list[float]] = []
    for row in path.read_text().splitlines():
        if " - " not in row:
            continue
        a, b = row.split(" - ")
        for p in (_vec(a.split()), _vec(b.split())):
            if not points or points[-1] != p:
                points.append(p)
    return points


def parse_limits(text: str) -> list[dict[str, Any]]:
    """Rows of the last 'Object names ...' table the compiler printed."""
    start = text.rfind(TABLE_HEADER)
    if start < 0:
        return []
    rows = []
    for row in text[start:].splitlines()[2:]:
        m = TABLE_ROW.match(row.strip())
        if not m:
            break
        name, used, max_count, mem, max_mem, fullness = m.groups()
        rows.append(
            {
                "name": name.lstrip("* ").strip(),
                "count": None if used == "[variable]" else int(used),
                "max": int(max_count) if max_count else None,
                "memory": int(mem),
                "max_memory": int(max_mem),
                "fullness_pct": float(fullness),
            }
        )
    return rows


def _messages(pattern: re.Pattern[str], text: str) -> list[str]:
    """Message text; an empty 'Error:' takes the next non-empty line as its message."""
    out = []
    for m in pattern.finditer(text):
        msg = m.group(1).strip()
        if not msg:
            rest = text[m.end() :].lstrip("\n").splitlines()
            msg = rest[0].strip() if rest else ""
        if msg not in out:
            out.append(msg)
    return out


def parse_compile_log(text: str, base: Path) -> dict[str, Any]:
    """Structure the combined compile.log for map files at `base` (path without suffix)."""
    steps = [
        {"step": s, "exit_code": int(code), "seconds": float(sec)}
        for s, code, sec in STEP_RESULT.findall(text)
    ]
    leak = None
    hull = LEAK_HULL.search(text)
    if hull:
        ent = LEAK_ENTITY.search(text, hull.end())
        lin = base.with_suffix(".lin")
        line = parse_lin(lin) if lin.exists() else []
        leak = {
            "hull": int(hull.group(1)),
            "entity": {"classname": ent.group(1), "origin": _vec(list(ent.groups()[1:]))}
            if ent
            else None,
            # The pointfile runs from the entity's leaf towards the outside; its first point
            # is the portal where the leak leaves the playable space (usually the hole).
            "first_point": line[0] if line else None,
            "line": line,
            "pointfile": base.with_suffix(".pts").name
            if base.with_suffix(".pts").exists()
            else None,
        }
    textures = TEXTURES_REFERENCED.findall(text)
    wads = WADS_REQUIRED.findall(text)
    return {
        "steps": steps,
        "errors": _messages(ERROR, text),
        "warnings": [w for w in _messages(WARNING, text) if not LEAK_HULL.search(w)],
        "leak": leak,
        "limits": parse_limits(text),
        "textures_referenced": int(textures[-1]) if textures else None,
        "wads_required": int(wads[-1]) if wads else None,
    }
