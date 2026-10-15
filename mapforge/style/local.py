"""The style review on a local vision model (LM Studio's OpenAI-compatible API, style.local in
config/pipeline.yaml): one request per contact sheet, notes per view written as they come.

Calibrated 2026-10-15 on de_forge01 against Claude (one sheet, six views): with reasoning on,
the local model (qwen3.8-27b) caught the most important finding (players hard to see on A's
rust) and the texture repetition in B, but missed a landmark blending in, an off-palette prop and
a stretched texture. It is therefore the running reviewer between iterations, not the judge at
the phase 7 gate (that is Claude on the same sheets).

Live files (build/<map>/style/): notes.json (one entry per view, filled sheet by sheet) and
progress.json; the website's map page polls copies of them (mapforge.style.publish).
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from mapforge.config import Config

FLAGS = ("ok", "cosmetic", "medium", "critical")

SHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "zone_match": {"type": "integer", "minimum": 1, "maximum": 5},
                    "flag": {"type": "string", "enum": list(FLAGS)},
                    "note": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["n", "zone_match", "flag", "note", "fix"],
            },
        }
    },
    "required": ["images"],
}

SHEET_PROMPT = """You are the style reviewer for the Counter-Strike 1.6 map {map} in its art pass (the layout is locked; only textures, lighting, props and dressing can change). The image is a contact sheet with {count} camera views at eye height, numbered 1-{count}; the name above each view tells the area, door or landmark. Zone: {zone}.
{tiles}

## Important
- The views come from our own renderer: decals, models, sprites and the sky are NOT shown. Do not criticise that they are missing.
- zone_match: 5 = hits the zone's palette/materials/lighting perfectly, 3 = partly, 1 = wrong mood.
- Look for: (a) can a player in brown/olive (T) or blue-grey (CT) clothes be seen against the background - floor and wall in the same tone is bad; (b) does the landmark stand out from its surroundings; (c) stretched/pixelated texture or patterned repetition over large surfaces; (d) objects in a colour/texture that does not belong to the zone's palette.
- flag: ok if nothing is wrong; critical = gameplay/readability (players hard to see, dark), medium = breaks the style, cosmetic = small things. Say exactly what and where in the note (1-2 sentences, English). fix = a concrete fix (texture, light, prop, decal), never the layout; empty when ok.

Answer only with JSON. The art direction below is in Danish; answer in English.

## Art direction
{art}
"""


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (local LM Studio)
        return json.loads(r.read())


def review_sheet(cfg: Config, map_name: str, sheet: dict, sheet_png: Path, art: str) -> list[dict]:
    """Ask the local model about one sheet -> one note per view."""
    lc = cfg.data["style"]["local"]
    tiles = "\n".join(f"{t['n']}: {t['image'][:-4]}" for t in sheet["tiles"])
    prompt = SHEET_PROMPT.format(map=map_name, count=len(sheet["tiles"]), zone=sheet["zone"],
                                 tiles=tiles, art=art)  # fmt: skip
    b64 = base64.b64encode(sheet_png.read_bytes()).decode()
    body = {
        "model": lc["model"],
        "temperature": lc.get("temperature", 0.2),
        "top_p": lc.get("top_p", 0.9),
        "max_tokens": lc.get("max_tokens", 8000),
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "sheet_notes", "schema": SHEET_SCHEMA}},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    }  # fmt: skip
    got = None
    for _ in range(2):  # an empty answer = the reasoning used the budget: retry with more
        resp = _post(lc["url"].rstrip("/") + "/chat/completions", body, lc.get("timeout_s", 600))
        content = (resp["choices"][0]["message"].get("content") or "").strip()
        if content:
            got = json.loads(content)
            break
        body["max_tokens"] = 2 * body["max_tokens"]
    if got is None:
        raise ValueError(f"empty answer twice (max_tokens up to {body['max_tokens']})")
    by_n = {t["n"]: t for t in sheet["tiles"]}
    notes = []
    for g in got.get("images", []):
        t = by_n.get(g.get("n"))
        if t is None or g.get("flag") not in FLAGS:
            continue
        notes.append({"image": t["image"], "subject": t["subject"], "zone": sheet["zone"],
                      "sheet": sheet["file"], "flag": g["flag"], "zone_match": g["zone_match"],
                      "note": g["note"], "fix": g.get("fix", ""), "source": "local"})  # fmt: skip
    return notes


def run_local(cfg: Config, map_name: str, publish=None, resume: bool = False) -> dict[str, Any]:
    """Review every sheet of the last emit with the local model; notes and progress are written
    after each sheet (and handed to `publish`). resume: keep the notes of sheets already done and
    go on with the rest. -> an answer in the style SCHEMA."""
    build = cfg.path("build_dir") / map_name
    style = build / "style"
    sheets = json.loads((style / "sheets.json").read_text(encoding="utf-8"))
    art = (cfg.path("maps_dir") / map_name / "ART_DIRECTION.md").read_text(encoding="utf-8")
    notes: list[dict] = []
    if resume and (style / "notes.json").is_file():
        notes = json.loads((style / "notes.json").read_text(encoding="utf-8"))
    done_sheets = {n["sheet"] for n in notes}
    started = time.time()

    def progress(state: str, done: int, current: str | None = None, error: str | None = None):
        p = {"state": state, "executor": "local", "model": cfg.data["style"]["local"]["model"],
             "done": done, "total": len(sheets), "current": current, "started": started,
             "updated": time.time(), "views": sum(len(s["tiles"]) for s in sheets), "error": error}  # fmt: skip
        (style / "progress.json").write_text(json.dumps(p), encoding="utf-8")
        (style / "notes.json").write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
        if publish:
            publish()

    progress("running", len(done_sheets), sheets[0]["file"] if sheets else None)
    for k, sheet in enumerate(sheets):
        if sheet["file"] in done_sheets:
            continue
        try:
            notes += review_sheet(cfg, map_name, sheet, style / "sheets" / sheet["file"], art)
        except (OSError, ValueError, KeyError) as exc:
            progress("failed", k, sheet["file"], str(exc))
            raise RuntimeError(f"local model failed on {sheet['file']}: {exc}") from exc
        nxt = sheets[k + 1]["file"] if k + 1 < len(sheets) else None
        progress("running" if nxt else "done", k + 1, nxt)
    findings = [{"severity": n["flag"], "image": n["image"], "where": n["subject"],
                 "what": n["note"], "fix": n["fix"] or "-"}
                for n in notes if n["flag"] != "ok"]  # fmt: skip
    zones: dict[str, list[int]] = {}
    for n in notes:
        zones.setdefault(n["zone"], []).append(n["zone_match"])
    flagged = sum(1 for n in notes if n["flag"] != "ok")
    return {
        "summary": f"Local model ({cfg.data['style']['local']['model']}): {len(notes)} views "
                   f"judged, {flagged} with findings.",
        "findings": findings,
        "zones": [{"zone": z, "score": round(sum(v) / len(v)), "reason": "mean of the views"}
                  for z, v in sorted(zones.items())],
    }  # fmt: skip
