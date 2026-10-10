"""Minimal WAD3 (Half-Life texture archive) reader/writer.

Layout:
  header    "WAD3", int32 num_entries, int32 dir_offset
  lumps     miptex: name[16], u32 width, u32 height, u32 offsets[4],
            4 mip levels of 8-bit indices, u16 palette size (256), 256*RGB, 2 pad bytes
  directory per entry: i32 filepos, i32 disksize, i32 size, u8 type (0x43),
            u8 compression (0), u16 pad, name[16]
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MIPTEX_TYPE = 0x43
MIP_LEVELS = 4
NAME_LEN = 16


@dataclass(frozen=True)
class Texture:
    name: str
    indices: np.ndarray  # (height, width) uint8 palette indices, mip level 0
    palette: np.ndarray  # (256, 3) uint8

    def __post_init__(self) -> None:
        h, w = self.indices.shape
        if w % 16 or h % 16 or w == 0 or h == 0:
            raise ValueError(f"{self.name}: dimensions must be multiples of 16, got {w}x{h}")
        if not 0 < len(self.name) < NAME_LEN:
            raise ValueError(f"Texture name must be 1-15 chars: {self.name!r}")
        if self.palette.shape != (256, 3):
            raise ValueError(f"{self.name}: palette must be 256x3")


def _encode_name(name: str) -> bytes:
    return name.encode("ascii").ljust(NAME_LEN, b"\0")


def build_mips(indices: np.ndarray, palette: np.ndarray) -> list[np.ndarray]:
    """Box-filter mip 0 in RGB and map each level back to the nearest used palette entry."""
    used = np.unique(indices)
    used_rgb = palette[used].astype(np.float32)
    rgb = palette[indices].astype(np.float32)
    mips = [indices.astype(np.uint8)]
    for level in range(1, MIP_LEVELS):
        f = 1 << level
        h, w = indices.shape[0] // f, indices.shape[1] // f
        down = rgb.reshape(h, f, w, f, 3).mean(axis=(1, 3))
        dist = ((down[:, :, None, :] - used_rgb[None, None, :, :]) ** 2).sum(axis=-1)
        mips.append(used[dist.argmin(axis=-1)].astype(np.uint8))
    return mips


def encode_miptex(tex: Texture) -> bytes:
    h, w = tex.indices.shape
    mips = build_mips(tex.indices, tex.palette)
    header_size = NAME_LEN + 4 * 2 + 4 * MIP_LEVELS
    offsets = []
    pos = header_size
    for m in mips:
        offsets.append(pos)
        pos += m.size
    out = bytearray(_encode_name(tex.name))
    out += struct.pack("<II4I", w, h, *offsets)
    for m in mips:
        out += m.tobytes()
    out += struct.pack("<H", 256)
    out += tex.palette.astype(np.uint8).tobytes()
    out += b"\0\0"
    return bytes(out)


def write_wad3(path: Path, textures: list[Texture]) -> None:
    names = [t.name.upper() for t in textures]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate texture names")
    body = bytearray()
    entries = []
    for tex in textures:
        lump = encode_miptex(tex)
        entries.append((12 + len(body), len(lump), tex.name))
        body += lump
    directory = bytearray()
    for filepos, size, name in entries:
        directory += struct.pack("<iiiBBH", filepos, size, size, MIPTEX_TYPE, 0, 0)
        directory += _encode_name(name)
    header = b"WAD3" + struct.pack("<ii", len(entries), 12 + len(body))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + body + directory)


@dataclass(frozen=True)
class WadEntry:
    name: str
    width: int
    height: int
    type: int


def read_wad3(path: Path) -> list[WadEntry]:
    data = path.read_bytes()
    if data[:4] != b"WAD3":
        raise ValueError(f"{path}: not a WAD3 file")
    count, dir_offset = struct.unpack_from("<ii", data, 4)
    entries = []
    for i in range(count):
        off = dir_offset + i * 32
        filepos, _disk, _size, typ, _comp, _pad = struct.unpack_from("<iiiBBH", data, off)
        name = data[off + 16 : off + 32].split(b"\0", 1)[0].decode("ascii")
        width, height = struct.unpack_from("<II", data, filepos + NAME_LEN)
        entries.append(WadEntry(name=name, width=width, height=height, type=typ))
    return entries
