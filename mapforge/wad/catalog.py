"""Texture catalog over our own WADs and the game's standard WADs (paths.wad_dirs).

The game's WADs (cstrike/*.wad, valve/*.wad from the local Half-Life install, mounted read-only)
are only *referenced*: a map's worldspawn `wad` key names the WADs its textures come from, and
every client has them. They are never embedded (`wad.include` holds our own WADs only) and never
copied into the repo.

`wads_for(textures, dirs)` -> the WAD file names that provide a set of texture names (first match
in dirs order wins, so our own assets/wads shadow the game's) and the names found nowhere.

Usage: python -m mapforge.wad.catalog [--sheets]
  -> build/textures/catalog.json (wad -> textures with size and mean colour)
     and with --sheets one contact sheet per WAD (build/textures/<wad>.png) to pick textures from.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from mapforge.bsp.reader import miptex_pixels

MIPTEX = 0x43
# Textures every compiler knows without a WAD (sky and tool textures are in our dev WAD too).
NO_WAD = {"SKY", "NULL", "AAATRIGGER", "CLIP", "ORIGIN", "HINT", "SKIP", "BEVEL"}


def wad_files(dirs: Iterable[Path]) -> list[Path]:
    """Every *.wad in dirs, in dirs order (missing dirs are skipped)."""
    out: list[Path] = []
    for d in dirs:
        if d.is_dir():
            out += sorted(p for p in d.iterdir() if p.suffix.lower() == ".wad")
    return out


def _entries(wad: Path) -> list[tuple[str, int, bytes]]:
    """(name, offset, file bytes) of each miptex in a WAD3 file; [] if it is not one."""
    try:
        data = wad.read_bytes()
    except OSError:
        return []
    if data[:4] != b"WAD3":
        return []
    count, dir_offset = struct.unpack_from("<ii", data, 4)
    out = []
    for i in range(count):
        off = dir_offset + i * 32
        filepos, _, _, typ = struct.unpack_from("<iiiB", data, off)
        if typ == MIPTEX:
            name = data[off + 16 : off + 32].split(b"\0", 1)[0].decode("ascii", "replace")
            out.append((name.upper(), filepos, data))
    return out


def texture_index(dirs: Iterable[Path]) -> dict[str, str]:
    """Texture name (upper case) -> WAD file name; the first WAD in dirs order wins."""
    index: dict[str, str] = {}
    for wad in wad_files(dirs):
        for name, _, _ in _entries(wad):
            index.setdefault(name, wad.name)
    return index


def wads_for(textures: Iterable[str], dirs: Iterable[Path]) -> tuple[list[str], list[str]]:
    """(WAD file names providing the textures, in dirs order; texture names found nowhere)."""
    dirs = list(dirs)
    index = texture_index(dirs)
    order = {w.name: i for i, w in enumerate(wad_files(dirs))}
    used, missing = set(), []
    for t in sorted({t.upper() for t in textures}):
        if t in NO_WAD:
            continue
        if t in index:
            used.add(index[t])
        else:
            missing.append(t)
    return sorted(used, key=order.__getitem__), missing


def catalog(dirs: Iterable[Path]) -> dict[str, list[dict]]:
    """WAD file name -> [{name, size, rgb}] for every texture (mean colour of mip 0)."""
    out: dict[str, list[dict]] = {}
    for wad in wad_files(dirs):
        rows = []
        for name, off, data in _entries(wad):
            px, pal = miptex_pixels(data, off)
            rgb = pal[px].reshape(-1, 3).mean(axis=0)
            rows.append({"name": name, "size": [px.shape[1], px.shape[0]],
                         "rgb": [int(round(c)) for c in rgb]})  # fmt: skip
        if rows:
            out.setdefault(wad.name, rows)
    return out


def contact_sheet(wad: Path, out: Path, cell: int = 96, cols: int = 12) -> int:
    """A grid of a WAD's textures (each scaled into cell x cell) with their names; -> count."""
    from PIL import Image, ImageDraw

    entries = _entries(wad)
    if not entries:
        return 0
    rows = (len(entries) + cols - 1) // cols
    label = 14
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (name, off, data) in enumerate(entries):
        px, pal = miptex_pixels(data, off)
        img = Image.fromarray(np.ascontiguousarray(pal[px]), "RGB")
        img.thumbnail((cell - 4, cell - 4))
        x, y = (i % cols) * cell, (i // cols) * (cell + label)
        sheet.paste(img, (x + 2, y + 2))
        draw.text((x + 2, y + cell), name[:15], fill=(220, 220, 220))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    from mapforge.config import load_config

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sheets", action="store_true", help="also write one PNG per WAD")
    args = ap.parse_args(argv)
    cfg = load_config()
    out_dir = cfg.path("build_dir") / "textures"
    out_dir.mkdir(parents=True, exist_ok=True)
    cat = catalog(cfg.wad_dirs)
    (out_dir / "catalog.json").write_text(json.dumps(cat, indent=1), encoding="utf-8")
    if args.sheets:
        seen = set()
        for wad in wad_files(cfg.wad_dirs):
            if wad.name in cat and wad.name not in seen:
                seen.add(wad.name)
                contact_sheet(wad, out_dir / f"{wad.stem.lower()}.png")
    total = sum(len(v) for v in cat.values())
    print(f"textures: {total} in {len(cat)} WADs -> {out_dir / 'catalog.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
