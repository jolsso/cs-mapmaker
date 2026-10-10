"""Load config/pipeline.yaml (+ optional pipeline.local.yaml override)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return base with override merged in; nested dicts merge, everything else replaces."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


@dataclass(frozen=True)
class Config:
    root: Path
    data: dict[str, Any]

    def path(self, key: str) -> Path:
        return self.root / self.data["paths"][key]

    @property
    def wad_dirs(self) -> list[Path]:
        return [self.root / d for d in self.data["paths"]["wad_dirs"]]

    @property
    def compiler(self) -> dict[str, Any]:
        return self.data["compiler"]

    @property
    def compiler_dir(self) -> Path:
        c = self.compiler
        return self.path("tools_dir") / f"{c['flavor']}-{c['version']}"

    def profile(self, name: str) -> dict[str, list[str]]:
        profiles = self.data["profiles"]
        if name not in profiles:
            raise KeyError(f"Unknown profile {name!r}; available: {sorted(profiles)}")
        return profiles[name]


def load_config(root: Path = REPO_ROOT) -> Config:
    config_dir = root / "config"
    data = yaml.safe_load((config_dir / "pipeline.yaml").read_text(encoding="utf-8"))
    local = config_dir / "pipeline.local.yaml"
    if local.exists():
        data = deep_merge(data, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    return Config(root=root, data=data)
