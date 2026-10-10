"""GoldSrc BSP v30 reader. Struct layouts and lump order from HLSDK utils/common/bspfile.h."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BSP_VERSION = 30
LUMPS = (
    "entities", "planes", "textures", "vertexes", "visibility", "nodes", "texinfo", "faces",
    "lighting", "clipnodes", "leafs", "marksurfaces", "edges", "surfedges", "models",
)  # fmt: skip

CONTENTS_EMPTY = -1
CONTENTS_SOLID = -2

# Clip hull boxes (mins, maxs); hull 0 is a point.
HULL_SIZES = {
    1: ((-16, -16, -36), (16, 16, 36)),  # standing player
    2: ((-32, -32, -32), (32, 32, 32)),  # large monsters
    3: ((-16, -16, -18), (16, 16, 18)),  # crouching player
}

DPLANE = np.dtype([("normal", "<f4", 3), ("dist", "<f4"), ("type", "<i4")])
DNODE = np.dtype(
    [
        ("planenum", "<i4"),
        ("children", "<i2", 2),
        ("mins", "<i2", 3),
        ("maxs", "<i2", 3),
        ("firstface", "<u2"),
        ("numfaces", "<u2"),
    ]
)
DCLIPNODE = np.dtype([("planenum", "<i4"), ("children", "<i2", 2)])
DTEXINFO = np.dtype([("vecs", "<f4", (2, 4)), ("miptex", "<i4"), ("flags", "<i4")])
DFACE = np.dtype(
    [
        ("planenum", "<i2"),
        ("side", "<i2"),
        ("firstedge", "<i4"),
        ("numedges", "<i2"),
        ("texinfo", "<i2"),
        ("styles", "u1", 4),
        ("lightofs", "<i4"),
    ]
)
DLEAF = np.dtype(
    [
        ("contents", "<i4"),
        ("visofs", "<i4"),
        ("mins", "<i2", 3),
        ("maxs", "<i2", 3),
        ("firstmarksurface", "<u2"),
        ("nummarksurfaces", "<u2"),
        ("ambient_level", "u1", 4),
    ]
)
DMODEL = np.dtype(
    [
        ("mins", "<f4", 3),
        ("maxs", "<f4", 3),
        ("origin", "<f4", 3),
        ("headnode", "<i4", 4),
        ("visleafs", "<i4"),
        ("firstface", "<i4"),
        ("numfaces", "<i4"),
    ]
)
DEDGE = np.dtype([("v", "<u2", 2)])

_ENTITY_BLOCK = re.compile(r"\{([^{}]*)\}")
_KEYVALUE = re.compile(r'"([^"]*)"\s*"([^"]*)"')


@dataclass(frozen=True)
class Texture:
    name: str
    width: int
    height: int
    embedded: bool  # pixel data inside the BSP (vs. loaded from a WAD at runtime)


@dataclass
class Bsp:
    entities: list[dict[str, str]]
    planes: np.ndarray
    textures: list[Texture]
    vertices: np.ndarray  # (n, 3) float32
    visibility: bytes
    nodes: np.ndarray
    texinfo: np.ndarray
    faces: np.ndarray
    lighting: bytes
    clipnodes: np.ndarray
    leafs: np.ndarray
    marksurfaces: np.ndarray
    edges: np.ndarray
    surfedges: np.ndarray
    models: np.ndarray
    entity_bytes: int

    def counts(self) -> dict[str, int]:
        """Object counts per lump (texture/lighting/visibility/entities in bytes)."""
        return {
            "models": len(self.models),
            "planes": len(self.planes),
            "vertexes": len(self.vertices),
            "nodes": len(self.nodes),
            "texinfo": len(self.texinfo),
            "faces": len(self.faces),
            "clipnodes": len(self.clipnodes),
            "leafs": len(self.leafs),
            "visleafs": int(self.models[0]["visleafs"]) if len(self.models) else 0,
            "marksurfaces": len(self.marksurfaces),
            "edges": len(self.edges),
            "surfedges": len(self.surfedges),
            "textures": len(self.textures),
            "entities": len(self.entities),
            "entdata_bytes": self.entity_bytes,
            "lighting_bytes": len(self.lighting),
            "visibility_bytes": len(self.visibility),
        }

    # --- geometry -------------------------------------------------------------------------

    def face_vertices(self, face_index: int) -> np.ndarray:
        """Polygon vertices of a face, in winding order."""
        f = self.faces[face_index]
        se = self.surfedges[f["firstedge"] : f["firstedge"] + f["numedges"]]
        idx = np.where(se >= 0, self.edges["v"][np.abs(se), 0], self.edges["v"][np.abs(se), 1])
        return self.vertices[idx]

    def face_lightmap(self, face_index: int) -> np.ndarray | None:
        """RGB lightmap (h, w, 3) of a face's first light style, or None if it has none."""
        f = self.faces[face_index]
        if f["lightofs"] < 0 or f["styles"][0] == 255:
            return None
        w, h = self.lightmap_size(face_index)
        start = int(f["lightofs"])
        raw = np.frombuffer(self.lighting, dtype=np.uint8, count=w * h * 3, offset=start)
        return raw.reshape(h, w, 3)

    def lightmap_size(self, face_index: int) -> tuple[int, int]:
        """Lightmap samples (w, h): texture-space extents / 16, + 1 (as in the engine)."""
        f = self.faces[face_index]
        vecs = self.texinfo[f["texinfo"]]["vecs"].astype(np.float64)
        verts = self.face_vertices(face_index).astype(np.float64)
        st = verts @ vecs[:, :3].T + vecs[:, 3]
        lo = np.floor(st.min(axis=0) / 16)
        hi = np.ceil(st.max(axis=0) / 16)
        w, h = (hi - lo + 1).astype(int)
        return int(w), int(h)

    # --- collision ------------------------------------------------------------------------

    def point_contents(self, points: np.ndarray, hull: int = 0, model: int = 0) -> np.ndarray:
        """CONTENTS_* value for each point (n, 3) in a hull of a model (vectorised descent)."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        head = int(self.models[model]["headnode"][hull])
        normals = self.planes["normal"].astype(np.float64)
        dists = self.planes["dist"].astype(np.float64)
        tree = self.nodes if hull == 0 else self.clipnodes
        planenum = tree["planenum"]
        children = tree["children"].astype(np.int64)

        idx = np.full(len(pts), head, dtype=np.int64)
        active = idx >= 0
        while active.any():
            n = idx[active]
            p = planenum[n]
            d = np.einsum("ij,ij->i", pts[active], normals[p]) - dists[p]
            idx[active] = children[n, (d < 0).astype(np.int64)]
            active = idx >= 0
        if hull == 0:
            # negative child = -(leaf + 1)
            return self.leafs["contents"][-(idx + 1)].astype(np.int64)
        return idx


def _lump(data: bytes, i: int) -> bytes:
    offset, length = struct.unpack_from("<ii", data, 4 + 8 * i)
    return data[offset : offset + length]


def _array(raw: bytes, dtype: np.dtype) -> np.ndarray:
    if len(raw) % dtype.itemsize:
        raise ValueError(f"lump size {len(raw)} not a multiple of {dtype.itemsize}")
    return np.frombuffer(raw, dtype=dtype).copy()


def parse_entities(text: str) -> list[dict[str, str]]:
    return [dict(_KEYVALUE.findall(block)) for block in _ENTITY_BLOCK.findall(text)]


def _textures(raw: bytes) -> list[Texture]:
    if not raw:
        return []
    (count,) = struct.unpack_from("<i", raw, 0)
    offsets = struct.unpack_from(f"<{count}i", raw, 4)
    out = []
    for off in offsets:
        if off < 0:
            continue
        name = raw[off : off + 16].split(b"\0", 1)[0].decode("ascii", "replace")
        width, height, mip0 = struct.unpack_from("<III", raw, off + 16)
        out.append(Texture(name=name, width=width, height=height, embedded=mip0 != 0))
    return out


def read_bsp(path: Path) -> Bsp:
    data = path.read_bytes()
    (version,) = struct.unpack_from("<i", data, 0)
    if version != BSP_VERSION:
        raise ValueError(f"{path}: BSP version {version}, expected {BSP_VERSION}")
    lumps = {name: _lump(data, i) for i, name in enumerate(LUMPS)}
    ent_text = lumps["entities"].split(b"\0", 1)[0].decode("utf-8", "replace")
    return Bsp(
        entities=parse_entities(ent_text),
        planes=_array(lumps["planes"], DPLANE),
        textures=_textures(lumps["textures"]),
        vertices=_array(lumps["vertexes"], np.dtype(("<f4", 3))),
        visibility=lumps["visibility"],
        nodes=_array(lumps["nodes"], DNODE),
        texinfo=_array(lumps["texinfo"], DTEXINFO),
        faces=_array(lumps["faces"], DFACE),
        lighting=lumps["lighting"],
        clipnodes=_array(lumps["clipnodes"], DCLIPNODE),
        leafs=_array(lumps["leafs"], DLEAF),
        marksurfaces=_array(lumps["marksurfaces"], np.dtype("<u2")),
        edges=_array(lumps["edges"], DEDGE),
        surfedges=_array(lumps["surfedges"], np.dtype("<i4")),
        models=_array(lumps["models"], DMODEL),
        entity_bytes=len(lumps["entities"]),
    )
