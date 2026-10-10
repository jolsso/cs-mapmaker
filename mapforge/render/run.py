"""Render a map: top-down views (lit and light-only) -> build/<map>/renders/ + index.json.

Usage: python -m mapforge.render.run --map de_dust2 [--source map|reference]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from mapforge.bsp.reader import read_bsp
from mapforge.config import Config, load_config
from mapforge.refmaps import extract_archives, find_reference_bsp
from mapforge.render.brightness import dark_zones, floor_brightness
from mapforge.render.cameras import auto_cameras, configured_cameras
from mapforge.render.gl import Renderer, look_at
from mapforge.render.mesh import build_mesh
from mapforge.render.textures import MISSING, WadIndex, wad_search_paths
from mapforge.render.topdown import annotate, draw_zones, render_topdown
from mapforge.validate.checks import spawn_origins
from mapforge.validate.walk import build_walk_graph


def _dirs(cfg: Config, key: str) -> list[Path]:
    out = []
    for d in cfg.data["render"][key]:
        p = Path(d)
        out.append(p if p.is_absolute() else cfg.root / p)
    return out


def render_map(cfg: Config, map_name: str, bsp_path: Path) -> dict[str, Any]:
    t0 = time.monotonic()
    out_dir = cfg.path("build_dir") / map_name / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    bsp = read_bsp(bsp_path)
    wads = WadIndex(wad_search_paths(bsp_path, _dirs(cfg, "wad_dirs")))
    mesh = build_mesh(bsp)
    renderer = Renderer(bsp, mesh, wads)

    wcfg = cfg.data["validate"]["walk"]
    origins, _ = spawn_origins(bsp.entities)
    graph = build_walk_graph(
        bsp,
        origins,
        cell=16,
        z_step=float(wcfg["z_step"]),
        max_step=float(wcfg["max_step"]),
        max_drop=float(wcfg["max_drop"]),
        jump_height=float(wcfg["jump_height"]),
    )  # fmt: skip  (16-unit grid is plenty to decide what to cut away)
    lo, hi = mesh.bounds
    lit, light, view = render_topdown(renderer, bsp, graph, (lo[2], hi[2]))

    images = []
    for name, img, purpose in (
        ("topdown.png", lit, "Overview from above: textures + compiled lighting; geometry above "
                             "player height is cut away. Spawns: T orange, CT blue; bomb sites "
                             "yellow."),
        ("topdown_light.png", light, "Lightmap only (brightness), same view. Dark areas are dark "
                                     "in game."),
    ):  # fmt: skip
        annotate(img, view, bsp, f"{map_name} - {name.removesuffix('.png')}").save(out_dir / name)
        images.append({"file": name, "kind": "topdown", "purpose": purpose, "view": view.to_dict()})
    # Brightness where players stand (compiled lightmap of the floor) and dark zones.
    bcfg = cfg.data["render"]["brightness"]
    bright = floor_brightness(bsp, graph)
    zones = dark_zones(bright, float(bcfg["dark_luma"]), graph.cell, int(bcfg["min_zone_cells"]))
    dark_img = draw_zones(annotate(lit, view, bsp, f"{map_name} - dark zones"), view, zones)
    dark_img.save(out_dir / "topdown_dark.png")
    images.append({
        "file": "topdown_dark.png", "kind": "topdown", "view": view.to_dict(),
        "purpose": f"Dark zones (red): walkable floor with lightmap luma < {bcfg['dark_luma']} "
                   f"over at least {int(bcfg['min_zone_cells'])} cells.",
    })  # fmt: skip
    q = np.percentile(bright.luma, [5, 25, 50]) if len(bright.luma) else [0, 0, 0]
    brightness = {
        "dark_luma": bcfg["dark_luma"],
        "floor_cells": int(len(bright.luma)),
        "unknown_cells": bright.unknown,
        "luma_p5_p25_p50": [round(float(v), 1) for v in q],
        "dark_zones": zones,
    }

    # Perspective views: automatic presets + config/cameras/<map>.yaml.
    cams = auto_cameras(bsp, graph) + configured_cameras(
        cfg.root / "config" / "cameras" / f"{map_name}.yaml"
    )
    w, h = cfg.data["render"].get("camera_size", [1280, 720])
    for cam in cams:
        img = renderer.render(
            look_at(np.array(cam.eye), np.array(cam.target), cam.fov, w, h),
            background=(0.55, 0.62, 0.72),  # sky is not drawn; a flat sky colour reads better
        )
        name = f"cam_{cam.name}.png"
        Image.fromarray(img).save(out_dir / name)
        images.append({"file": name, "kind": "camera", "purpose": cam.purpose, **cam.to_dict()})
    # Raw (unannotated) top-down, used as the base for heatmap overlays.
    Image.fromarray(lit).save(out_dir / "topdown_raw.png")

    missing = sorted(n for n, s in renderer.texture_sources.items() if s == MISSING)
    index = {
        "map": map_name,
        "bsp": bsp_path.as_posix(),
        "images": images,
        "base_for_overlays": {"file": "topdown_raw.png", "view": view.to_dict()},
        "missing_textures": missing,
        "brightness": brightness,
        "seconds": round(time.monotonic() - t0, 1),
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    parser.add_argument("--source", choices=["map", "reference"], default="map")
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.source == "reference":
        extract_archives(cfg)
        bsp_path = find_reference_bsp(cfg, args.map)
    else:
        bsp_path = cfg.path("build_dir") / args.map / f"{args.map}.bsp"
    if bsp_path is None or not bsp_path.is_file():
        print(f"no .bsp for {args.map} (compile it, or use --source reference)", file=sys.stderr)
        return 1
    index = render_map(cfg, args.map, bsp_path)
    print(f"rendered {len(index['images'])} images in {index['seconds']} s -> "
          f"{cfg.path('build_dir') / args.map / 'renders'}")  # fmt: skip
    if index["missing_textures"]:
        print(f"  missing textures (checkerboard): {', '.join(index['missing_textures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
