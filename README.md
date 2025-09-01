# cs-mapmaker

Generate Counter-Strike 1.6 Hammer `.map` files from real Danish city data. Provide a lat/lon bounding box, fetch building footprints from Dataforsyningen (dataset 2677), convert to convex brushes, and open in Hammer to refine.

Status: Planning/Docs first. CLI + pipeline scaffolding to follow.

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

## Getting Started (soon)
- This repository will add a Python CLI and optional FastAPI service.
- Initial commands will target a very small bbox to validate `.map` export.

## Attribution
- Include Dataforsyningen/GeoDanmark attribution in exports as required.