"""Generate maps/<map>/src/<map>.map from maps/<map>/layout.yaml.

Usage: python -m mapforge.generator.run --map de_forge01
"""

from __future__ import annotations

import argparse
import sys

from mapforge.config import Config, load_config
from mapforge.generator.build import generate
from mapforge.generator.spec import SpecError, load_layout
from mapforge.mapfile.parser import MapFile
from mapforge.mapfile.writer import write_map
from mapforge.wad.catalog import wads_for


def assign_wads(mapfile: MapFile, cfg: Config) -> list[str]:
    """Set the worldspawn `wad` key: our embedded WADs first, then the WADs (ours or the game's
    standard ones) holding the textures the map uses. The game's WADs are only referenced, never
    embedded (mapforge.wad.catalog). -> texture names found in no WAD."""
    used = {f.texture for b in mapfile.brushes() for f in b.faces}
    wads, missing = wads_for(used, cfg.wad_dirs)
    own = [w for w in cfg.data.get("wad", {}).get("include", []) if w not in wads]
    mapfile.worldspawn.properties["wad"] = ";".join(own + wads)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    args = parser.parse_args(argv)
    cfg = load_config()
    map_dir = cfg.path("maps_dir") / args.map
    try:
        layout = load_layout(map_dir / "layout.yaml")
        if layout.name != args.map:
            raise SpecError(f"layout name {layout.name!r} does not match the map dir {args.map!r}")
        g = generate(layout)
    except (OSError, SpecError, KeyError) as exc:
        print(f"generate failed: {exc}", file=sys.stderr)
        return 1
    missing = assign_wads(g.mapfile, cfg)
    if missing:
        print(f"generate failed: textures in no WAD of paths.wad_dirs: {missing}", file=sys.stderr)
        return 1
    out = map_dir / "src" / f"{args.map}.map"
    write_map(
        g.mapfile,
        out,
        header=f"GENERATED from layout.yaml by mapforge.generator – do not edit\n{g.stats}",
    )
    rad = out.with_suffix(".rad")  # texture lights for hlrad (-lights); none = no file
    if g.rad:
        rad.write_text(g.rad, encoding="utf-8", newline="\n")
    elif rad.exists():
        rad.unlink()
    print(f"generated {out} {g.stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
