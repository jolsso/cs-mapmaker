from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console

from app import __version__
from app.export.map220 import write_empty_map


app = typer.Typer(help="csmap CLI — bbox -> cache -> .map (Hammer 220)")
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
    dataset: str = typer.Option("2677", help="Dataforsyningen dataset id"),
    crs: int = typer.Option(25832, help="Working CRS (meters), e.g., 25832"),
    dry_run: bool = typer.Option(False, help="Do not write files; print plan only"),
) -> None:
    """Fetch building footprints for bbox (stub; caching only)."""
    box = BBox.parse(bbox)
    ensure_dir(out)
    plan = {
        "dataset": dataset,
        "bbox": box.__dict__,
        "crs": crs,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    if dry_run:
        rprint(plan)
        return

    # Stub: create a cache marker and a plan.json
    (out / "README.txt").write_text(
        "csmap cache directory (stub) — raw GeoJSON tiles will be stored here\n",
        encoding="utf-8",
    )
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    console.print("[green]Fetch stub complete[/green] →", out)


@app.command()
def generate(
    bbox: str = typer.Option(..., help="<minLon,minLat,maxLon,maxLat> in EPSG:4326"),
    out: Path = typer.Option(..., help="Output .map file path"),
    wad: Optional[str] = typer.Option(None, help="Semicolon-separated WADs for Hammer"),
    scale: float = typer.Option(32.0, help="Meters to Hammer units scale"),
    simplify: float = typer.Option(0.5, help="Simplification tolerance (meters)"),
    min_area: float = typer.Option(2.0, help="Min building area (m^2)"),
    default_height: float = typer.Option(10.0, help="Default building height (m)"),
    stub: bool = typer.Option(True, help="Generate empty map for now"),
) -> None:
    """Generate a Hammer .map from cached data (stub writes empty map)."""
    _ = BBox.parse(bbox)
    out = Path(out)
    wads = [w.strip() for w in (wad or "").split(";") if w.strip()]

    if stub:
        write_empty_map(out, wads=wads)
        console.print("[green].map created[/green] →", out)
        console.print(
            "[yellow]Note[/yellow]: generation pipeline is stubbed; solids will be added later."
        )
        return

    console.print(
        "[red]Not implemented[/red]: full generation pipeline will process cache → brushes."
    )
    raise typer.Exit(code=1)


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
    console.print("[green]Preview stub[/green] →", out)


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

