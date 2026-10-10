"""Generate assets/wads/mapforge_dev.wad: procedural graybox textures (own work, CC0).

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
}


def palette() -> np.ndarray:
    pal = np.zeros((256, 3), dtype=np.uint8)
    for idx, rgb in PALETTE_COLORS.items():
        pal[idx] = rgb
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


def dev_textures() -> list[Texture]:
    pal = palette()
    return [
        Texture("DEV_FLOOR", grid(1, 2), pal),
        Texture("DEV_WALL", grid(3, 4), pal),
        Texture("DEV_CEIL", grid(5, 6, minor=32), pal),
        Texture("DEV_CRATE", crate(), pal),
        Texture("SKY", np.full((SIZE, SIZE), 10, dtype=np.uint8), pal),
        Texture("AAATRIGGER", np.full((16, 16), 11, dtype=np.uint8), pal),
    ]


def crate() -> np.ndarray:
    """Plank crate: frame plus a diagonal brace, so cover reads as cover in renders."""
    img = np.full((SIZE // 2, SIZE // 2), 8, dtype=np.uint8)
    img[:4, :] = img[-4:, :] = img[:, :4] = img[:, -4:] = 9
    for i in range(SIZE // 2):
        img[i, max(0, i - 2) : i + 2] = 9
    return img


def main() -> int:
    out: Path = load_config().wad_dirs[0] / WAD_NAME
    write_wad3(out, dev_textures())
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
