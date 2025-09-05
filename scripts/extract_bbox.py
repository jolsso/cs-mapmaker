#!/usr/bin/env python3
"""
Extract building features from the DK Building dataset within a bounding box
and write them to a GeoJSON file.

Defaults assume the dataset at ./cache/building_inspire.gpkg (layer 'building')
in EPSG:25832. The input bbox CRS defaults to EPSG:4326, and the output
GeoJSON defaults to EPSG:4326 for easier consumption.

Examples:
  python scripts/extract_bbox.py --bbox 8.4509 55.9069 8.5309 55.9869 --in-crs EPSG:4326 --out maps/skjern.buildings.geojson
  python scripts/extract_bbox.py --bbox 440000 6190000 460000 6210000 --in-crs EPSG:25832 --out maps/clip.geojson
"""

from __future__ import annotations

import argparse
from pathlib import Path 
from typing import Iterable, Tuple 


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clip DK buildings by bbox to GeoJSON")
    p.add_argument("--source", default=str(Path("cache") / "building_inspire.gpkg"), help="Path to source GPKG")
    p.add_argument("--layer", default="building", help="Layer name in source dataset")
    p.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MINX", "MINY", "MAXX", "MAXY"),
        required=True,
        help="Bounding box as minx miny maxx maxy in --in-crs",
    )
    p.add_argument("--in-crs", default="EPSG:4326", help="CRS of the provided bbox (default: EPSG:4326)")
    p.add_argument("--out", default=str(Path("maps") / "clip.geojson"), help="Output GeoJSON file")
    p.add_argument("--out-crs", default="EPSG:4326", help="CRS for output features (default: EPSG:4326)")
    p.add_argument("--quiet", action="store_true", help="Reduce console output")
    # Preview rendering options
    p.add_argument("--preview", action="store_true", help="Also write an SVG preview next to the output GeoJSON")
    p.add_argument("--preview-width", type=int, default=1024, help="Preview width in pixels (default: 1024)")
    return p.parse_args(argv)


def _transform_bbox(bbox: Tuple[float, float, float, float], in_crs: str, to_crs: str) -> Tuple[float, float, float, float]:
    if in_crs == to_crs:
        return bbox
    from pyproj import Transformer, CRS

    # Always use x,y order (lon/lat for geographic) regardless of axis order authority
    transformer = Transformer.from_crs(CRS.from_user_input(in_crs), CRS.from_user_input(to_crs), always_xy=True)
    minx, miny, maxx, maxy = bbox
    x0, y0 = transformer.transform(minx, miny)
    x1, y1 = transformer.transform(maxx, maxy)
    # Normalize in case of axis flips during transform
    xmin, xmax = (x0, x1) if x0 <= x1 else (x1, x0)
    ymin, ymax = (y0, y1) if y0 <= y1 else (y1, y0)
    return (xmin, ymin, xmax, ymax)


def extract(argv: list[str]) -> int:
    args = parse_args(argv)

    import fiona
    from shapely.geometry import shape as shp_shape, mapping as shp_mapping, MultiPolygon as ShpMultiPolygon
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer, CRS

    src_path = Path(args.source)
    if not src_path.exists():
        raise SystemExit(f"Source not found: {src_path}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with fiona.open(src_path.as_posix(), layer=args.layer) as src:
        # Prefer WKT; fall back to EPSG string/dict.
        src_crs = src.crs_wkt or src.crs
        if not src_crs:
            raise SystemExit("Source CRS is undefined; cannot proceed.")

        # Prepare bbox in source CRS
        bbox_src = _transform_bbox(tuple(args.bbox), args.in_crs, src_crs)

        # Prepare output schema & CRS
        out_crs = args.out_crs
        transformer = Transformer.from_crs(CRS.from_user_input(src_crs), CRS.from_user_input(out_crs), always_xy=True)
        # Normalize output to MultiPolygon to accommodate polygonal buildings with multipart shapes
        out_schema = {"geometry": "MultiPolygon", "properties": src.schema.get("properties", {})}

        if not args.quiet:
            print(f"Reading {src_path} layer={args.layer} CRS={src_crs} bbox={bbox_src}")
            print(f"Writing {out_path} CRS={out_crs}")

        count = 0
        preview_geoms = []
        with fiona.open(out_path.as_posix(), mode="w", driver="GeoJSON", schema=out_schema, crs=out_crs) as dst:
            for feat in src.filter(bbox=bbox_src):
                geom = feat.get("geometry")
                if not geom:
                    continue
                try:
                    sg = shp_shape(geom)
                except Exception:
                    continue
                # Drop non-polygonal geometries
                if sg.geom_type not in ("Polygon", "MultiPolygon"):
                    continue
                try:
                    sg_t = shp_transform(transformer.transform, sg)
                except Exception:
                    continue
                if sg_t.is_empty:
                    continue
                if sg_t.geom_type == "Polygon":
                    sg_t = ShpMultiPolygon([sg_t])
                elif sg_t.geom_type != "MultiPolygon":
                    continue
                feat_out = {"type": "Feature", "geometry": shp_mapping(sg_t), "properties": feat.get("properties", {})}
                dst.write(feat_out)
                count += 1
                if args.preview:
                    preview_geoms.append(sg_t)

        if not args.quiet:
            print(f"Wrote {count} features -> {out_path}")

        if args.preview:
            _write_svg_preview(preview_geoms, out_path, width=args.preview_width, quiet=args.quiet)

    return 0 


def _write_svg_preview(geoms, out_path: Path, width: int = 1024, quiet: bool = False) -> None:
    # Determine bounds
    if not geoms:
        if not quiet:
            print("No geometries for preview; skipping SVG.")
        return
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    for g in geoms:
        x0, y0, x1, y1 = g.bounds
        if x0 < xmin: xmin = x0
        if y0 < ymin: ymin = y0
        if x1 > xmax: xmax = x1
        if y1 > ymax: ymax = y1
    if not (xmin < xmax and ymin < ymax):
        if not quiet:
            print("Invalid bounds for preview; skipping SVG.")
        return

    # Compute height preserving aspect ratio
    margin = 16
    world_w = max(1e-9, xmax - xmin)
    world_h = max(1e-9, ymax - ymin)
    draw_w = max(1, width - 2 * margin)
    height = int(draw_w * (world_h / world_w)) + 2 * margin
    draw_h = max(1, height - 2 * margin)

    def to_px(x, y):
        px = margin + (x - xmin) / world_w * draw_w
        py = margin + (ymax - y) / world_h * draw_h  # invert Y for screen coords
        return px, py

    # Build SVG paths
    path_elems = []
    # Light background
    bg = f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
    border = f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" fill="none" stroke="#cccccc"/>'

    for g in geoms:
        # Iterate parts
        parts = []
        for poly in g.geoms:
            # Exterior
            coords = poly.exterior.coords
            if not coords:
                continue
            d = []
            for i, (x, y) in enumerate(coords):
                px, py = to_px(x, y)
                cmd = 'M' if i == 0 else 'L'
                d.append(f"{cmd}{px:.1f},{py:.1f}")
            d.append('Z')
            # Interiors (holes)
            for ring in poly.interiors:
                ring_coords = ring.coords
                if not ring_coords:
                    continue
                for j, (x, y) in enumerate(ring_coords):
                    px, py = to_px(x, y)
                    cmd = 'M' if j == 0 else 'L'
                    d.append(f"{cmd}{px:.1f},{py:.1f}")
                d.append('Z')
            parts.append(' '.join(d))
        if not parts:
            continue
        path_d = ' '.join(parts)
        path_elems.append(f'<path d="{path_d}" fill="#1f77b4" fill-opacity="0.35" stroke="#1f77b4" stroke-width="0.8"/>')

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' viewBox='0 0 {width} {height}'>"
        f"{bg}{border}{''.join(path_elems)}</svg>"
    )
    svg_path = out_path.with_suffix('.svg')
    svg_path.write_text(svg, encoding='utf-8')
    if not quiet:
        print(f"Preview written -> {svg_path}")


if __name__ == "__main__": 
    import sys 
    raise SystemExit(extract(sys.argv[1:])) 
