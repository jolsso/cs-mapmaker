from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from app.cli.main import app as cli_app


class _FakeResp:
    def __init__(self, url: str, data: dict[str, Any], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code
        self.url = url
        self.text = json.dumps(data)

    def json(self) -> dict[str, Any]:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_first_page_for_skjern_bredgade_1(monkeypatch, tmp_path: Path) -> None:
    """Fetch first page using a bbox around 'Bredgade 1, 6900 Skjern' (mocked WFS)."""
    # "Bredgade 1, 6900 Skjern" (from Dataforsyningen Adresser API at test time)
    lon, lat = 8.4971136, 55.94360765
    eps = 0.0003  # ~30m margin in lat/lon
    bbox = f"{lon - eps},{lat - eps},{lon + eps},{lat + eps}"

    # Mock the WFS call to return a tiny FeatureCollection within bbox
    def _fake_get(url: str, params: dict[str, Any], headers=None, timeout: int = 30):  # type: ignore[override]
        # Only intercept WFS-like calls; otherwise, fail fast to avoid real network
        if "service" in params and str(params.get("service")).upper() == "WFS":
            fc = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": 1},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [lon - 0.0001, lat - 0.0001],
                                    [lon + 0.0001, lat - 0.0001],
                                    [lon + 0.0001, lat + 0.0001],
                                    [lon - 0.0001, lat + 0.0001],
                                    [lon - 0.0001, lat - 0.0001],
                                ]
                            ],
                        },
                    }
                ],
            }
            # Build a representative URL with encoded params for manifest
            from urllib.parse import urlencode

            req_url = f"{url}?{urlencode(params)}"
            return _FakeResp(req_url, fc)
        raise AssertionError("Unexpected external HTTP call in test")

    import requests

    monkeypatch.setattr(requests, "get", _fake_get)

    out_dir = tmp_path / "cache"
    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        [
            "fetch",
            "--bbox",
            bbox,
            "--out",
            str(out_dir),
            "--wfs-url",
            "https://api.dataforsyningen.dk/building_inspire",
            "--typename",
            "BU.Building",
            "--count",
            "10",
        ],
    )

    assert result.exit_code == 0, result.output

    # Read generated GeoJSON
    geojson_files = list(out_dir.glob("*.geojson"))
    assert geojson_files, "No GeoJSON written"
    data = json.loads(geojson_files[0].read_text(encoding="utf-8"))
    assert data.get("type") == "FeatureCollection"
    assert len(data.get("features", [])) == 1

    # Manifest present and includes request_url
    manifest_files = list(out_dir.glob("*.fetch.json"))
    assert manifest_files, "No manifest written"
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert manifest.get("request_url")
