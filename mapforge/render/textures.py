"""Texture pixels for a BSP: embedded miptex first, then WAD3 files by name."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from mapforge.bsp.reader import Bsp, miptex_pixels

MISSING = "missing"


class WadIndex:
    """Lazy name -> miptex lookup over a list of WAD3 files (first match wins)."""

    def __init__(self, wads: list[Path]) -> None:
        self.entries: dict[str, tuple[Path, int]] = {}
        self._data: dict[Path, bytes] = {}
        for wad in wads:
            try:
                head = wad.read_bytes()
            except OSError:
                continue
            if head[:4] not in (b"WAD3", b"WAD2"):
                continue
            count, dir_offset = struct.unpack_from("<ii", head, 4)
            for i in range(count):
                off = dir_offset + i * 32
                filepos, _, _, typ = struct.unpack_from("<iiiB", head, off)
                name = head[off + 16 : off + 32].split(b"\0", 1)[0].decode("ascii", "replace")
                if typ == 0x43:
                    self.entries.setdefault(name.upper(), (wad, filepos))
            self._data[wad] = head

    def get(self, name: str) -> tuple[np.ndarray, np.ndarray] | None:
        hit = self.entries.get(name.upper())
        if hit is None:
            return None
        wad, pos = hit
        return miptex_pixels(self._data[wad], pos)


def wad_search_paths(bsp_path: Path, extra_dirs: list[Path]) -> list[Path]:
    """WADs next to the map's mod (../*.wad), in extra dirs, and in sibling mod dirs."""
    dirs = [bsp_path.parent.parent, *extra_dirs]
    wads: list[Path] = []
    for d in dirs:
        if d.is_dir():
            wads += sorted(d.glob("*.wad")) + sorted(d.glob("*.WAD"))
    seen: set[Path] = set()
    return [w for w in wads if not (w in seen or seen.add(w))]


def texture_rgba(bsp: Bsp, index: int, wads: WadIndex) -> tuple[np.ndarray, str]:
    """(h, w, 4) uint8 RGBA for texture `index` and its source ('bsp', 'wad' or 'missing').

    Palette index 255 is transparent in '{' textures (alpha-tested in the engine).
    """
    tex = bsp.textures[index]
    got = bsp.texture_pixels(index)
    source = "bsp"
    if got is None:
        got = wads.get(tex.name)
        source = "wad"
    if got is None:
        size = (max(tex.height, 16), max(tex.width, 16))
        yy, xx = np.indices(size)
        check = ((yy // 8 + xx // 8) % 2).astype(np.uint8)
        rgba = np.zeros((*size, 4), dtype=np.uint8)
        rgba[..., 0] = 200 * check + 40
        rgba[..., 2] = 200 * check + 40
        rgba[..., 3] = 255
        return rgba, MISSING
    indices, palette = got
    rgba = np.empty((*indices.shape, 4), dtype=np.uint8)
    rgba[..., :3] = palette[indices]
    rgba[..., 3] = 255
    if tex.name.startswith("{"):
        rgba[indices == 255, 3] = 0
    return rgba, source
