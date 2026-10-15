"""Contact sheets for the style review: several camera views per image, grouped by zone.

A model is billed per pixel, and an image is scaled down to about 1.15 megapixels anyway, so six
views in one 1920x760 sheet cost about as much as one full-size view. Reading few sheets in one
turn also keeps the reviewer's context from growing with every image.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

TILE = (640, 360)  # one view on a sheet
COLS, ROWS = 3, 2  # six views per sheet
LABEL = 20  # px of caption above each view


def image_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def make_sheets(src: Path, images: list[dict[str, Any]], out: Path) -> list[dict[str, Any]]:
    """Sheets of the given images (index entries with file/zone), one zone per sheet run, written
    to out/; -> [{file, zone, tiles: [{n, image, subject}]}]. Old sheets in out/ are removed."""
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    by_zone: dict[str, list[dict]] = {}
    for i in images:
        by_zone.setdefault(i.get("zone") or "other", []).append(i)
    sheets = []
    per = COLS * ROWS
    w, h = TILE
    for zone in sorted(by_zone):
        group = by_zone[zone]
        for k in range(0, len(group), per):
            part = group[k : k + per]
            sheet = Image.new("RGB", (w * COLS, (h + LABEL) * ROWS), (18, 18, 18))
            draw = ImageDraw.Draw(sheet)
            tiles = []
            for j, img in enumerate(part):
                x, y = (j % COLS) * w, (j // COLS) * (h + LABEL)
                view = Image.open(src / img["file"]).convert("RGB").resize(TILE)
                sheet.paste(view, (x, y + LABEL))
                draw.text((x + 6, y + 4), f"{j + 1}: {img['file'][:-4]}", fill=(255, 255, 255))
                tiles.append({"n": j + 1, "image": img["file"], "subject": img.get("subject", "")})
            name = f"{zone}_{k // per + 1}.png"
            sheet.save(out / name)
            sheets.append({"file": name, "zone": zone, "tiles": tiles})
    return sheets
