from __future__ import annotations

from typing import Tuple

import requests


def fetch_wfs_bbox_first_page(
    *,
    wfs_url: str,
    typename: str,
    bbox: Tuple[float, float, float, float],
    srs_name: str = "EPSG:4326",
    count: int = 100,
    timeout: int = 30,
):
    """Fetch the first page of features for a bbox from a WFS endpoint as GeoJSON.

    Returns a tuple of (geojson_dict, request_url).

    This uses WFS 2.0.0 with `typenames` and `count`. Some servers may require
    different parameter names (e.g., `typeName`) or authentication — adjust as needed.
    """

    minx, miny, maxx, maxy = bbox
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typenames": typename,
        "srsName": srs_name,
        "bbox": f"{minx},{miny},{maxx},{maxy},{srs_name}",
        "outputFormat": "application/json",
        "count": str(count),
    }

    headers = {"Accept": "application/json"}
    resp = requests.get(wfs_url, params=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        # Provide helpful context if server responded with non-JSON
        snippet = resp.text[:400]
        raise RuntimeError(
            f"WFS did not return JSON (status {resp.status_code}). Body: {snippet}"
        ) from exc
    return data, resp.url

