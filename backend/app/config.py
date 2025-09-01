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
        df_url = os.getenv("DF_WFS_URL") or data.get("dataforsyningen", {}).get("wfs_url")
        df_typename = os.getenv("DF_WFS_TYPENAME") or data.get("dataforsyningen", {}).get(
            "wfs_typename"
        )

        return AppConfig(dataforsyningen=WFSConfig(url=df_url, typename=df_typename))

