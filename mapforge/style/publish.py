"""The style review on the website: every view with the notes written under it, a progress bar
while an analysis runs, and a lightbox with a minimap of the camera.

`export` writes a style review's web form - its JSON (index, sheets, notes, progress, style.json),
the views as JPEGs (thumbnail + full size) and the minimap - into one directory. It is used for:
- the current build: build/site/maps/<map>/style/ (`publish`, polled by style.js while a run is
  going; the site build calls it too, so the section survives a rebuild), and
- each history version: history/<map>/<NNN>/style/ (mapforge.history.snapshot, only when the
  views were rendered from that very .bsp), shown in the version's Render panel.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from mapforge.config import Config

THUMB = (480, 270)
FILES = ("index.json", "sheets.json", "notes.json", "progress.json")
MINIMAP = 512  # px, longest side


def site_dir(cfg: Config, map_name: str) -> Path:
    return cfg.path("build_dir") / "site" / "maps" / map_name / "style"


def export(build: Path, out: Path, images: bool = True) -> Path | None:
    """Write build/style/ (+ build/style.json, the minimap from build/renders/) in web form to
    out/. images=False: only the JSON (cheap; for polling during a run)."""
    src = build / "style"
    if not (src / "index.json").is_file():
        return None
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if (src / name).is_file():
            shutil.copy2(src / name, out / name)
        elif (out / name).is_file() and name != "index.json":
            (out / name).unlink()  # e.g. no run since this render: no stale notes
    if (build / "style.json").is_file():
        shutil.copy2(build / "style.json", out / "style.json")
    if images:
        for old in out.glob("*.jpg"):
            old.unlink()
        minimap(build, out)
        for png in src.glob("*.png"):
            im = Image.open(png).convert("RGB")
            im.save(out / f"{png.stem}_full.jpg", quality=86)  # the lightbox
            im.thumbnail(THUMB)
            im.save(out / f"{png.stem}.jpg", quality=82)
    return out


def publish(cfg: Config, map_name: str, images: bool = False) -> Path | None:
    """The current build's style review on the website."""
    return export(cfg.path("build_dir") / map_name, site_dir(cfg, map_name), images)


def minimap(build: Path, out: Path) -> None:
    """The plain top-down render (no annotations) as the lightbox's minimap, with the world
    rectangle it covers (renders/index.json -> base_for_overlays: north up)."""
    rindex = build / "renders" / "index.json"
    if not rindex.is_file():
        return
    base = json.loads(rindex.read_text(encoding="utf-8")).get("base_for_overlays") or {}
    src = build / "renders" / base.get("file", "topdown_raw.png")
    if not src.is_file() or "view" not in base:
        return
    im = Image.open(src).convert("RGB")
    im.thumbnail((MINIMAP, MINIMAP))
    im.save(out / "minimap.jpg", quality=85)
    (out / "minimap.json").write_text(
        json.dumps({"world_rect": base["view"]["world_rect"], "size": list(im.size)}),
        encoding="utf-8",
    )


def block(base: str) -> str:
    """The style review's containers; style.js fills every `.style-review` from data-base."""
    return (
        f"<div class='style-review' data-base='{base}'><div class='style-progress small'></div>"
        "<div class='style-summary'></div><div class='style-grid'></div></div>"
    )


def section(cfg: Config, map_name: str) -> str:
    """The map page's section for the current build (empty if there is no style review yet)."""
    if publish(cfg, map_name, images=True) is None:
        return ""
    return (
        "<section class='panel' id='style'><h2>Style review <span class='muted small'>– every "
        "area, chokepoint and landmark at eye height, judged against the art direction · "
        "current build</span></h2>" + block("style/") + "</section>"
    )
