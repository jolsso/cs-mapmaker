"""Brief v2 (phase 8a, docs/MAPMAKER.md): what the human wants, before any geometry.

maps/<map>/brief.json - written by the dashboard (POST /api/maps), read by the Interpreter.
v1 (dashboard until 2026-10-15: name + description + canvas) is upgraded on read; nothing
else changes for it. Every field except name and description is optional: the Interpreter
fills the gaps and lists them as assumptions for the human to confirm.

The questions are the conceptual ones that change the rest of the pipeline markedly
(ROADMAP 8a): space and height, playing style, identity. Light mood, sound and props are not
asked here - the art pass decides those.

maps/<map>/brief/images.json - images with a tag (what they steer) and a licence:
  mood | landmark | material | layout;  own | cc0 (may be committed, may become textures)
  | inspiration (local only: brief/inspiration/, gitignored; agents may look, never a texture).
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any

VERSION = 2
NAME = re.compile(r"^de_[a-z0-9_]{2,28}$")
ENUMS: dict[str, tuple[str, ...]] = {
    "mode": ("simple", "advanced"),
    "archetype": ("three_lane", "asymmetric", "stacked"),
    "pace": ("fast", "medium", "slow"),
    "size": ("small", "medium", "large"),
    # space and height
    "levels": ("flat", "some", "stacked"),
    "inside": ("mostly_outside", "mixed", "mostly_inside"),
    "density": ("tight", "mixed", "open"),
    # playing style
    "site_cover": ("open", "mixed", "cluttered"),
}
AMOUNT = ("few", "some", "many")  # sightlines.long / sightlines.cqb
LANDMARK_SPACE = ("small", "medium", "large")  # a crate stack .. a crane in the yard
TAGS = ("mood", "landmark", "material", "layout")
LICENSES = ("own", "cc0", "inspiration")
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# brief v2 fields: name -> (kind, help text shown in the dashboard and the Interpreter prompt)
FIELDS: dict[str, tuple[str, str]] = {
    "description": ("text", "the map in your own words: place, story, what it should feel like"),
    "concept": ("text", "the one idea that makes it this map (why the bomb, why here)"),
    "mode": ("enum", "simple: agents draw the sketch; advanced: you draw it in layers"),
    "archetype": ("enum", "three_lane (dust2/mirage), asymmetric, stacked (nuke/vertigo)"),
    "size": ("enum", "small (wingman-like), medium, large"),
    "pace": ("enum", "fast rotations and early contact, or slow and tactical"),
    "levels": ("enum", "space: flat, some height (stairs, platforms), or stacked floors"),
    "inside": ("enum", "space: mostly outside, mixed, or mostly inside"),
    "density": ("enum", "space: tight corridors or open yards"),
    "stacked_sites": ("bool", "space: one site above the other (like nuke)"),
    "sightlines": ("object", "playing style: {long: few|some|many, cqb: few|some|many}"),
    "site_cover": ("enum", "playing style: open sites (hard to hold) or cluttered (many angles)"),
    "sites": ("object", "per site (A, B): its character in a sentence"),
    "mid": ("text", "what mid is for"),
    "theme": ("text", "identity: setting and era (e.g. industrial harbour, winter, 1970s)"),
    "landmarks": (
        "list",
        "identity: [{name, note, space: small|medium|large}] - things that "
        "need room in the layout (a crane in the yard)",
    ),  # fmt: skip
    "must_have": ("list", "things the map must have"),
    "no_go": ("list", "things the map must not have"),
}


def _clip(v: Any, n: int) -> str:
    return str(v or "").strip()[:n]


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Any brief (v1 or v2) -> a v2 brief; unknown keys are dropped, bad values raise
    ValueError (the message names the field)."""
    b: dict[str, Any] = {"version": VERSION}
    name = _clip(raw.get("name"), 40)
    if not NAME.match(name):
        raise ValueError("name: de_ + 2-28 lower-case letters, digits or _ (e.g. de_harbour01)")
    b["name"] = name
    desc = _clip(raw.get("description"), 4000)
    if len(desc) < 10:
        raise ValueError("description: 10-4000 characters")
    b["description"] = desc
    b["mode"] = raw.get("mode") or "simple"
    for k, (kind, _) in FIELDS.items():
        if k in ("description", "mode") or raw.get(k) in (None, "", [], {}):
            continue
        v = raw[k]
        if kind == "enum":
            if v not in ENUMS[k]:
                raise ValueError(f"{k}: one of {ENUMS[k]}")
            b[k] = v
        elif kind == "text":
            b[k] = _clip(v, 1000)
        elif kind == "bool":
            b[k] = bool(v)
        elif k == "sightlines":
            sl = {s: v.get(s) for s in ("long", "cqb") if v.get(s)}
            if any(x not in AMOUNT for x in sl.values()):
                raise ValueError(f"sightlines: long/cqb one of {AMOUNT}")
            b[k] = sl
        elif k == "sites":
            b[k] = {s: _clip(v.get(s), 500) for s in ("A", "B") if v.get(s)}
        elif k == "landmarks":
            lms = []
            for lm in v[:8]:
                lm = {"name": lm} if isinstance(lm, str) else dict(lm)
                if not _clip(lm.get("name"), 80):
                    raise ValueError("landmarks: every landmark needs a name")
                sp = lm.get("space") or "medium"
                if sp not in LANDMARK_SPACE:
                    raise ValueError(f"landmarks.space: one of {LANDMARK_SPACE}")
                lms.append({"name": _clip(lm["name"], 80), "note": _clip(lm.get("note"), 300),
                            "space": sp})  # fmt: skip
            b[k] = lms
        else:  # must_have / no_go
            b[k] = [_clip(x, 300) for x in v[:12] if _clip(x, 300)]
    if b["mode"] not in ENUMS["mode"]:
        raise ValueError(f"mode: one of {ENUMS['mode']}")
    for k in ("created", "status", "canvas"):  # bookkeeping from the dashboard
        if k in raw:
            b[k] = raw[k]
    return b


def load(maps_dir: Path, name: str) -> dict[str, Any] | None:
    p = maps_dir / name / "brief.json"
    if not p.is_file():
        return None
    return normalize(json.loads(p.read_text(encoding="utf-8")))


def save(maps_dir: Path, b: dict[str, Any]) -> None:
    d = maps_dir / b["name"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "brief.json").write_text(json.dumps(b, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8", newline="\n")  # fmt: skip


def create(maps_dir: Path, raw: dict[str, Any], canvas: list[int]) -> dict[str, Any]:
    """A new map project: maps/<name>/brief.json (v2)."""
    b = normalize({**raw, "created": time.strftime("%Y-%m-%d %H:%M"), "status": "brief",
                   "canvas": canvas})  # fmt: skip
    if (maps_dir / b["name"]).exists():
        raise ValueError(f"{b['name']} exists already")
    save(maps_dir, b)
    return b


# --- images ----------------------------------------------------------------------------------


def images(maps_dir: Path, name: str) -> list[dict[str, Any]]:
    p = maps_dir / name / "brief" / "images.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []


def image_path(maps_dir: Path, name: str, img: dict[str, Any]) -> Path:
    """Where an image lives: brief/ (own, cc0) or brief/inspiration/ (gitignored)."""
    d = maps_dir / name / "brief"
    return (d / "inspiration" if img["license"] == "inspiration" else d) / img["file"]


def add_image(maps_dir: Path, name: str, req: dict[str, Any]) -> dict[str, Any]:
    """Upload one image: {file, data (base64), tag, license, note}. Re-encoded with Pillow,
    which drops EXIF (location, camera) and anything that is not a PNG/JPEG picture."""
    from PIL import Image

    if not (maps_dir / name / "brief.json").is_file():
        raise ValueError("unknown map")
    tag, lic = req.get("tag"), req.get("license")
    if tag not in TAGS:
        raise ValueError(f"tag: one of {TAGS}")
    if lic not in LICENSES:
        raise ValueError(f"license: one of {LICENSES}")
    data = base64.b64decode(str(req.get("data", "")), validate=True)
    if not 0 < len(data) <= MAX_IMAGE_BYTES:
        raise ValueError("image: 1 byte - 8 MB")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # noqa: BLE001 - any decoder error means: not an image
        raise ValueError(f"image: not a PNG/JPEG ({exc})") from None
    if im.format not in ("PNG", "JPEG"):
        raise ValueError("image: only PNG or JPEG")
    stem = re.sub(r"[^a-z0-9_-]+", "_", Path(str(req.get("file") or "image")).stem.lower())[:40]
    ext = ".png" if im.format == "PNG" else ".jpg"
    lst = images(maps_dir, name)
    taken = {i["file"] for i in lst}
    file, k = f"{stem or 'image'}{ext}", 2
    while file in taken:
        file, k = f"{stem}_{k}{ext}", k + 1
    entry = {"file": file, "tag": tag, "license": lic, "note": _clip(req.get("note"), 300)}
    out = image_path(maps_dir, name, entry)
    out.parent.mkdir(parents=True, exist_ok=True)
    clean = im.convert("RGB") if im.format == "JPEG" else im.convert("RGBA")
    clean.save(out, im.format)  # a fresh file: no EXIF, no text chunks
    lst.append(entry)
    p = maps_dir / name / "brief" / "images.json"
    p.write_text(json.dumps(lst, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                 newline="\n")  # fmt: skip
    return entry
