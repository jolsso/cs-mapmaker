from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None


DEFAULT_CONFIG_PATHS = (
    Path("config.yaml"),
    Path("backend/config.yaml"),
    Path("backend/config/config.yaml"),
)


@dataclass(frozen=True)
class WFSConfig:
    url: Optional[str] = None
    typename: Optional[str] = None
    api_key: Optional[str] = None
    api_key_header: Optional[str] = None  # e.g., 'X-API-Key'
    api_key_query: Optional[str] = None   # e.g., 'api-key' or 'token'


@dataclass(frozen=True)
class AppConfig:
    dataforsyningen: WFSConfig

    @staticmethod
    def load(path: Optional[Path] = None) -> "AppConfig":
        data = {}
        cfg_path: Optional[Path] = None
        if path and path.exists():
            cfg_path = path
        else:
            for p in DEFAULT_CONFIG_PATHS:
                if p.exists():
                    cfg_path = p
                    break

        if cfg_path and yaml is not None:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        # Env overrides
        df_section = data.get("dataforsyningen", {})
        df_url = os.getenv("DF_WFS_URL") or df_section.get("wfs_url")
        df_typename = os.getenv("DF_WFS_TYPENAME") or df_section.get("wfs_typename")
        df_api_key = os.getenv("DF_API_KEY") or df_section.get("api_key")
        df_api_key_header = os.getenv("DF_API_KEY_HEADER") or df_section.get("api_key_header")
        df_api_key_query = os.getenv("DF_API_KEY_QUERY") or df_section.get("api_key_query")

        return AppConfig(
            dataforsyningen=WFSConfig(
                url=df_url,
                typename=df_typename,
                api_key=df_api_key,
                api_key_header=df_api_key_header,
                api_key_query=df_api_key_query,
            )
        )
