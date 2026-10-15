"""Repeating textures (play tests 2026-10-15): a texture with a feature that appears once per tile
- a window, a door, bullet holes, a stain, a brick patch, a pipe - turns into wallpaper when it
covers a big surface. Pixel statistics cannot tell those from fine textures (OUT_WALL7 and its
bullet-hole variant OUT_WALL7B measure nearly the same), so a vision model rates each texture
from a 3x3 tiling of it, the way it looks on a wall; the ratings are data in the repo
(config/texture_risk.json), so generating a map stays deterministic.

  rate       textures the map uses (+ the family siblings of high-risk ones) that have no rating
             yet -> local vision model (style.local), six previews per request
  tame       in the generator: a face showing more than `max_tiles` tiles of a high-risk texture
             (across either axis) gets the texture's calm sibling instead - its family (OUT_WALL7B
             -> OUT_WALL7, BRICK05-2 -> BRICK05, CSTRIKE_WR4CCWD -> CSTRIKE_WR4CC*) with the same
             size and a low rating; small faces keep the feature (an accent, a single window)
  findings   for validation: what still repeats (no calm sibling, or unrated)

CLI: uv run python -m mapforge.wad.repeat --map NAME [--rate] [--names TEX ...]
"""

from __future__ import annotations

import argparse
import base64
import functools
import io
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

from mapforge.config import Config, load_config
from mapforge.mapfile.geometry import brush_geometry
from mapforge.mapfile.parser import MapFile, read_map
from mapforge.wad.catalog import _entries, wad_files

RISKS = ("low", "medium", "high")
MAX_TILES = {"high": 3.0, "medium": 6.0}  # tiles across a face before it reads as wallpaper
NO_TILE = re.compile(r"^(SKY|CLIP|NULL|HINT|SKIP|ORIGIN|AAATRIGGER|BEVEL|\{|!|~)", re.I)

RATE_SCHEMA = {
    "type": "object",
    "properties": {
        "textures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "risk": {"type": "string", "enum": list(RISKS)},
                    "feature": {"type": "string"},
                },
                "required": ["n", "risk", "feature"],
            },
        }
    },
    "required": ["textures"],
}

RATE_PROMPT = """Each numbered panel shows ONE game texture tiled 3x3, exactly as it repeats when it covers a big wall or floor in a Counter-Strike 1.6 map. For each panel, judge how obvious the repetition is:
- high: a distinct feature appears once per tile and forms a visible grid of copies - a window, door, vent, sign, pipe, bullet holes, a stain, a crack, a brick patch, a logo, a big blotch. Small features count too: a few bullet holes or dark specks in the same spot of every tile form an obvious grid on a wall.
- medium: no single object, but blotches or shading that you can notice repeating at the tile size.
- low: a regular building material whose pattern is meant to repeat (bricks, blocks, planks, tiles, plates with seams, grating, corrugation) or even noise; the tile seams do not show.
feature: name the repeating thing in a few words (empty for low). Answer only with JSON, one entry per panel."""


# --- textures -------------------------------------------------------------------------------


def texture_pixels(names: Iterable[str], dirs: Iterable[Path]) -> dict[str, np.ndarray]:
    """Name (upper case) -> RGB pixels (h, w, 3) from the first WAD holding it."""
    from mapforge.bsp.reader import miptex_pixels

    want, out = {n.upper() for n in names}, {}
    for wad in wad_files(dirs):
        for name, off, data in _entries(wad):
            if name in want and name not in out:
                px, pal = miptex_pixels(data, off)
                out[name] = np.ascontiguousarray(pal[px])
    return out


def texture_sizes(dirs: Iterable[Path]) -> dict[str, tuple[int, int]]:
    """Name -> (w, h) of every texture in the WADs (first WAD wins; cached per WAD set)."""
    return dict(_sizes(tuple(wad_files(dirs))))


@functools.lru_cache(maxsize=4)
def _sizes(wads: tuple[Path, ...]) -> dict[str, tuple[int, int]]:
    import struct

    out: dict[str, tuple[int, int]] = {}
    for wad in wads:
        for name, off, data in _entries(wad):
            if name not in out:
                w, h = struct.unpack_from("<II", data, off + 16)
                out[name] = (w, h)
    return out


def root(name: str) -> str:
    """A texture's family root: no random-tiling prefix (-0..-9, +0..+9), no variant suffix
    (OUT_WALL7B -> OUT_WALL7, BRICK05-2 -> BRICK05, CSTRIKE_WR4CCWD -> CSTRIKE_WR4CC)."""
    n = re.sub(r"^[-+][0-9A-J]", "", name.upper())
    return re.sub(r"(?:[-_]?\d{1,2}|[A-Z]{1,2})$", "", n) or n


def siblings(name: str, sizes: dict[str, tuple[int, int]]) -> list[str]:
    """Other textures of the same family and size (the family root itself included)."""
    r, size = root(name), sizes.get(name.upper())
    out = []
    for n, s in sizes.items():
        if n == name.upper() or s != size or NO_TILE.match(n):
            continue
        bare = re.sub(r"^[-+][0-9A-J]", "", n)
        if bare == r or root(n) == r:
            out.append(n)
    return sorted(out)


# --- ratings ---------------------------------------------------------------------------------


def risk_path(cfg: Config) -> Path:
    return cfg.root / "config" / "texture_risk.json"


def load_risk(cfg: Config) -> dict[str, dict[str, str]]:
    p = risk_path(cfg)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def calm_sibling(name: str, risk: dict, sizes: dict) -> str | None:
    """The family's calmest look-alike with the same size: the family root first when it is
    calmer than `name` (OUT_WALL7B -> OUT_WALL7, BRICK05-2 -> BRICK05: same material, no
    windows), else a low-risk member, else a medium one."""
    order = {"low": 0, "medium": 1, "high": 2}
    own = order.get((risk.get(name.upper()) or {}).get("risk"), 2)
    level = {s: order.get((risk.get(s) or {}).get("risk"), 3) for s in siblings(name, sizes)}
    r = root(name)
    base = [s for s in level if re.sub(r"^[-+][0-9A-J]", "", s) == r and level[s] < own]
    if base:
        return sorted(base, key=lambda s: (level[s], s))[0]
    for want in (0, 1):
        sib = sorted(s for s in level if level[s] == want and want < own)
        if sib:
            return min(sib, key=len)
    return None


def preview_sheet(pix: dict[str, np.ndarray], names: list[str], cell: int = 640):
    """Numbered 3x3 tilings of `names`, two rows of three -> PIL image."""
    from PIL import Image, ImageDraw

    cols = 3
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 24)), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for i, n in enumerate(names):
        img = Image.fromarray(np.tile(pix[n], (3, 3, 1)), "RGB")
        f = (cell - 8) / max(img.size)  # native pixels or larger: small features must show
        img = img.resize((int(img.width * f), int(img.height * f)), Image.NEAREST)
        x, y = (i % cols) * cell, (i // cols) * (cell + 24)
        draw.text((x + 6, y + 4), str(i + 1), fill=(255, 220, 80))
        sheet.paste(img, (x + 4, y + 22))
    return sheet


def rate(
    cfg: Config, names: Iterable[str], log=print, force: bool = False
) -> dict[str, dict[str, str]]:
    """Rate the textures that have no rating yet (all of them with `force`; local vision
    model) -> the updated ratings."""
    from mapforge.style.local import _post

    risk = load_risk(cfg)
    todo = sorted({n.upper() for n in names} - (set() if force else set(risk)))
    pix = texture_pixels(todo, cfg.wad_dirs)
    todo = [n for n in todo if n in pix]
    lc = cfg.data["style"]["local"]
    for k in range(0, len(todo), 6):
        batch = todo[k : k + 6]
        buf = io.BytesIO()
        preview_sheet(pix, batch).save(buf, "PNG")
        body = {
            "model": lc["model"], "temperature": 0.1, "max_tokens": lc.get("max_tokens", 8000),
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "texture_risk", "schema": RATE_SCHEMA}},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": RATE_PROMPT},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}},
            ]}],
        }  # fmt: skip
        got = None
        for _ in range(3):
            resp = _post(
                lc["url"].rstrip("/") + "/chat/completions", body, lc.get("timeout_s", 600)
            )
            try:
                got = json.loads((resp["choices"][0]["message"].get("content") or "").strip())
                break
            except ValueError:
                body["max_tokens"] = int(body["max_tokens"] * 1.5)
        for g in (got or {}).get("textures", []):
            n = g.get("n", 0) - 1
            if 0 <= n < len(batch) and g.get("risk") in RISKS:
                risk[batch[n]] = {"risk": g["risk"], "feature": g.get("feature", ""),
                                  "by": lc["model"]}  # fmt: skip
                log(f"  {batch[n]:20s} {g['risk']:6s} {g.get('feature', '')}")
        risk_path(cfg).write_text(json.dumps(dict(sorted(risk.items())), indent=1) + "\n",
                                  encoding="utf-8", newline="\n")  # fmt: skip
    return risk


# --- faces -----------------------------------------------------------------------------------


def face_tiles(brush, sizes: dict[str, tuple[int, int]]) -> list[tuple[int, float, float]]:
    """(face index, tiles along u, tiles along v) for every face of a brush."""
    geo = brush_geometry(brush)
    out = []
    for i, f in enumerate(brush.faces):
        size = sizes.get(f.texture.upper())
        pts = geo.face_vertices[i]
        if size is None or len(pts) < 3:
            continue
        u, v = np.array(f.u_axis[:3]), np.array(f.v_axis[:3])
        su, sv = (abs(f.scale[0]) or 1), (abs(f.scale[1]) or 1)
        pu, pv = pts @ u / su, pts @ v / sv
        out.append((i, float(np.ptp(pu)) / size[0], float(np.ptp(pv)) / size[1]))
    return out


def random_tiled(name: str, sizes: dict) -> bool:
    """A -0NAME texture with -1NAME etc. beside it: the game picks a variant per tile (random
    tiling), so a fixed grid of copies does not form. ⚠️ VERIFY in the GL renderer."""
    m = re.match(r"^-([0-9])(.+)$", name.upper())
    return bool(m) and any(f"-{k}{m.group(2)}" in sizes for k in "0123456789" if k != m.group(1))


def _risky_faces(mapfile: MapFile, risk: dict, sizes: dict):
    for b in mapfile.brushes():
        for i, tu, tv in face_tiles(b, sizes):
            t = b.faces[i].texture.upper()
            if random_tiled(t, sizes):
                continue
            level = (risk.get(t) or {}).get("risk")
            if level in MAX_TILES and max(tu, tv) > MAX_TILES[level] + 0.05:  # float slack
                yield b, i, t, level, max(tu, tv)


def tame(mapfile: MapFile, cfg: Config) -> dict[str, Any]:
    """Swap high-risk textures on big faces for their calm sibling (in place) -> a report:
    {swapped: {TEX: [sibling, faces]}, kept: {TEX: [level, faces, most tiles]}}."""
    from dataclasses import replace

    risk, sizes = load_risk(cfg), texture_sizes(cfg.wad_dirs)
    swapped: dict[str, list] = {}
    kept: dict[str, list] = {}
    calm: dict[str, str | None] = {}
    for b, i, t, level, tiles in list(_risky_faces(mapfile, risk, sizes)):
        if level == "high":
            if t not in calm:
                calm[t] = calm_sibling(t, risk, sizes)
            if calm[t]:
                b.faces[i] = replace(b.faces[i], texture=calm[t])
                swapped.setdefault(t, [calm[t], 0])[1] += 1
                continue
        k = kept.setdefault(t, [level, 0, 0.0])
        k[1] += 1
        k[2] = round(max(k[2], tiles), 1)
    used = {f.texture.upper() for b in mapfile.brushes() for f in b.faces}
    own = set(_sizes(tuple(wad_files(list(cfg.wad_dirs)[:1]))))  # our dev textures: flat grids
    unrated = sorted(t for t in used
                     if t not in risk and t not in own and not NO_TILE.match(t) and t in sizes)  # fmt: skip
    return {"swapped": swapped, "kept": kept, "unrated": unrated}


def findings(mapfile: MapFile, cfg: Config) -> list[dict[str, Any]]:
    """Validation: textures that still repeat visibly on big faces - high risk without a calm
    sibling, or medium risk (not swapped automatically: a suggestion only)."""
    rep = tame(mapfile, cfg)  # on the generated map: whatever is left
    risk, sizes = load_risk(cfg), texture_sizes(cfg.wad_dirs)
    out = []
    for t, (level, faces, tiles) in sorted(rep["kept"].items()):
        calm = calm_sibling(t, risk, sizes)
        what = (
            f"try {calm} (calmer, same family) or break the surface up"
            if calm
            else "no calmer texture in its family: choose another or break the surface up"
        )
        out.append({"severity": "warning", "rule": "repeating_texture",
                    "message": f"{t} ({level} repeat risk: {(risk.get(t) or {}).get('feature') or 'pattern'}) "
                               f"shows up to {tiles} tiles across on {faces} face(s); {what}"})  # fmt: skip
    if rep["unrated"]:
        out.append({"severity": "info", "rule": "repeating_texture",
                    "message": f"{len(rep['unrated'])} texture(s) without a repeat rating "
                               f"(./mf repeats MAP=... -- --rate): {rep['unrated'][:8]}"})  # fmt: skip
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map")
    ap.add_argument("--names", nargs="*", default=[])
    ap.add_argument("--rate", action="store_true", help="rate unrated textures (local model)")
    ap.add_argument("--force", action="store_true", help="with --rate: rate the named again")
    args = ap.parse_args(argv)
    cfg = load_config()
    names = {n.upper() for n in args.names}
    if args.map:
        mf = read_map(cfg.path("maps_dir") / args.map / "src" / f"{args.map}.map")
        names |= {f.texture.upper() for b in mf.brushes() for f in b.faces}
    names = {n for n in names if not NO_TILE.match(n)}
    if args.rate:
        risk = rate(cfg, names, force=args.force)
        sizes = texture_sizes(cfg.wad_dirs)
        fam = {s for n in names if (risk.get(n) or {}).get("risk") == "high"
               for s in siblings(n, sizes)}  # fmt: skip
        rate(cfg, fam)  # the calm sibling needs a rating too
    risk = load_risk(cfg)
    for n in sorted(names):
        r = risk.get(n) or {}
        print(f"{n:20s} {r.get('risk', '?'):6s} {r.get('feature', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
