"""Read YaPB's navigation graph (build/<map>/yapb/<sha>.graph) to see where bots can go.

File: a 24-byte header (magic "BPAY", version, options, node count, compressed size,
uncompressed size), the node array compressed with ULZ (YaPB's LZ77 variant), then an
optional extension header (author etc.). Each node is `struct Path` (220 bytes in graph
version 2): number, flags, origin, start, end, radius, light, display, then links.

Usage: python -m mapforge.simulate.yapbgraph build/<map>/yapb/<sha>.graph
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = b"BPAY"
HEADER = struct.Struct("<4siiiii")
NODE_SIZE = 220
MAX_LINKS = 8
LINK_OFFSET, LINK_STRIDE = 74, 20


def ulz_decompress(data: bytes, out_len: int) -> bytes:
    """ULZ decoder (token: 3 bits literal run, 1 bit distance high bit, 4 bits match length)."""
    out = bytearray()
    ip, end = 0, len(data)

    def varint() -> int:
        nonlocal ip
        val, shift = 0, 0
        while shift <= 21:
            c = data[ip]
            ip += 1
            val += c << shift
            if c < 128:
                break
            shift += 7
        return val

    while ip < end:
        token = data[ip]
        ip += 1
        if token >= 32:
            run = token >> 5
            if run == 7:
                run += varint()
            out += data[ip : ip + run]
            ip += run
            if ip >= end:
                break
        length = (token & 15) + 4
        if length == 15 + 4:
            length += varint()
        dist = ((token & 16) << 12) + data[ip] + (data[ip + 1] << 8)
        ip += 2
        start = len(out) - dist
        if start < 0:
            raise ValueError("corrupt ULZ stream (distance before start)")
        for i in range(length):  # may overlap: byte by byte
            out.append(out[start + i])
    if len(out) != out_len:
        raise ValueError(f"ULZ: got {len(out)} bytes, header says {out_len}")
    return bytes(out)


@dataclass
class Graph:
    version: int
    origins: np.ndarray  # (n, 3)
    flags: np.ndarray  # (n,)
    links: list[list[int]]  # per node: indices of linked nodes


def read_graph(path: Path) -> Graph:
    raw = path.read_bytes()
    magic, version, _options, count, csize, usize = HEADER.unpack_from(raw, 0)
    if magic != MAGIC:
        raise ValueError(f"{path}: not a YaPB graph (magic {magic!r})")
    body = ulz_decompress(raw[HEADER.size : HEADER.size + csize], usize)
    size = usize // count if count else NODE_SIZE
    origins, flags, links = [], [], []
    for i in range(count):
        rec = body[i * size : (i + 1) * size]
        _num, flg = struct.unpack_from("<ii", rec, 0)
        origins.append(struct.unpack_from("<3f", rec, 8))
        flags.append(flg)
        # links: MAX_LINKS records of LINK_STRIDE bytes from LINK_OFFSET, int16 node index
        # first (-1 = none). Found empirically on YaPB 4.4 graphs: with these, link lengths
        # match the analyser's node distance (median 80 at distance 80)
        out = []
        for k in range(MAX_LINKS):
            idx = struct.unpack_from("<h", rec, LINK_OFFSET + k * LINK_STRIDE)[0]
            if 0 <= idx < count:
                out.append(idx)
        links.append(out)
    return Graph(version, np.array(origins), np.array(flags), links)


def reachable(g: Graph, starts: np.ndarray, radius: float = 160) -> np.ndarray:
    """Bool mask of nodes reachable along links from any node within `radius` of a start point."""
    seen = np.zeros(len(g.origins), dtype=bool)
    if not len(starts) or not len(g.origins):
        return seen
    d = np.linalg.norm(g.origins[None, :, :2] - np.asarray(starts)[:, None, :2], axis=2)
    queue = list(np.flatnonzero((d < radius).any(axis=0)))
    seen[queue] = True
    while queue:
        i = queue.pop()
        for j in g.links[i]:
            if not seen[j]:
                seen[j] = True
                queue.append(j)
    return seen


def site_coverage(g: Graph, bsp, t_starts: np.ndarray) -> dict[str, dict[str, int]]:
    """Per bomb site: graph nodes in it, and how many of those T can reach along links."""
    from mapforge.validate.walk import bomb_sites, site_labels

    ok = reachable(g, t_starts)
    out = {}
    for boxes, label in zip(bomb_sites(bsp), site_labels(bsp), strict=True):
        inside = np.zeros(len(g.origins), dtype=bool)
        for lo, hi in boxes:
            inside |= np.all((g.origins >= lo - 32) & (g.origins <= hi + 32), axis=1)
        out[label] = {"nodes": int(inside.sum()), "reachable_from_t": int((inside & ok).sum())}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("graph", type=Path)
    args = ap.parse_args(argv)
    g = read_graph(args.graph)
    o = g.origins
    span = ", ".join(f"{a} {o[:, i].min():.0f}..{o[:, i].max():.0f}" for i, a in enumerate("xyz"))
    print(f"version {g.version}, {len(o)} nodes; {span}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
