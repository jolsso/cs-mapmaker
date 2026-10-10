"""Run one simulation server: create the container, copy map + config in, wait, copy results out.

No bind mounts: files go in and out with put_archive/get_archive, so this works from the forge
container (whose /work paths mean nothing to the Docker host).
"""

from __future__ import annotations

import io
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CSTRIKE = "/home/hlds/hlds/cstrike"
HLDS_UID = 1000  # first user created in docker/hlds/Dockerfile


@dataclass
class ServerJob:
    map_name: str
    run_id: str
    rounds: int
    out_dir: Path
    bsp: Path | None = None  # None: a map shipped with the game image
    graph: Path | None = None  # cached YaPB graph for this .bsp
    port: int | None = None  # host UDP port for spectators
    demo: bool = False
    timescale: float = 1.0
    extra_cvars: dict[str, Any] = field(default_factory=dict)


def _cvar(value: Any) -> str:
    return f'"{value}"' if isinstance(value, str) else str(value)


def server_cfg(sim: dict[str, Any], job: ServerJob) -> str:
    lines = [
        "// written by mapforge.simulate; exec'd by the tracker plugin (plugin_cfg)",
        f'hostname "MapForge {job.map_name} {job.run_id}"',
    ]
    cvars = {**sim["cvars"], **job.extra_cvars}
    cvars.update(mf_run_id=job.run_id, mf_max_rounds=job.rounds, sys_timescale=job.timescale)
    lines += [f"{k} {_cvar(v)}" for k, v in cvars.items()]
    return "\n".join(lines) + "\n"


def yapb_cfg(sim: dict[str, Any]) -> str:
    cvars = {**sim["yapb"], "yb_quota": 2 * int(sim["bots_per_team"]), "yb_quota_mode": "normal"}
    lines = ["// mapforge.simulate overrides (appended to yapb.cfg)"]
    lines += [f"{k} {_cvar(v)}" for k, v in cvars.items()]
    return "\n".join(lines) + "\n"


def _tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.uid, info.gid, info.mode = len(data), HLDS_UID, HLDS_UID, 0o644
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fetch(container: Any, path: str, dest: Path, suffixes: tuple[str, ...] = ()) -> list[Path]:
    """Copy the regular files under `path` (file or dir) into dest/ (flat); [] if missing."""
    import docker.errors

    try:
        stream, _ = container.get_archive(path)
    except docker.errors.NotFound:
        return []
    raw = io.BytesIO(b"".join(stream))
    out = []
    with tarfile.open(fileobj=raw) as tar:
        for m in tar.getmembers():
            name = Path(m.name).name
            if not m.isfile() or (suffixes and not name.endswith(suffixes)):
                continue
            dest.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(m)
            if data is not None:
                (dest / name).write_bytes(data.read())
                out.append(dest / name)
    return out


def run_server(
    client: Any, tag: str, sim: dict[str, Any], job: ServerJob, log=print
) -> dict[str, Any]:
    """Run one server to completion. Results land in job.out_dir; returns a status dict."""
    import requests.exceptions

    files = {
        "mapforge.cfg": server_cfg(sim, job).encode(),
        "addons/yapb/conf/mapforge_yapb.cfg": yapb_cfg(sim).encode(),
    }
    if job.bsp is not None:
        files[f"maps/{job.map_name}.bsp"] = job.bsp.read_bytes()
    if job.graph is not None and job.graph.is_file():
        files[f"addons/yapb/data/graph/{job.map_name}.graph"] = job.graph.read_bytes()

    env = {
        "MF_MAP": job.map_name,
        "MF_RUN_ID": job.run_id,
        "MF_MAXPLAYERS": str(sim["maxplayers"]),
        "MF_TICRATE": str(sim["ticrate"]),
        "MF_DEMO": "1" if job.demo else "0",
    }
    ports = {"27015/udp": (sim["bind"], job.port)} if job.port else None
    name = f"mapforge-{job.map_name}-{job.run_id}"
    for old in client.containers.list(all=True, filters={"name": f"^{name}$"}):
        old.remove(force=True)  # left over from an interrupted run
    container = client.containers.create(tag, environment=env, ports=ports, name=name, detach=True)
    status: dict[str, Any] = {"run_id": job.run_id, "port": job.port, "rounds_wanted": job.rounds}
    start = time.time()
    try:
        container.put_archive(CSTRIKE, _tar(files))
        container.start()
        if job.port:
            log(f"  {job.run_id}: running, spectate with `connect localhost:{job.port}`")
        timeout = sim["startup_timeout_s"] + job.rounds * sim["round_timeout_s"]
        try:
            result = container.wait(timeout=timeout)
            status.update(exit_code=result.get("StatusCode"), timed_out=False)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            container.kill()
            status.update(exit_code=None, timed_out=True)
        status["wall_s"] = round(time.time() - start, 1)
        job.out_dir.mkdir(parents=True, exist_ok=True)
        (job.out_dir / "server.log").write_bytes(container.logs())
        data = f"{CSTRIKE}/logs/mapforge/{job.map_name}_{job.run_id}"
        got = _fetch(container, data, job.out_dir)
        status["done"] = any(p.name == "DONE" for p in got)
        _fetch(container, f"{CSTRIKE}/addons/yapb/data/graph/{job.map_name}.graph", job.out_dir)
        if job.demo:
            demos = _fetch(container, f"{CSTRIKE}/demos", job.out_dir / "demos", (".dem",))
            status["demos"] = [p.name for p in demos]
    finally:
        container.remove(force=True)
    return status
