"""Compile maps/<map>/src/<map>.map to build/<map>/<map>.bsp (CSG -> BSP -> VIS -> RAD).

Usage: python -m mapforge.compile.run --map test_box [--profile fast|final]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

from mapforge.compile.log import parse_compile_log
from mapforge.config import Config, load_config, platform_key

STEPS = ("csg", "bsp", "vis", "rad")
KEEP_ON_COMPILE = {"style", "style.json"}  # build/<map>/ entries a recompile leaves alone
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
    """Compile a map; always writes build/<map>/compile.log and compile.json (also on failure)."""
    src = cfg.path("maps_dir") / map_name / "src" / f"{map_name}.map"
    if not src.is_file():
        raise CompileError(f"Map source not found: {src}")
    flags = cfg.profile(profile)
    tools, platform_flags = tool_paths(cfg)

    # build/<map>/ is owned by the pipeline; start clean so stale .pts/.err can't mislead.
    # The style review survives: its image hashes are what makes the next review look only at
    # views that changed (mapforge.style.run), and its views carry the version they came from.
    out_dir = cfg.path("build_dir") / map_name
    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.name in KEEP_ON_COMPILE:
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    work_map = out_dir / f"{map_name}.map"
    wads = prepare_map(src, work_map, cfg.wad_dirs + [cfg.compiler_dir])
    base = out_dir / map_name
    include = [w for w in wads if w.name in cfg.data.get("wad", {}).get("include", [])]
    extra = {"csg": [arg for w in include for arg in ("-wadinclude", w.name)]}
    if src.with_suffix(".rad").is_file():
        # texture lights from the generator: hlrad reads <map>.rad next to the map by itself
        # (passing it with -lights as well loads every entry twice)
        shutil.copy2(src.with_suffix(".rad"), out_dir / f"{map_name}.rad")

    log_path = out_dir / "compile.log"
    bsp = base.with_suffix(".bsp")
    started = time.monotonic()
    failure: CompileError | None = None
    step = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            for step in STEPS:
                cmd = [
                    str(tools[step]),
                    *platform_flags,
                    *flags.get(step, []),
                    *extra.get(step, []),
                    str(base),
                ]
                _run_step(cmd, step, out_dir, base, log, log_path)
        step = None
        if not bsp.is_file():
            raise CompileError(f"No .bsp produced (see {log_path})")
    except CompileError as exc:
        failure = exc
        raise
    finally:
        report = {
            "map": map_name,
            "profile": profile,
            "ok": failure is None,
            "failure": str(failure) if failure else None,
            "failed_step": step if failure else None,
            "compiler": {k: cfg.compiler[k] for k in ("flavor", "version")},
            "seconds": round(time.monotonic() - started, 2),
            **parse_compile_log(log_path.read_text(encoding="utf-8"), base),
        }
        (out_dir / "compile.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Compiled {bsp} [{profile}] in {time.monotonic() - started:.1f}s")
    return bsp


def _run_step(
    cmd: list[str], step: str, out_dir: Path, base: Path, log: TextIO, log_path: Path
) -> None:
    log.write(f"$ {' '.join(cmd)}\n")
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, errors="replace")
    output = proc.stdout + proc.stderr
    log.write(output)
    log.write(f"[{step}] exit={proc.returncode} time={time.monotonic() - t0:.1f}s\n\n")
    log.flush()
    print(f"  {step}: exit {proc.returncode} ({time.monotonic() - t0:.1f}s)")

    # hlbsp exits 0 on a leak, so look for the message and the pointfile too.
    if "LEAK" in output or base.with_suffix(".pts").exists() or base.with_suffix(".lin").exists():
        raise CompileError(f"{step}: map leaks (see {log_path} and {base}.pts)")
    if base.with_suffix(".err").exists() or ERROR_LINE.search(output):
        raise CompileError(f"{step}: compiler reported errors (see {log_path})")
    if proc.returncode != 0:
        raise CompileError(f"{step}: exited with code {proc.returncode} (see {log_path})")


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
