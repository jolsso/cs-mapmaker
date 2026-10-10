import struct

import numpy as np
import pytest

from mapforge.wad.dev_textures import dev_textures, palette
from mapforge.wad.wad3 import MIPTEX_TYPE, Texture, build_mips, read_wad3, write_wad3


def test_dev_wad_roundtrip(tmp_path):
    path = tmp_path / "dev.wad"
    textures = dev_textures()
    write_wad3(path, textures)

    assert path.read_bytes()[:4] == b"WAD3"
    entries = read_wad3(path)
    assert [e.name for e in entries] == [t.name for t in textures]
    for e in entries:
        assert e.type == MIPTEX_TYPE
        assert e.width % 16 == 0 and e.height % 16 == 0


def test_miptex_lump_layout(tmp_path):
    path = tmp_path / "one.wad"
    tex = Texture("T", np.ones((32, 16), dtype=np.uint8), palette())
    write_wad3(path, [tex])
    data = path.read_bytes()
    _, dir_offset = struct.unpack_from("<ii", data, 4)
    filepos, disksize, size = struct.unpack_from("<iii", data, dir_offset)
    w, h, *offsets = struct.unpack_from("<II4I", data, filepos + 16)
    assert (w, h) == (16, 32)
    pixels = [w * h >> (2 * i) for i in range(4)]
    assert offsets == [40, 40 + pixels[0], 40 + sum(pixels[:2]), 40 + sum(pixels[:3])]
    assert disksize == size == 40 + sum(pixels) + 2 + 768 + 2
    assert struct.unpack_from("<H", data, filepos + 40 + sum(pixels))[0] == 256


def test_mips_only_use_source_colours():
    tex = dev_textures()[0]
    mips = build_mips(tex.indices, tex.palette)
    assert [m.shape for m in mips] == [(128, 128), (64, 64), (32, 32), (16, 16)]
    used = set(np.unique(tex.indices))
    for m in mips[1:]:
        assert set(np.unique(m)) <= used


@pytest.mark.parametrize("shape", [(15, 16), (16, 24), (0, 16)])
def test_rejects_bad_dimensions(shape):
    with pytest.raises(ValueError):
        Texture("BAD", np.zeros(shape, dtype=np.uint8), palette())
