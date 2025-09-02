from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from app.cli.main import app as cli_app


def test_register_local_gpkg_for_skjern(tmp_path: Path) -> None:
    """Register a local GPKG for bbox around 'Bredgade 1, 6900 Skjern' (offline)."""
    lon, lat = 8.4971136, 55.94360765
    eps = 0.0003
    bbox = f"{lon - eps},{lat - eps},{lon + eps},{lat + eps}"

    out_dir = tmp_path / "cache"
    gpkg_path = tmp_path / "building_inspire.gpkg"
    gpkg_path.write_bytes(b"")  # create an empty placeholder file

    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        [
            "fetch",
            "--bbox",
            bbox,
            "--out",
            str(out_dir),
            "--gpkg",
            str(gpkg_path),
        ],
    )

    assert result.exit_code == 0, result.output

    manifest_files = list(out_dir.glob("*.fetch.json"))
    assert manifest_files, "No manifest written"
    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert manifest.get("source") == "local_gpkg"
    assert manifest.get("gpkg")
