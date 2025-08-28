import pytest

# Red tests defining one key behavior each (minimal, to drive FastAPI work)

def test_concepts_endpoint_contract():
    pytest.fail("Implement POST /concepts: {prompt} -> MapIntent (see docs/spec.md)")


def test_layouts_endpoint_contract():
    pytest.fail("Implement POST /layouts: MapIntent -> LayoutGraph (see docs/spec.md)")


def test_geometry_endpoint_contract():
    pytest.fail("Implement POST /geometry: LayoutGraph -> Geometry2D (see docs/spec.md)")


def test_maps_export_contract():
    pytest.fail("Implement POST /maps: Geometry2D -> MapExport (see docs/spec.md)")


def test_edits_patch_contract():
    pytest.fail("Implement POST /edits: NL prompt -> JSON Patch -> new version id")
