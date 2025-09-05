#!/usr/bin/env python3
"""
Download the Denmark buildings dataset ZIP and extract it into the cache folder.

Default output directory: ./cache

Usage:
  python scripts/download_dk_buildings.py
  python scripts/download_dk_buildings.py --output cache --keep-zip

Notes:
- Uses only the Python standard library (no extra deps).
- Skips re-downloading unless --force-download is provided when the ZIP already exists.
- Extracts into the output directory; prevents Zip Slip via path validation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import zipfile


DEFAULT_URL = (
    "https://ftp.sdfe.dk/main.html?download&weblink=ca102693c712ad4159e4a6f343da60d5&realfilename=DK%5FBuilding%2Ezip"
)


def human_size(num_bytes: Optional[int]) -> str:
    if num_bytes is None:
        return "unknown"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:0.1f} {unit}"
        size /= 1024.0


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _render_progress(bytes_read: int, total: Optional[int], start_time: float, bar_width: int = 40) -> str:
    elapsed = time.time() - start_time
    speed = bytes_read / max(1e-6, elapsed)
    speed_str = f"{human_size(int(speed))}/s"
    if total and total > 0:
        pct = bytes_read / total
        filled = int(bar_width * pct)
        bar = "=" * max(0, filled - 1) + (">" if filled > 0 else "")
        bar = bar.ljust(bar_width, ".")
        eta = (total - bytes_read) / max(1e-6, speed)
        return (
            f"[{bar}] {pct*100:5.1f}%  "
            f"{human_size(bytes_read)} / {human_size(total)}  "
            f"{speed_str}  ETA {_format_duration(eta)}"
        )
    else:
        # Unknown total size
        return (
            f"{human_size(bytes_read)}  "
            f"{speed_str}  Elapsed {_format_duration(elapsed)}"
        )


def download_file(url: str, dest: Path, quiet: bool = False, timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)

    req = Request(url, headers={"User-Agent": "cs-mapmaker-downloader/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            length_header = resp.headers.get("Content-Length")
            total = int(length_header) if length_header and length_header.isdigit() else None

            if not quiet:
                size_str = human_size(total)
                print(f"Downloading to {dest} ({size_str})...")

            chunk_size = 1024 * 1024  # 1 MiB
            bytes_read = 0
            t0 = time.time()
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_read += len(chunk)
                    if not quiet:
                        prog = _render_progress(bytes_read, total, t0)
                        print(f"\r{prog}", end="", flush=True)
            if not quiet:
                dt = time.time() - t0
                print(f"\nDone in {dt:0.1f}s.")
    except HTTPError as e:
        raise SystemExit(f"HTTP error {e.code}: {e.reason}")
    except URLError as e:
        raise SystemExit(f"URL error: {e.reason}")


def safe_extract_zip(zip_path: Path, dest_dir: Path, quiet: bool = False) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not quiet:
        print(f"Extracting {zip_path} -> {dest_dir}")

    base = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            # Normalize the path to prevent Zip Slip
            target = (dest_dir / info.filename).resolve()
            try:
                target.relative_to(base)
            except ValueError:
                raise SystemExit(f"Refusing to extract outside destination: {info.filename}")

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download and unzip Denmark buildings dataset into cache.")
    p.add_argument("--url", default=DEFAULT_URL, help="Source URL for DK_Building.zip")
    p.add_argument("--output", default=str(Path("cache")), help="Output directory for extraction (default: cache)")
    p.add_argument("--zip-name", default="DK_Building.zip", help="Local ZIP filename (default: DK_Building.zip)")
    p.add_argument("--keep-zip", action="store_true", help="Keep ZIP after extraction")
    p.add_argument("--force-download", action="store_true", help="Redownload even if ZIP exists")
    p.add_argument("--timeout", type=int, default=60, help="Download timeout in seconds (default: 60)")
    p.add_argument("--quiet", action="store_true", help="Reduce output verbosity")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    zip_path = out_dir / args.zip_name

    if zip_path.exists() and not args.force_download:
        if not args.quiet:
            print(f"ZIP already exists: {zip_path} (use --force-download to redownload)")
    else:
        download_file(args.url, zip_path, quiet=args.quiet, timeout=args.timeout)

    # Always extract into the output directory as requested.
    safe_extract_zip(zip_path, out_dir, quiet=args.quiet)

    if not args.keep_zip:
        try:
            zip_path.unlink()
            if not args.quiet:
                print(f"Removed ZIP: {zip_path}")
        except OSError:
            if not args.quiet:
                print(f"Warning: failed to remove {zip_path}")

    if not args.quiet:
        print("All done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
