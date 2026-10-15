"""Interpreter (phase 8a, docs/MAPMAKER.md): brief + images -> intent.json, "how I understood
you" - the first thing the human confirms before any geometry is drawn.

Same pattern as Review/Decide: a prompt and a schema are written, a fresh subagent (or a
headless `claude -p`) reads the brief and every image and writes the answer, and the code
decides whether the answer is acceptable:

  ./mf brief MAP=<name>              -> build/<map>/intent_prompt.md + intent_schema.json
  ./mf brief MAP=<name> -- --answer  build/<map>/intent_answer.json -> maps/<map>/intent.json

Rules checked in code (not left to the model):
- the schema (types, enums, ranges);
- every `must_have` of the brief appears exactly once: covered (how) or rejected (why);
- a value the brief set is kept, or the change is listed under `assumptions` with a reason;
  every question the brief left open is answered under `assumptions` too, so the human sees
  what was guessed;
- targets lie in the bands of docs/DESIGN_GUIDE.md (T -> site 14-25 s, CT lead >= 3 s).
The dashboard edits the intent through PUT /api/maps/<map>/intent (save_edit), same checks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from mapforge import brief as briefs
from mapforge.config import Config, load_config

E = briefs.ENUMS
S = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "summary",
        "concept",
        "archetype",
        "size",
        "pace",
        "space",
        "playstyle",
        "sites",
        "mid",
        "landmarks",
        "theme",
        "targets",
        "must_have",
        "no_go",
        "assumptions",
        "open_questions",
    ],  # fmt: skip
    "properties": {
        "summary": {"type": "string", "minLength": 40},
        "concept": {"type": "string", "minLength": 10},
        "archetype": {"type": "string", "enum": list(E["archetype"])},
        "size": {"type": "string", "enum": list(E["size"])},
        "pace": {"type": "string", "enum": list(E["pace"])},
        "space": {
            "type": "object",
            "required": ["levels", "inside", "density", "stacked_sites"],
            "properties": {
                "levels": {"type": "string", "enum": list(E["levels"])},
                "inside": {"type": "string", "enum": list(E["inside"])},
                "density": {"type": "string", "enum": list(E["density"])},
                "stacked_sites": {"type": "boolean"},
            },
        },
        "playstyle": {
            "type": "object",
            "required": ["sightlines", "site_cover"],
            "properties": {
                "sightlines": {
                    "type": "object",
                    "required": ["long", "cqb"],
                    "properties": {
                        "long": {"type": "string", "enum": list(briefs.AMOUNT)},
                        "cqb": {"type": "string", "enum": list(briefs.AMOUNT)},
                    },  # fmt: skip
                },
                "site_cover": {"type": "string", "enum": list(E["site_cover"])},
            },
        },
        "sites": {
            "type": "object",
            "required": ["A", "B"],
            "properties": {
                s: {
                    "type": "object",
                    "required": ["character", "entrances", "vertical"],
                    "properties": {
                        "character": S,
                        "entrances": {"type": "integer", "minimum": 2, "maximum": 4},
                        "vertical": {"type": "boolean"},
                    },  # fmt: skip
                }
                for s in ("A", "B")
            },
        },
        "mid": S,
        "landmarks": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": ["name", "where", "space", "purpose", "image"],
                "properties": {
                    "name": S,
                    "where": S,
                    "space": {"type": "string", "enum": list(briefs.LANDMARK_SPACE)},
                    "purpose": S,
                    "image": S,
                },  # fmt: skip
            },
        },
        "theme": {
            "type": "object",
            "required": ["setting", "tags", "palette", "materials"],
            "properties": {
                "setting": S,
                "tags": {"type": "array", "items": S},
                "palette": {"type": "array", "items": S},
                "materials": {"type": "array", "items": S},
            },  # fmt: skip
        },
        "targets": {
            "type": "object",
            "required": ["t_to_site_s", "ct_lead_s", "longest_sightline"],
            "properties": {
                "t_to_site_s": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "number", "minimum": 10, "maximum": 30},
                },  # fmt: skip
                "ct_lead_s": {"type": "number", "minimum": 3, "maximum": 15},
                "longest_sightline": {"type": "integer", "minimum": 512, "maximum": 4096},
            },
        },
        "must_have": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item", "status", "how"],
                "properties": {
                    "item": S,
                    "status": {"type": "string", "enum": ["covered", "rejected"]},
                    "how": {"type": "string", "minLength": 5},
                },  # fmt: skip
            },
        },
        "no_go": {"type": "array", "items": S},
        "assumptions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["field", "value", "why"],
                "properties": {"field": S, "value": S, "why": {"type": "string", "minLength": 5}},
            },
        },
        "open_questions": {"type": "array", "items": S},
    },
}
# brief field -> where it lands in the intent (for "kept or explained")
BRIEF_TO_INTENT = {
    "archetype": ("archetype",), "size": ("size",), "pace": ("pace",),
    "levels": ("space", "levels"), "inside": ("space", "inside"),
    "density": ("space", "density"), "stacked_sites": ("space", "stacked_sites"),
    "site_cover": ("playstyle", "site_cover"),
}  # fmt: skip


def check_schema(v: Any, sch: dict[str, Any], where: str = "intent") -> list[str]:
    """A small JSON-schema subset (type, enum, required, properties, items, min/max)."""
    errs: list[str] = []
    t = sch.get("type")
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool}
    if t == "integer":
        ok = isinstance(v, int) and not isinstance(v, bool)
    elif t == "number":
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
    else:
        ok = isinstance(v, kinds[t]) if t in kinds else True
    if not ok:
        return [f"{where}: expected {t}"]
    if "enum" in sch and v not in sch["enum"]:
        errs.append(f"{where}: {v!r} not one of {sch['enum']}")
    if t == "string" and len(v) < sch.get("minLength", 0):
        errs.append(f"{where}: at least {sch['minLength']} characters")
    if t in ("integer", "number"):
        if "minimum" in sch and v < sch["minimum"]:
            errs.append(f"{where}: {v} < {sch['minimum']}")
        if "maximum" in sch and v > sch["maximum"]:
            errs.append(f"{where}: {v} > {sch['maximum']}")
    if t == "object":
        for k in sch.get("required", []):
            if k not in v:
                errs.append(f"{where}.{k}: missing")
        for k, sub in sch.get("properties", {}).items():
            if k in v:
                errs += check_schema(v[k], sub, f"{where}.{k}")
    if t == "array":
        if len(v) < sch.get("minItems", 0) or len(v) > sch.get("maxItems", 1 << 30):
            errs.append(f"{where}: {len(v)} items (allowed {sch.get('minItems', 0)}-"
                        f"{sch.get('maxItems', 'any')})")  # fmt: skip
        for i, x in enumerate(v):
            errs += check_schema(x, sch.get("items", {}), f"{where}[{i}]")
    return errs


def check(intent: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Everything an intent must satisfy against its brief -> errors ([] = accepted)."""
    errs = check_schema(intent, SCHEMA)
    if errs:
        return errs
    # every must_have exactly once: covered or rejected with a reason
    want = [m.strip().lower() for m in brief.get("must_have", [])]
    got = [m["item"].strip().lower() for m in intent["must_have"]]
    for m in want:
        if got.count(m) != 1:
            errs.append(f"must_have: {m!r} must appear exactly once (covered or rejected)")
    for m in got:
        if m not in want:
            errs.append(f"must_have: {m!r} is not in the brief (put your own ideas elsewhere)")
    # brief values kept, or the change explained; open questions answered as assumptions
    assumed = {a["field"] for a in intent["assumptions"]}
    for field, path in BRIEF_TO_INTENT.items():
        v = intent
        for p in path:
            v = v[p]
        if field in brief and brief[field] != v and field not in assumed:
            errs.append(f"{field}: the brief says {brief[field]!r}, the intent {v!r} - "
                        "keep it or explain the change under assumptions")  # fmt: skip
        if field not in brief and field not in assumed:
            errs.append(f"{field}: not in the brief - list your choice under assumptions")
    lo, hi = intent["targets"]["t_to_site_s"]
    if not 14 <= lo < hi <= 25:
        errs.append("targets.t_to_site_s: 14 <= min < max <= 25 s (DESIGN_GUIDE)")
    if intent["space"]["stacked_sites"] and intent["space"]["levels"] == "flat":
        errs.append("space: stacked sites need levels 'some' or 'stacked', not 'flat'")
    return errs


# --- prompt / answer -------------------------------------------------------------------------

PROMPT = """You are the Interpreter in a pipeline that builds Counter-Strike 1.6 bomb-defusal maps (GoldSrc) from a human's brief. Turn the brief and its images into an **intent**: a precise statement of what the map should be, which the human confirms before any geometry is drawn. Everything later (sketch, layout, art pass) builds on it.

Map: {name}

## The brief (brief.json v2)
```json
{brief}
```
Field meanings: {fields}

## Images
{images}

## Rules
- Answer in English. Write JSON only, matching the schema in {schema}, to {answer}.
- `summary`: 2-4 sentences "this is how I understood you", in plain words the human will recognise.
- Keep every value the brief set. If you must change one (it contradicts another wish or the design norms), list it under `assumptions` with the reason.
- Every question the brief left open (archetype, size, pace, levels, inside, density, stacked_sites, site_cover): choose, and list each choice under `assumptions` (field = the brief field name) with a short reason. Ask under `open_questions` only what really changes the map and you cannot infer.
- `must_have`: every item of the brief exactly once, verbatim, status covered (say how) or rejected (say why - e.g. it breaks a design norm).
- `landmarks`: the brief's landmarks plus what the images tagged `landmark` show; `where` = which part of the map (A, B, mid, T spawn, ...); `space` = how much room it needs in the layout; `image` = the image file or "".
- `theme`: setting, tags, a palette (colour words) and materials, from the description and the images tagged mood/material.
- `targets`: T spawn -> site time [min, max] within 14-25 s, CT lead >= 3 s at both sites, longest sightline in units (1 unit = 1 inch; 2000+ is very long). Base them on pace, size and sightlines.
- Design norms (docs/DESIGN_GUIDE.md): 2-3 main routes, one chokepoint per route before each site, connectors around chokepoints, CT reaches every site >= 3 s before T.

## Design guide (excerpt)
{guide}
"""


def _guide(cfg: Config) -> str:
    p = cfg.root / "docs" / "DESIGN_GUIDE.md"
    text = p.read_text(encoding="utf-8") if p.is_file() else ""
    return text[:6000] + ("\n[...]" if len(text) > 6000 else "")


def emit(cfg: Config, name: str) -> Path:
    maps = cfg.path("maps_dir")
    b = briefs.load(maps, name)
    if b is None:
        raise ValueError(f"{name}: no brief.json")
    out = cfg.path("build_dir") / name
    out.mkdir(parents=True, exist_ok=True)
    imgs = briefs.images(maps, name)
    lines = [f"- {briefs.image_path(maps, name, i)} - tag {i['tag']}, licence {i['license']}"
             + (f": {i['note']}" if i["note"] else "") for i in imgs]  # fmt: skip
    if (maps / name / "annotations.json").is_file():
        lines.append(f"- sketch on a blank grid (the human's drawing, world units +-3072): "
                     f"{maps / name / 'annotations.json'} - indicative only")  # fmt: skip
    schema = out / "intent_schema.json"
    schema.write_text(json.dumps(SCHEMA, indent=1) + "\n", encoding="utf-8", newline="\n")
    prompt = PROMPT.format(
        name=name, brief=json.dumps(b, indent=2, ensure_ascii=False),
        fields="; ".join(f"{k}: {h}" for k, (_, h) in briefs.FIELDS.items()),
        images="\n".join(lines) or "(none) - read all images listed here before answering",
        schema=schema, answer=out / "intent_answer.json", guide=_guide(cfg),
    )  # fmt: skip
    p = out / "intent_prompt.md"
    p.write_text(prompt, encoding="utf-8", newline="\n")
    return p


def _write(maps: Path, name: str, intent: dict[str, Any], by: str, confirmed: bool) -> dict:
    intent = {**intent, "meta": {"by": by, "time": time.strftime("%Y-%m-%d %H:%M"),
                                 "confirmed": confirmed}}  # fmt: skip
    (maps / name / "intent.json").write_text(
        json.dumps(intent, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return intent


def answer(cfg: Config, name: str, file: Path | None = None) -> tuple[bool, list[str]]:
    maps = cfg.path("maps_dir")
    b = briefs.load(maps, name)
    if b is None:
        return False, [f"{name}: no brief.json"]
    f = file or cfg.path("build_dir") / name / "intent_answer.json"
    try:
        intent = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"{f}: {exc}"]
    intent.pop("meta", None)
    errs = check(intent, b)
    if not errs:
        _write(maps, name, intent, "interpreter", confirmed=False)
    return not errs, errs


def save_edit(maps: Path, name: str, req: dict[str, Any]) -> dict[str, Any]:
    """The human's corrections from the dashboard: {intent, confirm: bool} -> intent.json."""
    b = briefs.load(maps, name)
    if b is None:
        raise ValueError("unknown map")
    intent = dict(req.get("intent") or {})
    intent.pop("meta", None)
    errs = check(intent, b)
    if errs:
        raise ValueError("; ".join(errs[:6]))
    return _write(maps, name, intent, "human", confirmed=bool(req.get("confirm")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", required=True)
    ap.add_argument("--answer", nargs="?", const="", metavar="FILE")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.answer is None:
        try:
            p = emit(cfg, args.map)
        except ValueError as exc:
            print(f"brief {args.map}: {exc}", file=sys.stderr)
            return 2
        print(f"brief {args.map}: PROMPT READY - {p}; answer to "
              f"{p.parent / 'intent_answer.json'}, then --answer")  # fmt: skip
        return 0
    ok, errs = answer(cfg, args.map, Path(args.answer) if args.answer else None)
    if ok:
        print(f"brief {args.map}: INTENT OK -> maps/{args.map}/intent.json (waiting for you)")
        return 0
    print(f"brief {args.map}: REJECTED")
    for e in errs:
        print(f"  {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
