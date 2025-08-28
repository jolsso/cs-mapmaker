from typing import List, Optional, Tuple
from pydantic import BaseModel, Field


class MapIntent(BaseModel):
    prompt: str = Field(..., description="Natural language concept")
    map_type: str = Field("cs", description="Mode, e.g., cs/de/dm")
    symmetry: Optional[str] = None  # none, mirror, rotational
    size: Optional[str] = None  # small/medium/large
    theme: Optional[str] = None
    seed: int = 0


class Node(BaseModel):
    id: str
    kind: str  # room, corridor, spawn, site
    width: float = 0.0


class Edge(BaseModel):
    a: str
    b: str


class LayoutGraph(BaseModel):
    nodes: List[Node]
    edges: List[Edge]


class Polygon(BaseModel):
    id: str
    points: List[Tuple[float, float]]
    elevation: float = 0.0


class Entity(BaseModel):
    type: str
    position: Tuple[float, float]


class Geometry2D(BaseModel):
    polygons: List[Polygon]
    entities: List[Entity] = []


class MapExport(BaseModel):
    map_url: str
    report_url: Optional[str] = None


# Endpoint-specific lightweight contracts
class ConceptRequest(BaseModel):
    prompt: str


class EditRequest(BaseModel):
    prompt: str
    base_version_id: Optional[str] = None


class EditResponse(BaseModel):
    version_id: str
    patch: List[dict] = []  # JSON Patch (RFC 6902)

