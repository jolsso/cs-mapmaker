# API Contracts (Minimal)

Pydantic (Python / FastAPI):
```python
from typing import List, Optional
from pydantic import BaseModel, Field

class MapIntent(BaseModel):
    prompt: str = Field(..., description='Natural language concept')
    map_type: str = Field('cs', description='Mode, e.g., cs/de/dm')
    symmetry: Optional[str] = None  # none, mirror, rotational
    size: Optional[str] = None      # small/medium/large
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
    points: List[tuple]
    elevation: float = 0.0

class Entity(BaseModel):
    type: str
    position: tuple

class Geometry2D(BaseModel):
    polygons: List[Polygon]
    entities: List[Entity] = []

class MapExport(BaseModel):
    map_url: str
    report_url: Optional[str] = None
```

TypeScript (Svelte):
```ts
export type MapIntent = {
  prompt: string;
  map_type: string; // cs/de/dm
  symmetry?: string;
  size?: string;
  theme?: string;
  seed: number;
};

export type Node = { id: string; kind: string; width?: number };
export type Edge = { a: string; b: string };
export type LayoutGraph = { nodes: Node[]; edges: Edge[] };

export type Polygon = { id: string; points: [number,number][]; elevation?: number };
export type Entity = { type: string; position: [number,number] };
export type Geometry2D = { polygons: Polygon[]; entities?: Entity[] };

export type MapExport = { map_url: string; report_url?: string };
```

Example requests/responses:
```json
// POST /concepts (body)
{ "prompt": "Symmetric hostage rescue, two routes, small" }
```
```json
// POST /concepts (response)
{ "prompt":"Symmetric hostage rescue, two routes, small", "map_type":"cs", "symmetry":"mirror", "size":"small", "seed":0 }
```
```json
// POST /layouts (response)
{ "nodes":[{"id":"A","kind":"room"},{"id":"B","kind":"room"}], "edges":[{"a":"A","b":"B"}] }
```
```json
// POST /geometry (response)
{ "polygons":[{"id":"p1","points":[[0,0],[10,0],[10,10],[0,10]]}], "entities":[] }
```
```json
// POST /maps (response)
{ "map_url":"/artifacts/x/map.map", "report_url":"/artifacts/x/validation.json" }
```
