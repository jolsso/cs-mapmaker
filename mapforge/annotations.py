"""Human annotations on a map: maps/<map>/annotations.json (drawn on the website's map page).

An annotation is a wish in world coordinates: a point ("more crates here"), a rectangle
("remove these corridors") or a freehand line ("a route like this"), with a text. Decide sees
the open ones first (mapforge.decide.run), with the layout areas each one touches; the loop
marks them done when a change that `addresses` "annotation:<id>" was applied.

Written by the live/API container (mapforge.live.collector) and by the loop; plain JSON so it
can be committed with the map.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

KINDS = {"point", "rect", "path", "note"}  # note = text only, no position
STATUSES = {"open", "done", "rejected", "needs_human"}
MAX_TEXT = 500


def path_of(maps_dir: Path, map_name: str) -> Path:
    return maps_dir / map_name / "annotations.json"


def load(maps_dir: Path, map_name: str) -> list[dict[str, Any]]:
    p = path_of(maps_dir, map_name)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []


def save(maps_dir: Path, map_name: str, items: list[dict[str, Any]]) -> None:
    p = path_of(maps_dir, map_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def validate(item: dict[str, Any]) -> dict[str, Any]:
    """A clean annotation from user input (raises ValueError)."""
    kind = item.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    text = str(item.get("text", "")).strip()[:MAX_TEXT]
    if not text:
        raise ValueError("text is required")
    pts = item.get("points")
    if kind == "note":
        return {"kind": kind, "text": text, "points": []}
    if not isinstance(pts, list) or not pts or len(pts) > 500:
        raise ValueError("points: 1..500 [x, y] pairs")
    try:
        points = [[round(float(p[0])), round(float(p[1]))] for p in pts]
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("points must be [x, y] numbers") from exc
    if any(abs(c) > 8192 for p in points for c in p):
        raise ValueError("points outside the map")
    need = {"point": 1, "rect": 2, "path": 2}[kind]
    if len(points) < need:
        raise ValueError(f"{kind} needs at least {need} point(s)")
    return {"kind": kind, "text": text, "points": points if kind != "rect" else points[:2]}


def add(maps_dir: Path, map_name: str, item: dict[str, Any]) -> dict[str, Any]:
    items = load(maps_dir, map_name)
    clean = validate(item)
    clean.update(
        id=max((a["id"] for a in items), default=0) + 1,
        status="open",
        created=time.strftime("%Y-%m-%d %H:%M"),
        resolution=None,
    )
    items.append(clean)
    save(maps_dir, map_name, items)
    return clean


def remove(maps_dir: Path, map_name: str, ann_id: int) -> bool:
    items = load(maps_dir, map_name)
    keep = [a for a in items if a["id"] != ann_id]
    save(maps_dir, map_name, keep)
    return len(keep) != len(items)


def bbox(a: dict[str, Any], pad: float = 0) -> tuple[float, float, float, float]:
    xs = [p[0] for p in a["points"]]
    ys = [p[1] for p in a["points"]]
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def touched_areas(a: dict[str, Any], layout: dict[str, Any]) -> list[str]:
    """Names of layout areas the annotation overlaps (a point/line gets 32 units of slack)."""
    if not a["points"]:
        return []
    x0, y0, x1, y1 = bbox(a, 0 if a["kind"] == "rect" else 32)
    hits = []
    from mapforge.generator.spec import expand_macros

    for area in expand_macros(layout, int(layout.get("grid", 16)))["areas"]:
        ax0, ay0, ax1, ay1 = area["rect"]
        if ax0 < x1 and x0 < ax1 and ay0 < y1 and y0 < ay1:
            hits.append(area["name"])
    return hits


def prompt_text(maps_dir: Path, map_name: str, layout: dict[str, Any] | None) -> str:
    """The open annotations for the Decide prompt ('' if none)."""
    items = [a for a in load(maps_dir, map_name) if a["status"] in ("open", "needs_human")]
    if not items:
        return ""
    lines = []
    for a in items:
        where = {"point": "punkt", "rect": "område", "path": "streg", "note": "tekst"}[a["kind"]]
        pts = a["points"] if a["kind"] != "path" else [a["points"][0], a["points"][-1]]
        if a["kind"] == "note":
            lines.append(f'- **annotation:{a["id"]}** (tekst, hele mappet): "{a["text"]}"')
            continue
        areas = ", ".join(touched_areas(a, layout)) if layout else ""
        lines.append(f"- **annotation:{a['id']}** ({where} {pts}{'; rammer: ' + areas if areas else ''}"
                     f"{'; status: venter på mennesket' if a['status'] == 'needs_human' else ''}): \"{a['text']}\"")  # fmt: skip
    return "\n".join(lines)


def resolve(
    maps_dir: Path, map_name: str, iteration: str, applied: list[dict], escalated: str | None
) -> list[int]:
    """After a plan was applied: annotations addressed by an applied change -> done.

    Returns the ids that changed. If the plan escalated, the open annotations it addressed
    become needs_human with the reason.
    """
    items = load(maps_dir, map_name)
    by_id = {a["id"]: a for a in items}
    changed = []
    for change in applied:
        for ref in change.get("addresses", []) or []:
            ref = str(ref)
            if ref.startswith("annotation:") and ref[11:].strip().isdigit():
                a = by_id.get(int(ref[11:].strip()))
                if a and a["status"] in ("open", "needs_human"):
                    a.update(
                        status="done",
                        resolution=f"iteration {iteration}: {change.get('effect', change.get('type'))}",
                    )
                    changed.append(a["id"])
    if escalated:
        for a in items:
            if a["status"] == "open" and f"annotation:{a['id']}" in escalated:
                a.update(
                    status="needs_human", resolution=f"iteration {iteration}: {escalated[:300]}"
                )
                changed.append(a["id"])
    if changed:
        save(maps_dir, map_name, items)
    return changed


def mark_needs_human(
    maps_dir: Path, map_name: str, iteration: str, ann_id: int, reason: str
) -> bool:
    """Decide could not fulfil a wish (outside the toolbox / against a locked decision)."""
    items = load(maps_dir, map_name)
    for a in items:
        if a["id"] == ann_id and a["status"] == "open":
            a.update(status="needs_human", resolution=f"iteration {iteration}: {reason[:300]}")
            save(maps_dir, map_name, items)
            return True
    return False
