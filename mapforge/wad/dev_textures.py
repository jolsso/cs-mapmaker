"""Generate assets/wads/mapforge_dev.wad: procedural graybox textures (own work, CC0).

Base set (DEV_FLOOR/WALL/CEIL/CRATE), tool textures the compiler treats by name (CLIP,
ORIGIN, AAATRIGGER, SKY), entity textures (DEV_GLASS, DEV_DOOR, DEV_LADDER), zone tints of
floor/wall/ceiling (DEV_FLOOR_<ZONE> ..., for callouts: one colour family per zone) and a few
landmark materials (DEV_METAL, DEV_BRICK, DEV_CONCRETE, DEV_WOOD).

Usage: python -m mapforge.wad.dev_textures
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from mapforge.config import load_config
from mapforge.wad.wad3 import Texture, write_wad3

WAD_NAME = "mapforge_dev.wad"
SIZE = 128  # 128 units per tile at scale 1

# index: RGB
PALETTE_COLORS = {
    0: (0, 0, 0),
    1: (150, 150, 150),  # floor base
    2: (110, 110, 110),  # floor lines
    3: (180, 170, 150),  # wall base
    4: (140, 130, 115),  # wall lines
    5: (90, 90, 95),  # ceiling base
    6: (70, 70, 75),  # ceiling lines
    7: (230, 120, 40),  # accent (tile corner marker)
    8: (150, 105, 60),  # crate base
    9: (105, 70, 38),  # crate planks
    10: (120, 160, 210),  # sky
    11: (240, 140, 20),  # trigger (tool texture, stripped by the compiler)
    12: (170, 200, 215),  # glass
    13: (220, 235, 245),  # glass highlight
    14: (95, 75, 55),  # door leaf
    15: (60, 45, 30),  # door frame / ladder rungs
    16: (120, 120, 125),  # metal
    17: (85, 85, 92),  # metal seams
    18: (150, 70, 55),  # brick
    19: (110, 105, 100),  # mortar
    20: (135, 130, 120),  # concrete
    21: (115, 110, 102),  # concrete speckle
    22: (160, 120, 75),  # wood
    23: (125, 90, 55),  # wood grain
    24: (200, 60, 200),  # tool: clip (magenta)
    25: (240, 200, 40),  # tool: origin
}

# Zone tints: a multiplier on the base floor/wall/ceiling colours (one family per zone).
ZONE_TINTS = {
    "RED": (1.15, 0.80, 0.75),
    "BLUE": (0.78, 0.90, 1.18),
    "GREEN": (0.82, 1.10, 0.82),
    "SAND": (1.12, 1.02, 0.80),
    "GREY": (0.92, 0.92, 0.95),
}


def palette(tint: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> np.ndarray:
    pal = np.zeros((256, 3), dtype=np.uint8)
    for idx, rgb in PALETTE_COLORS.items():
        scale = tint if 1 <= idx <= 6 else (1.0, 1.0, 1.0)
        pal[idx] = [min(255, round(c * s)) for c, s in zip(rgb, scale, strict=True)]
    return pal


def grid(base: int, line: int, minor: int = 16, major: int = 64) -> np.ndarray:
    """Base colour with 1px lines every `minor` px and 2px lines every `major` px."""
    img = np.full((SIZE, SIZE), base, dtype=np.uint8)
    coords = np.arange(SIZE)
    minor_mask = coords % minor == 0
    major_mask = (coords % major == 0) | (coords % major == major - 1)
    for mask in (minor_mask, major_mask):
        img[mask, :] = line
        img[:, mask] = line
    img[:4, :4] = 7  # orientation marker in the tile corner
    return img


def crate() -> np.ndarray:
    """Plank crate: frame plus a diagonal brace, so cover reads as cover in renders."""
    img = np.full((SIZE // 2, SIZE // 2), 8, dtype=np.uint8)
    img[:4, :] = img[-4:, :] = img[:, :4] = img[:, -4:] = 9
    for i in range(SIZE // 2):
        img[i, max(0, i - 2) : i + 2] = 9
    return img


def glass() -> np.ndarray:
    img = np.full((64, 64), 12, dtype=np.uint8)
    for i in range(64):
        img[i, max(0, i - 20) : max(0, i - 16)] = 13  # a highlight streak
    img[:2, :] = img[-2:, :] = img[:, :2] = img[:, -2:] = 15
    return img


def door() -> np.ndarray:
    img = np.full((64, 128), 14, dtype=np.uint8)
    img[:4, :] = img[-4:, :] = img[:, :4] = img[:, -4:] = 15
    img[60 : 68 - 4, 40:48] = 7  # handle
    return img


def ladder() -> np.ndarray:
    img = np.zeros((32, 64), dtype=np.uint8)  # dark backing
    img[:, :4] = img[:, -4:] = 15  # rails
    img[::16, :] = 15  # rungs every 16 units
    img[1::16, :] = 15
    return img


def pattern(base: int, line: int, kind: str) -> np.ndarray:
    img = np.full((64, 64), base, dtype=np.uint8)
    if kind == "metal":
        img[::32, :] = line
        img[:, ::32] = line
        img[4::32, 4::32] = 13  # rivets
    elif kind == "brick":
        for r in range(0, 64, 16):
            img[r, :] = line
            shift = 0 if (r // 16) % 2 == 0 else 16
            img[r : r + 16, shift::32] = line
    elif kind == "concrete":
        rng = np.random.default_rng(7)  # deterministic speckle
        img[rng.random((64, 64)) < 0.08] = line
        img[::64, :] = line
    elif kind == "wood":
        for c in range(0, 64, 16):
            img[:, c] = line
        img[::5, 3::16] = line
    return img


def dev_textures() -> list[Texture]:
    pal = palette()
    out = [
        Texture("DEV_FLOOR", grid(1, 2), pal),
        Texture("DEV_WALL", grid(3, 4), pal),
        Texture("DEV_CEIL", grid(5, 6, minor=32), pal),
        Texture("DEV_CRATE", crate(), pal),
        Texture("SKY", np.full((SIZE, SIZE), 10, dtype=np.uint8), pal),
        Texture("AAATRIGGER", np.full((16, 16), 11, dtype=np.uint8), pal),
        Texture("CLIP", np.full((16, 16), 24, dtype=np.uint8), pal),
        Texture("ORIGIN", np.full((16, 16), 25, dtype=np.uint8), pal),
        Texture("DEV_GLASS", glass(), pal),
        Texture("DEV_DOOR", door(), pal),
        Texture("DEV_LADDER", ladder(), pal),
        Texture("DEV_METAL", pattern(16, 17, "metal"), pal),
        Texture("DEV_BRICK", pattern(18, 19, "brick"), pal),
        Texture("DEV_CONCRETE", pattern(20, 21, "concrete"), pal),
        Texture("DEV_WOOD", pattern(22, 23, "wood"), pal),
    ]
    for zone, tint in ZONE_TINTS.items():
        zp = palette(tint)
        out += [
            Texture(f"DEV_FLOOR_{zone}", grid(1, 2), zp),
            Texture(f"DEV_WALL_{zone}", grid(3, 4), zp),
            Texture(f"DEV_CEIL_{zone}", grid(5, 6, minor=32), zp),
        ]
    return out


def main() -> int:
    out: Path = load_config().wad_dirs[0] / WAD_NAME
    write_wad3(out, dev_textures())
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
