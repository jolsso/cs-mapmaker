from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console

from app import __version__
from app.export.map220 import write_empty_map
from app.providers.wfs import fetch_wfs_bbox_first_page
from app.config import AppConfig


app = typer.Typer(help="csmap CLI - bbox -> cache -> .map (Hammer 220)")
console = Console()


@dataclass(frozen=True)
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @staticmethod
    def parse(text: str) -> "BBox":
        try:
            parts = [float(p.strip()) for p in text.split(",")]
            if len(parts) != 4:
                raise ValueError
            a, b, c, d = parts
            if a >= c or b >= d:
                raise ValueError("min must be < max for lon/lat")
            return BBox(a, b, c, d)
        except Exception as e:  # noqa: BLE001
            raise typer.BadParameter(
                "Expected '<minLon,minLat,maxLon,maxLat>'"
            ) from e


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


@app.command()
def version() -> None:
    """Show CLI version."""
    rprint(f"csmap {__version__}")


@app.command()
def fetch(
    bbox: str = typer.Option(..., help="<minLon,minLat,maxLon,maxLat> in EPSG:4326"),
    out: Path = typer.Option(Path("cache"), help="Cache directory"),
    gpkg: Optional[Path] = typer.Option(
        None,
        help="Path to a local GeoPackage to use instead of web API",
    ),
    wfs_url: Optional[str] = typer.Option(
        None,
        help=(
            "WFS endpoint base URL (e.g., https://<host>/<path>/ows). "
            "If omitted, reads DF_WFS_URL env var."
        ),
    ),
    typename: Optional[str] = typer.Option(
        None,
        help=(
            "WFS type name/layer for buildings (e.g., 'bygning'). "
            "If omitted, reads DF_WFS_TYPENAME env var."
        ),
    ),
    count: int = typer.Option(100, help="Max features to fetch (first page)"),
    srs_name: str = typer.Option(
        "EPSG:4326", help="CRS for server response and bbox parameter"
    ),
    output_name: Optional[str] = typer.Option(
        None, help="Output filename (defaults to bbox hash).geojson"
    ),
) -> None:
    """Fetch the first page of building polygons via WFS and cache as GeoJSON.

    Note: Dataforsyningen requires the correct WFS URL and typename for dataset 2677.
    Provide them via --wfs-url and --typename or DF_WFS_URL / DF_WFS_TYPENAME env vars.
    """
    box = BBox.parse(bbox)
    ensure_dir(out)

    # Prefer a local GeoPackage if present
    if gpkg and Path(gpkg).exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest = {
            "source": "local_gpkg",
            "gpkg": str(Path(gpkg).resolve()),
            "bbox": (box.min_lon, box.min_lat, box.max_lon, box.max_lat),
            "srs_name": srs_name,
            "timestamp": stamp,
        }
        fname = f"local_gpkg_{Path(gpkg).stem}_{stamp}.fetch.json"
        (out / fname).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        console.print(
            f"[green]Using local GeoPackage[/green] -> {manifest['gpkg']} (manifest: {out / fname})"
        )
        return

    cfg = AppConfig.load()
    wfs_url = wfs_url or os.getenv("DF_WFS_URL") or cfg.dataforsyningen.url
    typename = typename or os.getenv("DF_WFS_TYPENAME") or cfg.dataforsyningen.typename
    if not wfs_url or not typename:
        raise typer.BadParameter(
            "Missing --wfs-url and/or --typename (or env DF_WFS_URL / DF_WFS_TYPENAME)."
        )

    bbox_tuple = (box.min_lon, box.min_lat, box.max_lon, box.max_lat)
    try:
        features, request_url = fetch_wfs_bbox_first_page(
        wfs_url=wfs_url,
        typename=typename,
        bbox=bbox_tuple,
        srs_name=srs_name,
        count=count,
        api_key=cfg.dataforsyningen.api_key,
        api_key_header=cfg.dataforsyningen.api_key_header,
        api_key_query=cfg.dataforsyningen.api_key_query,
    )
    except Exception as exc:  # noqa: BLE001
        console.print(
            "[red]Fetch failed[/red]:",
            str(exc),
        )
        console.print(
            "[yellow]Hint[/yellow]: Some Dataforsyningen services require an API key."
        )
        console.print(
            "Configure it in config.yaml (dataforsyningen.api_key + api_key_header/api_key_query) or set DF_API_KEY."
        )
        raise typer.Exit(code=1)

    # Name output by bbox and count
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{box.min_lon:.5f}_{box.min_lat:.5f}_{box.max_lon:.5f}_{box.max_lat:.5f}_{count}"
    fname = output_name or f"df_2677_{slug}_{stamp}.geojson"
    out_path = out / fname
    ensure_dir(out)
    out_path.write_text(json.dumps(features), encoding="utf-8")

    # Write a small fetch manifest
    manifest = {
        "source": "wfs",
        "url": wfs_url,
        "typename": typename,
        "bbox": bbox_tuple,
        "srs_name": srs_name,
        "count": count,
        "request_url": request_url,
        "out": str(out_path),
        "timestamp": stamp,
    }
    (out / f"{fname}.fetch.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    console.print(
        f"[green]Fetched[/green] {len(features.get('features', []))} features -> {out_path}"
    )


@app.command()
def generate(
    bbox: str = typer.Option(..., help="<minLon,minLat,maxLon,maxLat> in EPSG:4326"),
    out: Path = typer.Option(..., help="Output .map file path"),
    wad: Optional[str] = typer.Option(None, help="Semicolon-separated WADs for Hammer"),
    gpkg: Optional[Path] = typer.Option(None, help="Path to local GeoPackage (buildings)"),
    layer: Optional[str] = typer.Option(None, help="Layer name in the GeoPackage"),
    source_crs: Optional[str] = typer.Option(None, help="CRS of GPKG layer if missing (e.g., EPSG:25832)"),
    scale: float = typer.Option(32.0, help="Meters to Hammer units scale"),
    simplify: float = typer.Option(0.5, help="Simplification tolerance (meters)"),
    min_area: float = typer.Option(2.0, help="Min building area (m^2)"),
    default_height: float = typer.Option(10.0, help="Default building height (m)"),
    wall_texture: str = typer.Option("BRICK/BRICK01", help="Wall texture path"),
    roof_texture: str = typer.Option("ROOF/ROOF01", help="Roof texture path"),
    stub: bool = typer.Option(False, help="Generate empty map instead of solids"),
) -> None:
    """Generate a Hammer .map from cached data or local GPKG."""
    box = BBox.parse(bbox)
    out = Path(out)
    wads = [w.strip() for w in (wad or "").split(";") if w.strip()]

    if stub and not gpkg:
        write_empty_map(out, wads=wads)
        console.print("[green].map created[/green] ->", out)
        console.print(
            "[yellow]Note[/yellow]: generation pipeline is stubbed; solids will be added later."
        )
        return

    if gpkg:
        try:
            boxes = _boxes_from_gpkg(
                gpkg, layer, box, source_crs=source_crs, scale=scale, min_area=min_area, height=default_height
            )
        except ImportError as ie:
            console.print(
                "[red]Missing dependency[/red]:", str(ie)
            )
            console.print(
                "Install with: pip install shapely pyproj fiona"
            )
            raise typer.Exit(code=1)
        except Exception as exc:  # noqa: BLE001
            console.print("[red]GPKG processing failed[/red]:", str(exc))
            raise typer.Exit(code=1)

        from app.export.map220 import write_boxes_map

        write_boxes_map(
            out,
            boxes,
            wads=wads,
            wall_texture=wall_texture,
            roof_texture=roof_texture,
        )
        console.print(
            f"[green]Map with {len(boxes)} box solids created[/green] ->", out
        )
        return

    console.print("[yellow]Nothing to generate[/yellow]: provide --gpkg or use --stub.")
    raise typer.Exit(code=2)


@app.command()
def preview(
    bbox: str = typer.Option(..., help="<minLon,minLat,maxLon,maxLat> in EPSG:4326"),
    out: Path = typer.Option(Path("previews/bbox.txt"), help="Preview output path (text)"),
) -> None:
    """Write a simple textual preview (stub)."""
    box = BBox.parse(bbox)
    out = Path(out)
    ensure_dir(out.parent)
    out.write_text(f"Preview (stub) for bbox: {box}\n", encoding="utf-8")
    console.print("[green]Preview stub[/green] ->", out)


@app.command()
def clean(
    cache_dir: Path = typer.Option(Path("cache"), help="Cache directory"),
    older_than: str = typer.Option("30d", help="TTL, e.g., 30d, 12h (stub)"),
) -> None:
    """Clean cached items older than TTL (stub)."""
    console.print(
        f"[yellow]Stub[/yellow]: would clean {cache_dir} for items older than {older_than}"
    )


def _main(argv: list[str] | None = None) -> int:
    try:
        app()
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))


# --- helpers (local to CLI to avoid hard deps at import time) ---
def _boxes_from_gpkg(
    gpkg_path: Path,
    layer: Optional[str],
    bbox: BBox,
    *,
    source_crs: Optional[str],
    scale: float,
    min_area: float,
    height: float,
):
    # Lazy imports to keep CLI lightweight unless used
    import fiona  # type: ignore
    from shapely.geometry import shape, box as sbox  # type: ignore
    from shapely.ops import transform as stransform  # type: ignore
    from pyproj import CRS, Transformer  # type: ignore

    # Prepare spatial filters
    filter_poly_wgs84 = sbox(bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat)

    # Open dataset
    with fiona.Env():
        with fiona.open(gpkg_path, layer=layer) as src:
            # Determine source CRS
            src_crs = None
            if src.crs_wkt:
                src_crs = CRS.from_wkt(src.crs_wkt)
            elif src.crs:
                src_crs = CRS.from_user_input(src.crs)
            elif source_crs:
                src_crs = CRS.from_user_input(source_crs)
            else:
                raise RuntimeError("Cannot determine source CRS; please pass --source-crs EPSG:xxxx")

            crs_wgs84 = CRS.from_epsg(4326)
            crs_metric = CRS.from_epsg(25832)

            to_wgs84 = Transformer.from_crs(src_crs, crs_wgs84, always_xy=True)
            to_metric = Transformer.from_crs(src_crs, crs_metric, always_xy=True)
            wgs_to_metric = Transformer.from_crs(crs_wgs84, crs_metric, always_xy=True)

            # Center in metric CRS for normalization
            lon_c = (bbox.min_lon + bbox.max_lon) / 2.0
            lat_c = (bbox.min_lat + bbox.max_lat) / 2.0
            cx, cy = wgs_to_metric.transform(lon_c, lat_c)

            boxes = []
            for feat in src:
                if not feat.get("geometry"):
                    continue
                geom = shape(feat["geometry"])  # src CRS

                # Quick bbox filter: transform to WGS84 and intersect with filter polygon
                geom_wgs = stransform(lambda x, y, z=None: to_wgs84.transform(x, y), geom)
                if not geom_wgs.is_valid or not geom_wgs.intersects(filter_poly_wgs84):
                    continue

                # Transform to metric CRS to compute bounds and area
                geom_m = stransform(lambda x, y, z=None: to_metric.transform(x, y), geom)
                if geom_m.is_empty:
                    continue

                if hasattr(geom_m, "area") and geom_m.area < float(min_area):
                    continue

                minx, miny, maxx, maxy = geom_m.bounds

                # Normalize around center and scale to Hammer units
                minx_u = (minx - cx) * scale
                maxx_u = (maxx - cx) * scale
                miny_u = (miny - cy) * scale
                maxy_u = (maxy - cy) * scale
                z0_u = 0.0
                z1_u = height * scale

                # Skip degenerate boxes
                if maxx_u - minx_u <= 0.1 or maxy_u - miny_u <= 0.1:
                    continue

                boxes.append((minx_u, miny_u, maxx_u, maxy_u, z0_u, z1_u))

            return boxes
