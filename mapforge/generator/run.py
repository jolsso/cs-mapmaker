"""Generate maps/<map>/src/<map>.map from maps/<map>/layout.yaml.

Usage: python -m mapforge.generator.run --map de_forge01
"""

from __future__ import annotations

import argparse
import sys

from mapforge.config import load_config
from mapforge.generator.build import generate
from mapforge.generator.spec import SpecError, load_layout
from mapforge.mapfile.writer import write_map


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
