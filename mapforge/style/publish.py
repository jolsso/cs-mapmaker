"""The style review on the website: the map page's "Style review" section shows every view with
the note written under it, and a progress bar while an analysis runs.

`publish` copies build/<map>/style/{index,sheets,notes,progress}.json and style.json to
build/site/maps/<map>/style/ (and the views as small JPEGs with images=True); the page's script
(style.js) polls those files every few seconds while progress.json says "running". The site build
calls publish too, so the section survives a rebuild.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from mapforge.config import Config

THUMB = (480, 270)
FILES = ("index.json", "sheets.json", "notes.json", "progress.json")


def site_dir(cfg: Config, map_name: str) -> Path:
    return cfg.path("build_dir") / "site" / "maps" / map_name / "style"


def publish(cfg: Config, map_name: str, images: bool = False) -> Path | None:
    """Copy the style review's data (and with images=True its views) to the website."""
    build = cfg.path("build_dir") / map_name
    src = build / "style"
    if not (src / "index.json").is_file():
        return None
    out = site_dir(cfg, map_name)
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if (src / name).is_file():
            shutil.copy2(src / name, out / name)
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


MINIMAP = 512  # px, longest side


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


def section(cfg: Config, map_name: str) -> str:
    """The map page's section (empty if the map has no style review yet)."""
    if publish(cfg, map_name, images=True) is None:
        return ""
    return (
        "<section class='panel' id='style'><h2>Style review <span class='muted small'>– every "
        "area, chokepoint and landmark at eye height, judged against the art direction</span></h2>"
        "<div id='style-progress' class='small'></div><div id='style-summary'></div>"
        "<div id='style-grid' class='style-grid'></div></section>"
    )
