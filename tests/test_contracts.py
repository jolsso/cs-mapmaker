from fastapi.testclient import TestClient
from backend.app.main import app


client = TestClient(app)


def test_root_and_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json().get("service") == "cs-mapmaker"

    h = client.get("/health")
    assert h.status_code == 200
    assert h.json().get("status") == "healthy"


def test_concepts_endpoint_contract():
    payload = {"prompt": "Symmetric hostage rescue, two routes, small"}
    r = client.post("/concepts", json=payload)
    assert r.status_code == 200
    body = r.json()

    # Expected fields per docs/spec.md and current implementation
    assert body["prompt"] == payload["prompt"]
    assert body["map_type"] == "cs"
    assert body["symmetry"] == "mirror"
    assert body["size"] == "small"
    assert isinstance(body["seed"], int)


def test_layouts_endpoint_contract():
    # Derive intent from the same prompt, then request layout
    intent = client.post(
        "/concepts", json={"prompt": "Symmetric hostage rescue, two routes, small"}
    ).json()

    r = client.post("/layouts", json=intent)
    assert r.status_code == 200
    body = r.json()

    assert set(body.keys()) == {"nodes", "edges"}
    assert len(body["nodes"]) == 2
    ids = {n["id"] for n in body["nodes"]}
    assert ids == {"A", "B"}
    # Width derived from size=small in current impl
    for n in body["nodes"]:
        assert n["kind"] == "room"
        assert n["width"] == 3.0
    assert body["edges"] == [{"a": "A", "b": "B"}]


def test_geometry_endpoint_contract():
    intent = client.post(
        "/concepts", json={"prompt": "Symmetric hostage rescue, two routes, small"}
    ).json()
    layout = client.post("/layouts", json=intent).json()

    r = client.post("/geometry", json=layout)
    assert r.status_code == 200
    body = r.json()

    assert set(body.keys()) == {"polygons", "entities"}
    assert len(body["polygons"]) == 1
    poly = body["polygons"][0]
    assert poly["id"] == "p1"
    assert poly["points"] == [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert body["entities"] == []


def test_maps_export_contract():
    intent = client.post(
        "/concepts", json={"prompt": "Symmetric hostage rescue, two routes, small"}
    ).json()
    layout = client.post("/layouts", json=intent).json()
    geometry = client.post("/geometry", json=layout).json()

    r = client.post("/maps", json=geometry)
    assert r.status_code == 200
    body = r.json()

    assert "map_url" in body and isinstance(body["map_url"], str)
    assert "report_url" in body
    assert body["map_url"].startswith("/artifacts/")


def test_edits_patch_contract():
    payload = {"prompt": "Move CT spawn 200 units east"}
    r1 = client.post("/edits", json=payload)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["version_id"].startswith("v-")
    assert len(body1["version_id"]) == 10  # v- + 8 hex
    assert isinstance(body1["patch"], list)

    # Deterministic version id for same prompt
    r2 = client.post("/edits", json=payload)
    assert r2.json()["version_id"] == body1["version_id"]

