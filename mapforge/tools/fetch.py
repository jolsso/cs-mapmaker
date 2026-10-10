"""Download and unpack the pinned map compilers into tools/.

Usage: python -m mapforge.tools.fetch
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from mapforge.config import Config, load_config, platform_key

MARKER = ".sha256"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_subtree(archive: Path, root: str, dest: Path) -> None:
    """Extract only members under `root/` into dest, refusing path traversal."""
    prefix = PurePosixPath(root)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            member = PurePosixPath(info.filename)
            if info.is_dir() or prefix not in member.parents:
                continue
            rel = member.relative_to(prefix)
            if rel.is_absolute() or ".." in rel.parts:
                raise RuntimeError(f"Unsafe path in archive: {info.filename}")
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def fetch(cfg: Config) -> Path:
    c = cfg.compiler
    dest = cfg.compiler_dir
    marker = dest / MARKER
    if marker.exists() and marker.read_text().strip() == c["sha256"]:
        print(f"{c['flavor']} {c['version']} already present in {dest}")
        return dest

    with tempfile.TemporaryDirectory(prefix="mapforge-fetch-") as tmp:
        archive = Path(tmp) / "download.zip"
        print(f"Downloading {c['url']}")
        with urllib.request.urlopen(c["url"]) as resp, archive.open("wb") as out:
            shutil.copyfileobj(resp, out)
        digest = sha256_of(archive)
        if digest != c["sha256"]:
            raise RuntimeError(f"SHA256 mismatch: expected {c['sha256']}, got {digest}")

        if dest.exists():
            shutil.rmtree(dest)
        extract_subtree(archive, c["archive_root"], dest)

    plat = c["platforms"][platform_key()]
    bin_dir = dest / plat["bin_dir"]
    for step in ("csg", "bsp", "vis", "rad"):
        exe = bin_dir / plat[step]
        if not exe.exists():
            raise RuntimeError(f"Expected compiler binary missing after extract: {exe}")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    marker.write_text(c["sha256"])
    print(f"Installed {c['flavor']} {c['version']} into {dest}")
    return dest


def main() -> int:
    try:
        fetch(load_config())
    except Exception as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
