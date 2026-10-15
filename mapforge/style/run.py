"""Style review (phase 7): systematic cameras over the whole map, checked against the map's
ART_DIRECTION.md by Claude, with pass/fail decided here (no critical findings).

  --emit (default)  render build/<map>/style/ (+ index.json with per-image numbers), put the
                    views that changed since the last scored review on contact sheets
                    (style/sheets/, six views each, by zone; --all: every view) and write
                    style_prompt.md + style_schema.json; a fresh subagent reads all sheets in one
                    turn and writes build/<map>/style_answer.json.
  --answer [FILE]   check that answer against the schema -> build/<map>/style.json; findings
                    on views that did not change are carried over from the previous review.

Cameras (mapforge.style.cameras): every area from its middle, both sides of every chokepoint
and site entrance, every landmark from inside its zone. Deterministic checks run first and
become findings themselves: missing textures and dark zones are critical; images that are
largely burnt out (luma >= 250) are medium.

Exit 0 = pass (or prompt written), 1 = fail, 2 = could not run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from mapforge.config import Config, load_config
from mapforge.style.sheets import image_hash, make_sheets

SEVERITIES = ("critical", "medium", "cosmetic")  # ART_DIRECTION.md §7: kritisk/middel/kosmetisk
BURNT_LUMA, BURNT_SHARE = 250, 0.25  # an image with >= 25 % pure-white pixels is burnt out

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "image": {"type": "string"},
                    "where": {"type": "string"},
                    "what": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "image", "where", "what", "fix"],
            },
        },
        "zones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "zone": {"type": "string"},
                    "score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "reason": {"type": "string"},
                },
                "required": ["zone", "score", "reason"],
            },
        },
    },
    "required": ["summary", "findings", "zones"],
}

PROMPT = """You are the style reviewer in a pipeline that builds Counter-Strike 1.6 maps (GoldSrc). The map is in its art pass (phase 7): the layout is locked; only textures, lighting, props and dressing can change. Judge the views against the map's art direction and its checklist (§7). Be concrete: a few real findings with a usable fix beat many vague ones. The art direction is written in Danish; answer in English.

Map: {map}

## Images
The images are contact sheets: six camera views per sheet, numbered 1-6 with the camera's name above each view. **Read ALL sheets in one message** (several Read calls in the same turn), then write the answer - do not read them one at a time. If you need a view at full resolution, it is at {full}/<name>.png. Eye height 64 units (a standing player), FOV {fov} degrees. Our own renderer: textures and compiled lighting, but the sky is a flat colour, and decals, models and sprites are not shown.
{scope}
{images}

## Deterministic measurements (already run)
{numbers}

## Art direction (the reference)
{art}

## Answer
Write all text in English. Answer ONLY with JSON following the schema.
- `findings`: one per concrete problem. `image` is the camera's file name (e.g. `area_a_site_north.png`), not the sheet's. `severity`: `critical` = affects gameplay/readability (e.g. players hard to see against the background, a dark play area), `medium` = breaks the style (wrong palette for the zone, landmark not recognisable, stretched or misaligned texture, patterned repetition), `cosmetic` = small things. `where` = area/door/landmark in words. `fix` = the concrete fix (texture, light colour/brightness, prop or decal) - never a change to the layout.
- `zones`: one score 1-5 per zone of the art direction (`t`, `ct`, `mid`, `a`, `b` ...) for how well the views hit the zone's palette, materials and lighting mood.
"""


def _shown(p: Path, root: Path) -> str:
    try:
        return str(root / p.relative_to(root)) if p.is_absolute() else str(root / p)
    except ValueError:
        return str(p)


def image_numbers(path: Path) -> dict[str, float]:
    """Mean luma, share of burnt-out and near-black pixels, and RMS contrast of an image."""
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    luma = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    return {
        "mean_luma": round(float(luma.mean()), 1),
        "burnt": round(float((luma >= BURNT_LUMA).mean()), 3),
        "black": round(float((luma <= 8).mean()), 3),
        "contrast": round(float(luma.std()), 1),
    }


def render_style(cfg: Config, map_name: str) -> dict[str, Any]:
    from mapforge.bsp.reader import read_bsp
    from mapforge.generator.spec import parse_layout
    from mapforge.render.gl import Renderer, look_at
    from mapforge.render.mesh import build_mesh
    from mapforge.render.run import _dirs
    from mapforge.render.textures import MISSING, WadIndex, wad_search_paths
    from mapforge.style.cameras import FOV, style_cameras

    t0 = time.monotonic()
    build = cfg.path("build_dir") / map_name
    bsp_path = build / f"{map_name}.bsp"
    if not bsp_path.is_file():
        raise RuntimeError(f"missing {bsp_path}: run `./mf validate` first")
    raw = yaml.safe_load(
        (cfg.path("maps_dir") / map_name / "layout.yaml").read_text(encoding="utf-8")
    )
    layout = parse_layout(raw)
    bsp = read_bsp(bsp_path)
    renderer = Renderer(
        bsp, build_mesh(bsp), WadIndex(wad_search_paths(bsp_path, _dirs(cfg, "wad_dirs")))
    )
    out = build / "style"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    w, h = cfg.data["render"].get("camera_size", [1280, 720])
    images = []
    for sc in style_cameras(layout, raw, bsp):
        img = renderer.render(look_at(np.array(sc.cam.eye), np.array(sc.cam.target), sc.cam.fov, w, h),
                              background=(0.55, 0.62, 0.72))  # fmt: skip
        name = f"{sc.cam.name}.png"
        Image.fromarray(img).save(out / name)
        images.append({"file": name, "kind": sc.kind, "area": sc.area, "zone": sc.zone,
                       "subject": sc.subject, "hash": image_hash(out / name),
                       **sc.cam.to_dict(), **image_numbers(out / name)})  # fmt: skip
    rindex = build / "renders" / "index.json"
    brightness = (
        json.loads(rindex.read_text(encoding="utf-8")).get("brightness", {})
        if rindex.is_file()
        else {}
    )
    index = {
        "map": map_name,
        "bsp_sha256": hashlib.sha256(
            bsp_path.read_bytes()
        ).hexdigest(),  # history ties it to a version
        "fov": FOV,
        "images": images,
        "missing_textures": sorted(n for n, s in renderer.texture_sources.items() if s == MISSING),
        "dark_zones": len(brightness.get("dark_zones", [])),
        "seconds": round(time.monotonic() - t0, 1),
    }
    (out / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return index


def deterministic_findings(index: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for name in index["missing_textures"]:
        out.append({"severity": "critical", "image": "index.json", "where": name,
                    "what": f"texture {name} is in no WAD (checkerboard in game)",
                    "fix": "pick a texture from ./mf textures"})  # fmt: skip
    if index["dark_zones"]:
        out.append({"severity": "critical", "image": "renders/topdown_dark.png", "where": "play areas",
                    "what": f"{index['dark_zones']} dark zones in the brightness map",
                    "fix": "more light or a brighter zone colour there"})  # fmt: skip
    for i in index["images"]:
        if i["burnt"] >= BURNT_SHARE:
            out.append({"severity": "medium", "image": i["file"], "where": i["subject"],
                        "what": f"{i['burnt']:.0%} of the view is burnt out (luma >= {BURNT_LUMA})",
                        "fix": "lower sun/light brightness or a darker texture in the zone"})  # fmt: skip
    return out


def build_prompt(
    cfg: Config, map_name: str, index: dict[str, Any], sheets: list[dict], carried: int = 0
) -> str:
    out = cfg.path("build_dir") / map_name / "style"
    art = cfg.path("maps_dir") / map_name / "ART_DIRECTION.md"
    if not art.is_file():
        raise RuntimeError(f"missing {art}: the style review needs the map's art direction")
    purpose = {i["file"]: i["purpose"] for i in index["images"]}
    images = "\n".join(
        f"- {_shown(out / 'sheets' / sh['file'], cfg.root)} (zone {sh['zone']}): "
        + "; ".join(f"{t['n']} = {t['image']} ({purpose[t['image']]})" for t in sh["tiles"])
        for sh in sheets
    )
    scope = (
        f"Only the {sum(len(sh['tiles']) for sh in sheets)} views that changed since the last "
        f"review are included; {carried} unchanged views keep their earlier findings."
        if carried
        else "All views are included."
    )
    rows = [
        "| image | zone | mean luma | burnt out | black | contrast |",
        "|---|---|---|---|---|---|",
    ]
    rows += [f"| {i['file']} | {i['zone'] or '-'} | {i['mean_luma']} | {i['burnt']:.0%} | {i['black']:.0%} | {i['contrast']} |"
             for i in index["images"]]  # fmt: skip
    numbers = "\n".join(rows) + (
        f"\n\nDark zones in the brightness map: {index['dark_zones']}. Missing textures: "
        f"{index['missing_textures'] or 'none'}."
    )
    return PROMPT.format(map=map_name, fov=index["fov"], images=images, numbers=numbers, scope=scope,
                         full=_shown(out, cfg.root), art=art.read_text(encoding="utf-8"))  # fmt: skip


def previous(build: Path) -> dict[str, Any]:
    """The last scored review (style.json), or {}."""
    p = build / "style.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def emit(cfg: Config, map_name: str, review_all: bool = False) -> dict[str, Any]:
    """Render, put the changed views on sheets, write prompt + schema. -> summary numbers."""
    build = cfg.path("build_dir") / map_name
    index = render_style(cfg, map_name)
    seen = {} if review_all else previous(build).get("image_hashes", {})
    todo = [i for i in index["images"] if seen.get(i["file"]) != i["hash"]]
    sheets = make_sheets(build / "style", todo, build / "style" / "sheets")
    (build / "style" / "sheets.json").write_text(json.dumps(sheets, indent=2), encoding="utf-8")
    carried = len(index["images"]) - len(todo)
    (build / "style_prompt.md").write_text(
        build_prompt(cfg, map_name, index, sheets, carried), encoding="utf-8"
    )
    (build / "style_schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
    return {"images": len(index["images"]), "changed": len(todo), "sheets": len(sheets),
            "seconds": index["seconds"]}  # fmt: skip


def score(cfg: Config, map_name: str, answer: dict[str, Any], executor: str) -> dict[str, Any]:
    """Pass/fail in code: deterministic findings + the answer's + previous findings on views that
    did not change. -> style.json."""
    build = cfg.path("build_dir") / map_name
    index = json.loads((build / "style" / "index.json").read_text(encoding="utf-8"))
    sheets = json.loads((build / "style" / "sheets.json").read_text(encoding="utf-8"))
    reviewed = {t["image"] for sh in sheets for t in sh["tiles"]}
    current = {i["file"] for i in index["images"]}
    old = [f for f in previous(build).get("findings", [])
           if f.get("image") in current - reviewed and f.get("source") != "code"]  # fmt: skip
    code = [{**f, "source": "code"} for f in deterministic_findings(index)]
    findings = code + [{**f, "source": executor} for f in answer["findings"]] + old
    result = {"map": map_name, "passed": not any(f["severity"] == "critical" for f in findings),
              "executor": executor, "summary": answer["summary"], "zones": answer["zones"],
              "findings": findings, "images": len(index["images"]), "reviewed": len(reviewed),
              "image_hashes": {i["file"]: i["hash"] for i in index["images"]}}  # fmt: skip
    (build / "style.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def check_answer(answer: Any) -> dict[str, Any]:
    if not isinstance(answer, dict) or not isinstance(answer.get("summary"), str):
        raise RuntimeError("answer must be an object with a string 'summary'")
    for i, f in enumerate(answer.get("findings", None) or []):
        missing = [
            k
            for k in ("severity", "image", "where", "what", "fix")
            if not isinstance(f.get(k), str)
        ]
        if missing:
            raise RuntimeError(f"finding {i} lacks string field(s): {missing}")
        if f["severity"] not in SEVERITIES:
            raise RuntimeError(f"finding {i}: severity must be one of {SEVERITIES}")
    if not isinstance(answer.get("findings"), list) or not isinstance(answer.get("zones"), list):
        raise RuntimeError("answer.findings and answer.zones must be lists")
    for z in answer["zones"]:
        if not isinstance(z.get("score"), int) or not 1 <= z["score"] <= 5:
            raise RuntimeError(f"zone score {z!r}: integer 1-5")
    return answer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--map", required=True)
    ap.add_argument("--answer", nargs="?", const="", metavar="FILE")
    ap.add_argument("--all", action="store_true", help="review every view, not only changed ones")
    ap.add_argument(
        "--local",
        action="store_true",
        help="emit, then review the sheets with the local model (style.local)",
    )
    ap.add_argument("--resume", action="store_true",
                    help="with --local: no new emit; go on from the last sheet that was done")  # fmt: skip
    args = ap.parse_args(argv)
    cfg = load_config()
    build = cfg.path("build_dir") / args.map
    try:
        if args.local:
            from mapforge.style.local import run_local
            from mapforge.style.publish import publish

            if not args.resume:
                n = emit(cfg, args.map, args.all)
                snapshot(cfg, args.map)
                print(f"style {args.map}: {n['changed']} of {n['images']} views on {n['sheets']} "
                      f"sheets -> local model {cfg.data['style']['local']['model']}")  # fmt: skip
                publish(cfg, args.map, images=True)
            answer = check_answer(
                run_local(cfg, args.map, lambda: publish(cfg, args.map), resume=args.resume)
            )
            (build / "style_answer.json").write_text(
                json.dumps(answer, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            result = score(cfg, args.map, answer, "local")
            publish(cfg, args.map)
            snapshot(cfg, args.map)
            report(args.map, result)
            return 0 if result["passed"] else 1
        if args.answer is None:
            n = emit(cfg, args.map, args.all)
            snapshot(cfg, args.map)
            print(f"style {args.map}: {n['images']} views ({n['changed']} changed) on {n['sheets']} sheets "
                  f"in {n['seconds']} s; prompt {build / 'style_prompt.md'} -> answer to "
                  f"{build / 'style_answer.json'}, then --answer")  # fmt: skip
            return 0
        path = Path(args.answer) if args.answer else build / "style_answer.json"
        answer = check_answer(json.loads(path.read_text(encoding="utf-8")))
        result = score(cfg, args.map, answer, "session")
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"style review failed to run: {exc}", file=sys.stderr)
        return 2
    snapshot(cfg, args.map)
    report(args.map, result)
    return 0 if result["passed"] else 1


def snapshot(cfg: Config, map_name: str) -> None:
    """Keep the style review with the history version of this .bsp (and on the website)."""
    from mapforge.history import snapshot as history_snapshot

    history_snapshot(cfg, map_name)


def report(map_name: str, result: dict[str, Any]) -> None:
    counts = {s: sum(f["severity"] == s for f in result["findings"]) for s in SEVERITIES}
    print(
        f"style {map_name}: {'PASS' if result['passed'] else 'FAIL'} {counts} - {result['summary']}"
    )
    for f in result["findings"]:
        print(f"  [{f['severity']}] {f['where']}: {f['what']} -> {f['fix']} ({f['image']})")


if __name__ == "__main__":
    sys.exit(main())
