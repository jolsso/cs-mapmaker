"""Rewrite a BSP with a new entity lump (like ripent -import): geometry is untouched."""

from __future__ import annotations

import struct
from pathlib import Path

from mapforge.bsp.reader import BSP_VERSION, LUMPS


def serialize_entities(entities: list[dict[str, str]]) -> bytes:
    out = []
    for ent in entities:
        out.append("{\n" + "".join(f'"{k}" "{v}"\n' for k, v in ent.items()) + "}\n")
    return "".join(out).encode("utf-8") + b"\0"


def write_with_entities(src: Path, dst: Path, entities: list[dict[str, str]]) -> None:
    data = src.read_bytes()
    lumps = []
    for i in range(len(LUMPS)):
        off, length = struct.unpack_from("<ii", data, 4 + 8 * i)
        lumps.append(data[off : off + length])
    lumps[0] = serialize_entities(entities)
    header_size = 4 + 8 * len(LUMPS)
    body = bytearray()
    table = []
    for lump in lumps:
        while (header_size + len(body)) % 4:
            body += b"\0"
        table.append((header_size + len(body), len(lump)))
        body += lump
    header = struct.pack("<i", BSP_VERSION) + b"".join(struct.pack("<ii", o, n) for o, n in table)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(header + body)
