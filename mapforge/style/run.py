"""Style review (phase 7): systematic cameras over the whole map, checked against the map's
ART_DIRECTION.md by Claude, with pass/fail decided here (no critical findings).

  --emit (default)  render build/<map>/style/ (+ index.json with per-image numbers) and write
                    style_prompt.md + style_schema.json; a fresh subagent reads the prompt and
                    the images and writes build/<map>/style_answer.json.
  --answer [FILE]   check that answer against the schema -> build/<map>/style.json.

Cameras (mapforge.style.cameras): every area from its middle, both sides of every chokepoint
and site entrance, every landmark from inside its zone. Deterministic checks run first and
become findings themselves: missing textures and dark zones are critical; images that are
largely burnt out (luma >= 250) are medium.

Exit 0 = pass (or prompt written), 1 = fail, 2 = could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from mapforge.config import Config, load_config

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

PROMPT = """Du er stilreviewer i en pipeline, der laver Counter-Strike 1.6 maps (GoldSrc). Mappet er i art pass (fase 7): layoutet er låst, kun teksturer, lys, props og pynt kan ændres. Vurdér billederne mod mappets art direction og tjeklisten (§7). Vær konkret: hellere få, rigtige fund med en brugbar rettelse end mange vage.

Map: {map}

## Billeder
Læs HVER fil med Read-værktøjet (absolutte stier). Øjenhøjde 64 units (en stående spiller), FOV {fov}°. Vores egen renderer: teksturer og kompileret lys, men himlen er en flad farve, og decals, modeller og sprites vises ikke.
{images}

## Deterministiske målinger (allerede kørt)
{numbers}

## Art direction (facitliste)
{art}

## Svar
Skriv alle tekster på dansk. Svar KUN med JSON efter skemaet.
- `findings`: et fund pr. konkret problem. `severity`: `critical` = påvirker gameplay/læsbarhed (fx spillere svære at se mod baggrunden, mørkt spilområde), `medium` = bryder stilen (forkert palet for zonen, landmark ikke til at genkende, tekstur strakt eller forkert alignet, mønstret gentagelse), `cosmetic` = småting. `image` = filnavnet. `where` = område/dør/landmark i ord. `fix` = den konkrete rettelse (tekstur, lysfarve/-styrke, prop eller decal) – aldrig en ændring af layoutet.
- `zones`: én score 1-5 pr. zone i art direction (`t`, `ct`, `mid`, `a`, `b` …) for, hvor godt billederne rammer zonens palet, materialer og lys-stemning.
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
                       "subject": sc.subject, **sc.cam.to_dict(), **image_numbers(out / name)})  # fmt: skip
    rindex = build / "renders" / "index.json"
    brightness = (
        json.loads(rindex.read_text(encoding="utf-8")).get("brightness", {})
        if rindex.is_file()
        else {}
    )
    index = {
        "map": map_name,
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
                    "what": f"teksturen {name} findes ikke i nogen WAD (checkerboard i spillet)",
                    "fix": "vælg en tekstur fra ./mf textures"})  # fmt: skip
    if index["dark_zones"]:
        out.append({"severity": "critical", "image": "renders/topdown_dark.png", "where": "spilområder",
                    "what": f"{index['dark_zones']} mørke zoner i lysstyrkekortet",
                    "fix": "mere lys eller lysere zonefarve dér"})  # fmt: skip
    for i in index["images"]:
        if i["burnt"] >= BURNT_SHARE:
            out.append({"severity": "medium", "image": i["file"], "where": i["subject"],
                        "what": f"{i['burnt']:.0%} af billedet er udbrændt (luma >= {BURNT_LUMA})",
                        "fix": "lavere sol-/lysstyrke eller mørkere tekstur i zonen"})  # fmt: skip
    return out


def build_prompt(cfg: Config, map_name: str, index: dict[str, Any]) -> str:
    out = cfg.path("build_dir") / map_name / "style"
    art = cfg.path("maps_dir") / map_name / "ART_DIRECTION.md"
    if not art.is_file():
        raise RuntimeError(f"missing {art}: the style review needs the map's art direction")
    images = "\n".join(
        f"- {_shown(out / i['file'], cfg.root)} — {i['purpose']} [zone {i['zone'] or '-'}]"
        for i in index["images"]
    )
    rows = [
        "| billede | zone | middel-luma | udbrændt | sort | kontrast |",
        "|---|---|---|---|---|---|",
    ]
    rows += [f"| {i['file']} | {i['zone'] or '-'} | {i['mean_luma']} | {i['burnt']:.0%} | {i['black']:.0%} | {i['contrast']} |"
             for i in index["images"]]  # fmt: skip
    numbers = "\n".join(rows) + (
        f"\n\nMørke zoner i lysstyrkekortet: {index['dark_zones']}. Manglende teksturer: "
        f"{index['missing_textures'] or 'ingen'}."
    )
    return PROMPT.format(map=map_name, fov=index["fov"], images=images, numbers=numbers,
                         art=art.read_text(encoding="utf-8"))  # fmt: skip


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
    args = ap.parse_args(argv)
    cfg = load_config()
    build = cfg.path("build_dir") / args.map
    try:
        if args.answer is None:
            index = render_style(cfg, args.map)
            (build / "style_prompt.md").write_text(
                build_prompt(cfg, args.map, index), encoding="utf-8"
            )
            (build / "style_schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
            print(f"style {args.map}: {len(index['images'])} images in {index['seconds']} s; prompt "
                  f"{build / 'style_prompt.md'} -> answer to {build / 'style_answer.json'}, then --answer")  # fmt: skip
            return 0
        index = json.loads((build / "style" / "index.json").read_text(encoding="utf-8"))
        path = Path(args.answer) if args.answer else build / "style_answer.json"
        answer = check_answer(json.loads(path.read_text(encoding="utf-8")))
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"style review failed to run: {exc}", file=sys.stderr)
        return 2
    findings = deterministic_findings(index) + answer["findings"]
    result = {"map": args.map, "passed": not any(f["severity"] == "critical" for f in findings),
              "summary": answer["summary"], "zones": answer["zones"], "findings": findings,
              "images": len(index["images"])}  # fmt: skip
    (build / "style.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    counts = {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES}
    print(
        f"style {args.map}: {'PASS' if result['passed'] else 'FAIL'} {counts} - {answer['summary']}"
    )
    for f in findings:
        print(f"  [{f['severity']}] {f['where']}: {f['what']} -> {f['fix']} ({f['image']})")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
