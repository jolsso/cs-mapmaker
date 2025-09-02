from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    TimeRemainingColumn,
    SpinnerColumn,
    MofNCompleteColumn,
    TextColumn,
)

from app import __version__
from app.export.map220 import write_empty_map


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
    gpkg: Path = typer.Option(
        ..., help="Path to a local GeoPackage with buildings"
    ),
    srs_name: str = typer.Option(
        "EPSG:4326", help="CRS of the provided bbox"
    ),
) -> None:
    """Register a local GeoPackage as the data source for a bbox (offline-only)."""
    box = BBox.parse(bbox)
    ensure_dir(out)

    gpkg_path = Path(gpkg)
    if not gpkg_path.exists():
        raise typer.BadParameter(f"GPKG not found: {gpkg_path}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = {
        "source": "local_gpkg",
        "gpkg": str(gpkg_path.resolve()),
        "bbox": (box.min_lon, box.min_lat, box.max_lon, box.max_lat),
        "srs_name": srs_name,
        "timestamp": stamp,
    }
    fname = f"local_gpkg_{gpkg_path.stem}_{stamp}.fetch.json"
    (out / fname).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    console.print(
        f"[green]Using local GeoPackage[/green] -> {manifest['gpkg']} (manifest: {out / fname})"
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
    progress: bool = typer.Option(True, help="Show progress while reading GPKG"),
    max_features: Optional[int] = typer.Option(
        None, help="Process at most N features (early stop)"
    ),
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
                gpkg,
                layer,
                box,
                source_crs=source_crs,
                scale=scale,
                min_area=min_area,
                height=default_height,
                show_progress=progress,
                max_features=max_features,
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
    show_progress: bool = True,
    max_features: Optional[int] = None,
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
            wgs_to_src = Transformer.from_crs(crs_wgs84, src_crs, always_xy=True)

            # Center in metric CRS for normalization
            lon_c = (bbox.min_lon + bbox.max_lon) / 2.0
            lat_c = (bbox.min_lat + bbox.max_lat) / 2.0
            cx, cy = wgs_to_metric.transform(lon_c, lat_c)

            # Compute source-CRS bbox and use collection-level spatial filter if available
            x1, y1 = wgs_to_src.transform(bbox.min_lon, bbox.min_lat)
            x2, y2 = wgs_to_src.transform(bbox.max_lon, bbox.max_lat)
            bbox_src = (
                min(x1, x2),
                min(y1, y2),
                max(x1, x2),
                max(y1, y2),
            )

            total = None
            try:
                # We can't know the filtered count cheaply; leave total unknown
                total = None
            except Exception:
                total = None

            progress_ctx = None
            task_id = None
            if show_progress:
                progress_ctx = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold]Reading GPKG"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeRemainingColumn(),
                    transient=True,
                    console=console,
                )
                progress_ctx.start()
                task_id = progress_ctx.add_task("features", total=total)

            # Prefer streaming with a driver-level bbox filter
            try:
                iterator = src.filter(bbox=bbox_src)
            except Exception:
                iterator = iter(src)

            boxes = []
            for _feat_idx, feat in enumerate(iterator, start=1):
                if not feat.get("geometry"):
                    continue
                geom = shape(feat["geometry"])  # src CRS

                # Quick bbox filter in WGS84 (fallback if driver-level filter is coarse)
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

                if progress_ctx and task_id is not None:
                    if total is not None:
                        progress_ctx.update(task_id, completed=_feat_idx)
                    else:
                        progress_ctx.advance(task_id)

                if max_features and len(boxes) >= max_features:
                    break

            if progress_ctx:
                progress_ctx.stop()

            return boxes
