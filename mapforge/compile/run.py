"""Compile maps/<map>/src/<map>.map to build/<map>/<map>.bsp (CSG -> BSP -> VIS -> RAD).

Usage: python -m mapforge.compile.run --map test_box [--profile fast|final]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mapforge.config import Config, load_config, platform_key

STEPS = ("csg", "bsp", "vis", "rad")
WAD_KEY = re.compile(r'("wad"\s+")([^"]*)(")')
ERROR_LINE = re.compile(r"^\s*Error:", re.MULTILINE)


class CompileError(RuntimeError):
    pass


def resolve_wads(value: str, search_dirs: list[Path]) -> list[Path]:
    """Resolve each entry of a worldspawn `wad` value by file name against search_dirs."""
    resolved = []
    for entry in filter(None, (e.strip() for e in value.split(";"))):
        name = Path(entry.replace("\\", "/")).name
        for d in search_dirs:
            if (d / name).is_file():
                resolved.append((d / name).resolve())
                break
        else:
            dirs = ", ".join(str(d) for d in search_dirs)
            raise CompileError(f"WAD {name!r} not found in: {dirs}")
    return resolved


def prepare_map(src: Path, dest: Path, search_dirs: list[Path]) -> list[Path]:
    """Copy src to dest with the worldspawn `wad` key rewritten to absolute paths."""
    text = src.read_text(encoding="utf-8")
    match = WAD_KEY.search(text)
    if not match:
        raise CompileError(f'{src}: worldspawn has no "wad" key')
    wads = resolve_wads(match.group(2), search_dirs)
    joined = ";".join(p.as_posix() for p in wads)
    text = text[: match.start(2)] + joined + text[match.end(2) :]
    dest.write_text(text, encoding="utf-8")
    return wads


def tool_paths(cfg: Config) -> tuple[dict[str, Path], list[str]]:
    plat = cfg.compiler["platforms"][platform_key()]
    bin_dir = cfg.compiler_dir / plat["bin_dir"]
    tools = {step: bin_dir / plat[step] for step in STEPS}
    missing = [str(p) for p in tools.values() if not p.exists()]
    if missing:
        raise CompileError(
            "Compiler binaries missing (run `uv run task tools:fetch`): " + ", ".join(missing)
        )
    return tools, list(plat.get("flags", []))


def compile_map(cfg: Config, map_name: str, profile: str = "fast") -> Path:
    src = cfg.path("maps_dir") / map_name / "src" / f"{map_name}.map"
    if not src.is_file():
        raise CompileError(f"Map source not found: {src}")
    flags = cfg.profile(profile)
    tools, platform_flags = tool_paths(cfg)

    # build/<map>/ is owned by the pipeline; start clean so stale .pts/.err can't mislead.
    out_dir = cfg.path("build_dir") / map_name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    work_map = out_dir / f"{map_name}.map"
    wads = prepare_map(src, work_map, cfg.wad_dirs + [cfg.compiler_dir])
    base = out_dir / map_name
    include = [w for w in wads if w.name in cfg.data.get("wad", {}).get("include", [])]
    extra = {"csg": [arg for w in include for arg in ("-wadinclude", w.name)]}

    log_path = out_dir / "compile.log"
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        for step in STEPS:
            cmd = [
                str(tools[step]),
                *platform_flags,
                *flags.get(step, []),
                *extra.get(step, []),
                str(base),
            ]
            log.write(f"$ {' '.join(cmd)}\n")
            t0 = time.monotonic()
            proc = subprocess.run(
                cmd, cwd=out_dir, capture_output=True, text=True, errors="replace"
            )
            output = proc.stdout + proc.stderr
            log.write(output)
            log.write(f"[{step}] exit={proc.returncode} time={time.monotonic() - t0:.1f}s\n\n")
            log.flush()
            print(f"  {step}: exit {proc.returncode} ({time.monotonic() - t0:.1f}s)")

            if (
                "LEAK" in output
                or base.with_suffix(".pts").exists()
                or base.with_suffix(".lin").exists()
            ):
                raise CompileError(f"{step}: map leaks (see {log_path} and {base}.pts)")
            if base.with_suffix(".err").exists() or ERROR_LINE.search(output):
                raise CompileError(f"{step}: compiler reported errors (see {log_path})")
            if proc.returncode != 0:
                raise CompileError(f"{step}: exited with code {proc.returncode} (see {log_path})")

    bsp = base.with_suffix(".bsp")
    if not bsp.is_file():
        raise CompileError(f"No .bsp produced (see {log_path})")
    print(f"Compiled {bsp} [{profile}] in {time.monotonic() - started:.1f}s")
    return bsp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    parser.add_argument("--profile", default="fast")
    args = parser.parse_args(argv)
    try:
        compile_map(load_config(), args.map, args.profile)
    except (CompileError, KeyError) as exc:
        print(f"compile failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
