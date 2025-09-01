# cs-mapmaker

Generate Counter-Strike 1.6 Hammer `.map` files from real Danish city data. Provide a lat/lon bounding box, fetch building footprints from Dataforsyningen (dataset 2677), convert to convex brushes, and open in Hammer to refine.

Status: CLI scaffold ready; generation is stubbed (empty map).

## Quickstart
- Using Task (recommended):
  - `task bootstrap`
  - `task cli:help`
  - `task cli:example:generate` (writes `maps/example.map` with worldspawn)
  - To fetch real buildings (requires WFS details):
    - Either edit `config.yaml` (auto-created from `config.example.yaml` on first bootstrap), or set env vars:
      - In `config.yaml` set:
        - `dataforsyningen.wfs_url: https://<host>/<path>/ows`
        - `dataforsyningen.wfs_typename: <buildings_layer_name>`
      - Or set env vars:
        - `DF_WFS_URL="https://<host>/<path>/ows"`
        - `DF_WFS_TYPENAME="<buildings_layer_name>"`
    - Then run: `task cli:example:fetch`
    - Tip: Open `<DF_WFS_URL>?service=WFS&request=GetCapabilities` in a browser to find the correct layer `Name` (use that as `DF_WFS_TYPENAME`).
- Manual (without Task):
  - Create venv and install deps:
    - Windows PowerShell:
      - `python -m venv backend/.venv`
      - `.\\backend\\.venv\\Scripts\\Activate.ps1`
      - `pip install -r backend/requirements.txt`
    - macOS/Linux:
      - `python -m venv backend/.venv`
      - `source backend/.venv/bin/activate`
      - `pip install -r backend/requirements.txt`
  - Show help: `python -m app.cli --help`
  - Generate empty map: `python -m app.cli generate --bbox 12.5,55.6,12.6,55.7 --out maps/example.map --wad halflife.wad`
  - Fetch first buildings page (WFS):
    - With flags: `python -m app.cli fetch --bbox 12.5,55.6,12.6,55.7 --out cache --wfs-url https://<host>/<path>/ows --typename <layer>`
    - With config: Set `config.yaml` as above, then `python -m app.cli fetch --bbox 12.5,55.6,12.6,55.7 --out cache`
    - Or with env: `set DF_WFS_URL=...`, `set DF_WFS_TYPENAME=...`, then `python -m app.cli fetch --bbox 12.5,55.6,12.6,55.7 --out cache`
  - Open `maps/example.map` in Hammer (no solids yet; worldspawn only).

## Overview
- Input: Lat/lon bounding box over Denmark.
- Data: Buildings from Dataforsyningen dataset 2677 (GeoDanmark Bygning).
- Process: Fetch → cache → reproject → simplify → convex-decompose → extrude.
- Output: Valve 220 `.map` with worldspawn + building solids.

## High-Level Flow
- Select bbox: User provides `<minLon,minLat,maxLon,maxLat>`.
- Fetch & cache: Download buildings (dataset 2677) for bbox and store raw GeoJSON.
- Process geometry: Reproject to meters, clean/simplify, convex-decompose, extrude to height, snap.
- Export: Write `.map` (Valve 220) with textures and safe IDs.

## Architecture
- Provider: Dataforsyningen WFS/GeoJSON client with paging, retries, and minimal fields.
- Cache: On-disk cache (SQLite index + GeoJSON blobs) keyed by provider:dataset:crs:bboxhash:version.
- SRS: EPSG:4326 (input) ⇄ EPSG:25832 (working). Normalize around bbox center; scale meters→Hammer units (default 1 m ≈ 32 u).
- Geometry: Clip, repair invalid rings, topology-preserving simplify, convex decomposition, extrusion to prisms, grid snapping, culling.
- Export: Valve 220 writer (planes from 3 pts, consistent winding, simple UV axes) with texture presets for walls/roofs.
- CLI: `csmap fetch|generate|preview|clean` for end-to-end or stepwise runs.
- API/UI (optional): FastAPI endpoints mirroring CLI and a small preview UI.

## Data Source
- Dataset: https://dataforsyningen.dk/data/2677 (GeoDanmark Bygning).
- Access: Use OGC WFS 2.0 or GeoJSON per bbox; request geometry and height attributes if available.
- Attribution: Include required notice with exports.

## Coordinate Systems & Scaling
- Input: WGS84 (EPSG:4326) lat/lon.
- Working: ETRS89 / UTM 32N (EPSG:25832) for meter-based operations.
- Normalize: Subtract bbox centroid to keep coordinates near origin.
- Scale: Meters → Hammer units (default 32); configurable.
- Extents: Keep within engine/world limits; warn and cap as needed.

## Geometry Pipeline
- Clip & clean: Clip to bbox, fix invalid polygons, drop tiny slivers (< min area).
- Simplify: Douglas–Peucker (preserve topology) to reduce vertices.
- Convex decomposition: Split concave footprints into convex parts (brush-friendly).
- Extrude: Use height attribute or default (e.g., 10 m); flat roof.
- Snap & cull: Grid snapping to avoid micro-brushes; cap buildings/brushes/faces; log skips.

## Export: Valve 220 `.map`
- Worldspawn: "mapversion" "220", "classname" "worldspawn", configurable "wad" list.
- Solids: One solid per convex prism; planes from 3 points; consistent winding/outward normals.
- Texturing: Wall/roof presets; simple axis mapping; stable IDs.

## CLI (planned)
- `csmap fetch --bbox <minlon,minlat,maxlon,maxlat> --crs 25832 --out cache/`
- `csmap generate --bbox <...> --scale 32 --simplify 0.5 --min-area 2 --default-height 10 --wad halflife.wad --out maps/city.map`
- `csmap preview --bbox <...> --scale 32` (quick footprint coverage image)
- `csmap clean --older-than 30d`

## Caching Strategy
- Keys: `provider:dataset:crs:bbox_or_tile_hash:version`.
- Storage: SQLite index + blob files under `cache/`.
- TTL & versioning: TTL eviction and schema version bumps to invalidate.

## Limits & Guardrails
- Caps: Max buildings/brushes/faces per run; abort or sample with report.
- Filters: Drop under min area/height; reject degenerate geometry.
- Validation: Detect non-convex residuals, inverted planes; write a summary report.

## Tech Stack
- Python: `requests`, `pyproj`, `shapely`, `numpy`, `typer` (CLI), `fastapi` (optional API).
- Preview: `matplotlib` or `Pillow` to render simple footprint images.

## Roadmap
- M1: POC bbox → rectangles (default height) → `.map` opens in Hammer.
- M2: Robust CRS, simplification, convex decomposition, caps + report.
- M3: Ingest heights, better UVs/textures, presets; preview image.
- M4: Performance, attribution file, docs polish.

## CLI Commands
- `fetch`: Fetches the first page of building polygons via WFS for a bbox and caches GeoJSON.
- `generate`: Produces a `.map`. Currently writes an empty worldspawn (stub). Accepts `--wad` to set WAD paths.
- `preview`: Writes a simple textual preview for a bbox (stub).
- `clean`: Prints intended cache cleanup (stub).

## Attribution
- Include Dataforsyningen/GeoDanmark attribution in exports as required.
