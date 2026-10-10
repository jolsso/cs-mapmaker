"""Deliberately broken variants of reference maps, for testing the Review gate.

Usage: python -m mapforge.refmaps_variants
Only the entity lump changes (like ripent): the geometry stays valid, so validation passes and
only the visual review can catch the problem. Written to build/refmaps/variants/ (local only).
"""

from __future__ import annotations

import sys

import numpy as np

from mapforge.bsp.reader import read_bsp
from mapforge.bsp.writer import write_with_entities
from mapforge.config import load_config
from mapforge.refmaps import find_reference_bsp


def _origin(e: dict[str, str]) -> np.ndarray:
    return np.array([float(v) for v in e["origin"].split()])


def spawnswap(entities: list[dict[str, str]]) -> list[dict[str, str]]:
    """T spawns moved onto the CT spawn positions (both teams spawn in one place)."""
    ct = [e["origin"] for e in entities if e.get("classname") == "info_player_start"]
    out, k = [], 0
    for e in entities:
        if e.get("classname") == "info_player_deathmatch":
            e = {**e, "origin": ct[k % len(ct)]}
            k += 1
        out.append(e)
    return out


def sitemoved(entities: list[dict[str, str]], bsp) -> list[dict[str, str]]:
    """The second bomb site (func_bomb_target) shifted into the CT spawn."""
    ct = np.mean(
        [_origin(e) for e in entities if e.get("classname") == "info_player_start"], axis=0
    )
    targets = [i for i, e in enumerate(entities) if e.get("classname") == "func_bomb_target"]
    i = targets[-1]
    m = bsp.models[int(entities[i]["model"][1:])]
    centre = (m["mins"] + m["maxs"]) / 2
    shift = ct - centre
    shift[2] = ct[2] - 36 - m["mins"][2]  # floor of the box at the CT spawn floor
    out = list(entities)
    out[i] = {**entities[i], "origin": " ".join(f"{v:.0f}" for v in shift)}
    return out


def main() -> int:
    cfg = load_config()
    src = find_reference_bsp(cfg, "de_dust2")
    if src is None:
        print("de_dust2 not found among reference maps", file=sys.stderr)
        return 1
    bsp = read_bsp(src)
    root = cfg.root / cfg.data["reference_maps"]["extract_dir"] / "variants"
    for name, ents in (
        ("de_dust2_spawnswap", spawnswap(bsp.entities)),
        ("de_dust2_sitemoved", sitemoved(bsp.entities, bsp)),
    ):
        dst = root / name / "maps" / f"{name}.bsp"
        write_with_entities(src, dst, ents)
        print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
