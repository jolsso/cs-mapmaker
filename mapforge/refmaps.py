"""Third-party reference maps: unpack archives from test_maps/ and locate <map>.bsp.

Usage: python -m mapforge.refmaps            # unpack new/changed archives
       python -m mapforge.refmaps --list     # list reference maps that can be found

Archives are untrusted data: each is unpacked into its own empty directory with `unar`
(nothing in them is executed), and anything that lands outside that directory is an error.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from mapforge.config import Config, load_config

ARCHIVE_SUFFIXES = {".rar", ".zip", ".7z"}
MARKER = ".source-sha256"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_dirs(cfg: Config) -> list[Path]:
    dirs = []
    for d in cfg.data["reference_maps"]["dirs"]:
        p = Path(d)
        dirs.append(p if p.is_absolute() else cfg.root / p)
    return [d for d in dirs if d.is_dir()]


def extract_archives(cfg: Config) -> list[Path]:
    """Unpack each archive in archives_dir to extract_dir/<stem>/ (skipped if unchanged)."""
    rm = cfg.data["reference_maps"]
    src = cfg.root / rm["archives_dir"]
    dest_root = cfg.root / rm["extract_dir"]
    if not src.is_dir():
        return []
    archives = sorted(p for p in src.iterdir() if p.suffix.lower() in ARCHIVE_SUFFIXES)
    if archives and shutil.which("unar") is None:
        raise RuntimeError("`unar` not found; run inside the forge container (`./mf refmaps`)")
    out = []
    for archive in archives:
        dest = dest_root / archive.stem
        digest = _sha256(archive)
        marker = dest / MARKER
        if marker.is_file() and marker.read_text().strip() == digest:
            out.append(dest)
            continue
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        proc = subprocess.run(
            ["unar", "-q", "-f", "-D", "-o", str(dest), str(archive)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"unar failed for {archive.name}: {proc.stderr.strip()}")
        root = dest.resolve()
        for f in dest.rglob("*"):
            if not f.resolve().is_relative_to(root):
                raise RuntimeError(f"{archive.name}: entry escapes its directory: {f}")
        marker.write_text(digest)
        print(f"unpacked {archive.name} -> {dest}")
        out.append(dest)
    return out


def find_reference_bsp(cfg: Config, map_name: str) -> Path | None:
    for d in reference_dirs(cfg):
        hits = sorted(d.rglob(f"{map_name}.bsp"))
        if hits:
            return hits[0]
    return None


def list_reference_maps(cfg: Config) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in reference_dirs(cfg):
        for bsp in sorted(d.rglob("*.bsp")):
            found.setdefault(bsp.stem, bsp)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config()
    try:
        extract_archives(cfg)
    except RuntimeError as exc:
        print(f"refmaps: {exc}", file=sys.stderr)
        return 1
    if args.list:
        for name, path in list_reference_maps(cfg).items():
            print(f"{name:24} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
