from __future__ import annotations

import hashlib
from typing import Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .models import (
    ConceptRequest,
    EditRequest,
    EditResponse,
    Entity,
    Geometry2D,
    LayoutGraph,
    MapExport,
    MapIntent,
    Node,
    Edge,
    Polygon,
)


app = FastAPI(title="cs-mapmaker API", version="0.1.0")

# Permissive CORS for local dev; tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve a minimal static UI from /ui (frontend/ directory at repo root)
try:
    app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")
except Exception:
    # Directory may not exist in some environments; ignore mounting failure
    pass

@app.get("/")
def root() -> Dict[str, str]:
    return {"service": "cs-mapmaker", "status": "ok"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy"}


def _infer_intent(prompt: str) -> MapIntent:
    p = prompt.lower().strip()
    map_type = "cs"
    if any(k in p for k in ["defusal", "bomb", " de ", "de_"]):
        map_type = "de"

    symmetry = None
    if any(k in p for k in ["symmetric", "symmetrical", "mirror"]):
        symmetry = "mirror"

    size = None
    for s in ("small", "medium", "large"):
        if s in p:
            size = s
            break

    theme = None
    for t in ("urban", "desert", "snow", "jungle", "industrial"):
        if t in p:
            theme = t
            break

    # Stable deterministic seed from prompt
    seed = int(hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8], 16)

    return MapIntent(
        prompt=prompt,
        map_type=map_type,
        symmetry=symmetry,
        size=size,
        theme=theme,
        seed=seed,
    )


@app.post("/concepts", response_model=MapIntent)
def create_concept(req: ConceptRequest) -> MapIntent:
    """Prompt -> MapIntent (naive parse)."""
    return _infer_intent(req.prompt)


@app.post("/layouts", response_model=LayoutGraph)
def create_layout(intent: MapIntent) -> LayoutGraph:
    """Intent -> very simple 2-node layout (A-B)."""

    # Width hint by size (arbitrary but deterministic)
    width_map = {"small": 3.0, "medium": 5.0, "large": 7.5}
    node_width = width_map.get(intent.size or "", 4.0)

    nodes = [
        Node(id="A", kind="room", width=node_width),
        Node(id="B", kind="room", width=node_width),
    ]
    edges = [Edge(a="A", b="B")]
    return LayoutGraph(nodes=nodes, edges=edges)


@app.post("/geometry", response_model=Geometry2D)
def create_geometry(layout: LayoutGraph) -> Geometry2D:
    """Layout -> minimal 10x10 square geometry."""
    # Simple deterministic square; future: transform graph to rectilinear polygons
    poly = Polygon(id="p1", points=[(0, 0), (10, 0), (10, 10), (0, 10)])
    return Geometry2D(polygons=[poly], entities=[])


@app.post("/maps", response_model=MapExport)
def export_map(geometry: Geometry2D) -> MapExport:
    """Geometry -> export locations (stub)."""
    # In MVP stub, just return stable placeholder paths
    return MapExport(
        map_url="/artifacts/demo/map.map",
        report_url="/artifacts/demo/validation.json",
    )


@app.post("/edits", response_model=EditResponse)
def propose_edit(req: EditRequest) -> EditResponse:
    """NL prompt -> JSON Patch -> new version id (stub)."""
    # Stable short version id from prompt
    digest = hashlib.md5(req.prompt.encode("utf-8")).hexdigest()[:8]
    version_id = f"v-{digest}"
    # Minimal: empty patch; future: generate RFC6902 JSON Patch
    return EditResponse(version_id=version_id, patch=[])
