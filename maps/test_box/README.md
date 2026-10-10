# test_box

Phase 0 test map: the smallest map that has to compile from a clean checkout.

- Sealed 1024×1024×256 interior room (floor at z=0), 16-unit walls, everything on the 16-grid.
- 1 `light` in the middle at z=192.
- 2× `info_player_start` (CT) at x=-384 and 2× `info_player_deathmatch` (T) at x=384, origin z=36 (feet on the floor).
- Textures from `mapforge_dev.wad` (generated, see `assets/LICENSES.md`).

The source is `src/test_box.map` (Valve 220). Compile with `uv run task compile MAP=test_box`.
