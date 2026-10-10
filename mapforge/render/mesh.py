"""Triangle batches (one per texture) with texture and lightmap UVs, plus a lightmap atlas."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from mapforge.bsp.reader import Bsp

# Tool / invisible textures that the engine does not draw.
SKIP_TEXTURES = {
    "sky", "clip", "origin", "null", "aaatrigger", "bevel", "hint", "skip", "solidhint",
    "bevelhint", "splitface", "noclip",
}  # fmt: skip
# Brush entities that are invisible in game (triggers, zones, ladders' clip volumes).
SKIP_CLASSES = (
    "trigger_", "func_bomb_target", "func_buyzone", "func_hostage_rescue", "func_escapezone",
    "func_vip_safetyzone", "func_ladder", "env_bubbles", "func_mortar_field",
)  # fmt: skip
# Vertex layout: position (3), texture uv (2), lightmap uv (2)
VERTEX_FLOATS = 7


@dataclass
class Batch:
    texture: int
    vertices: list[np.ndarray] = field(default_factory=list)

    def array(self) -> np.ndarray:
        return np.vstack(self.vertices).astype("f4")


@dataclass
class Mesh:
    batches: dict[int, np.ndarray]  # texture index -> (n, 7) float32 triangle vertices
    atlas: np.ndarray  # (H, W, 3) uint8 lightmap atlas
    bounds: tuple[np.ndarray, np.ndarray]


def _visible_models(bsp: Bsp) -> list[tuple[int, np.ndarray]]:
    """(model index, origin offset) for the world and every visible brush entity."""
    out = [(0, np.zeros(3))]
    for ent in bsp.entities:
        model = ent.get("model", "")
        cls = ent.get("classname", "")
        if not model.startswith("*") or cls.startswith(SKIP_CLASSES):
            continue
        rendermode = int(ent.get("rendermode", "0") or 0)
        renderamt = float(ent.get("renderamt", "255") or 255)
        if rendermode != 0 and renderamt == 0:
            continue
        origin = np.array([float(v) for v in ent.get("origin", "0 0 0").split()])
        out.append((int(model[1:]), origin))
    return out


class _AtlasPacker:
    """Shelf packer for lightmap rectangles (1 texel border to stop bleeding)."""

    def __init__(self, width: int = 2048) -> None:
        self.width = width
        self.x = self.y = self.shelf = 0
        self.blocks: list[tuple[int, int, np.ndarray]] = []

    def add(self, img: np.ndarray) -> tuple[int, int]:
        h, w = img.shape[:2]
        if self.x + w + 2 > self.width:
            self.x, self.y, self.shelf = 0, self.y + self.shelf, 0
        pos = (self.x + 1, self.y + 1)
        self.blocks.append((pos[0], pos[1], img))
        self.x += w + 2
        self.shelf = max(self.shelf, h + 2)
        return pos

    def image(self) -> np.ndarray:
        height = max(1, self.y + self.shelf)
        atlas = np.zeros((height, self.width, 3), dtype=np.uint8)
        for x, y, img in self.blocks:
            h, w = img.shape[:2]
            atlas[y : y + h, x : x + w] = img
            # replicate edges into the border
            atlas[y - 1, x : x + w] = img[0]
            atlas[y + h, x : x + w] = img[-1]
            atlas[y - 1 : y + h + 1, x - 1] = atlas[y - 1 : y + h + 1, x]
            atlas[y - 1 : y + h + 1, x + w] = atlas[y - 1 : y + h + 1, x + w - 1]
        return atlas


def build_mesh(bsp: Bsp) -> Mesh:
    packer = _AtlasPacker()
    white = packer.add(np.full((2, 2, 3), 255, dtype=np.uint8))  # for faces without lightmap
    pending: list[tuple[int, np.ndarray, np.ndarray, tuple[int, int] | None, np.ndarray]] = []
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)

    for model, origin in _visible_models(bsp):
        m = bsp.models[model]
        for fi in range(int(m["firstface"]), int(m["firstface"]) + int(m["numfaces"])):
            face = bsp.faces[fi]
            ti = bsp.texinfo[face["texinfo"]]
            tex_index = int(ti["miptex"])
            tex = bsp.textures[tex_index]
            if tex.name.lower() in SKIP_TEXTURES or tex.name.lower().startswith("sky"):
                continue
            verts = bsp.face_vertices(fi).astype(np.float64)
            if len(verts) < 3:
                continue
            vecs = ti["vecs"].astype(np.float64)
            st = verts @ vecs[:, :3].T + vecs[:, 3]
            lm = bsp.face_lightmap(fi)
            lm_pos = packer.add(lm) if lm is not None else None
            world = verts + origin
            lo, hi = np.minimum(lo, world.min(axis=0)), np.maximum(hi, world.max(axis=0))
            pending.append((tex_index, world, st, lm_pos, np.floor(st.min(axis=0) / 16)))

    atlas = packer.image()
    ah, aw = atlas.shape[:2]
    batches: dict[int, Batch] = {}
    for tex_index, world, st, lm_pos, lm_min in pending:
        tex = bsp.textures[tex_index]
        uv = st / [max(tex.width, 1), max(tex.height, 1)]
        if lm_pos is None:
            luv = np.tile([(white[0] + 1) / aw, (white[1] + 1) / ah], (len(st), 1))
        else:
            # sample centres: (s/16 - floor(min s/16) + 0.5) texels into this face's block
            local = st / 16 - lm_min + 0.5
            luv = (local + lm_pos) / [aw, ah]
        v = np.hstack([world, uv, luv])
        tri = np.array([[0, i, i + 1] for i in range(1, len(v) - 1)]).ravel()
        batches.setdefault(tex_index, Batch(tex_index)).vertices.append(v[tri])
    return Mesh(
        batches={k: b.array() for k, b in batches.items()},
        atlas=atlas,
        bounds=(lo, hi),
    )
