"""Build the simulation server image (docker/hlds/ + server/plugins/) through the Docker socket.

The build context is assembled here, so it holds exactly these files; the tag carries a hash of
them, so the image is rebuilt only when the Dockerfile, the add-on pins or a plugin change.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from typing import Any

from mapforge.config import Config

HLDS_FILES = ("Dockerfile", "addons.lock", "install_addons.sh", "entrypoint.sh")


def context_files(cfg: Config) -> dict[str, bytes]:
    """name in the build context -> content (LF line endings, as the files are used on Linux)."""
    files = {name: (cfg.root / "docker" / "hlds" / name).read_bytes() for name in HLDS_FILES}
    for sma in sorted((cfg.root / "server" / "plugins").glob("*.sma")):
        files[f"plugins/{sma.name}"] = sma.read_bytes()
    return {k: v.replace(b"\r\n", b"\n") for k, v in files.items()}


def image_tag(cfg: Config, files: dict[str, bytes] | None = None) -> str:
    files = files if files is not None else context_files(cfg)
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + files[name] + b"\0")
    return f"{cfg.data['simulate']['image']}:{h.hexdigest()[:12]}"


def _context_tar(files: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def ensure_image(cfg: Config, client: Any, log=print) -> str:
    """Return the image tag, building it if this exact context has not been built yet."""
    import docker.errors

    files = context_files(cfg)
    tag = image_tag(cfg, files)
    try:
        client.images.get(tag)
        return tag
    except docker.errors.ImageNotFound:
        pass
    log(f"building {tag} (first time downloads HLDS via SteamCMD, ~1 GB) ...")
    stream = client.api.build(
        fileobj=_context_tar(files), custom_context=True, tag=tag, rm=True, decode=True
    )
    tail: list[str] = []
    for chunk in stream:
        line = chunk.get("stream", "").rstrip()
        if line:
            tail = (tail + [line])[-40:]
            if line.startswith("Step "):
                log("  " + line)
        if "error" in chunk:
            raise RuntimeError("image build failed:\n" + "\n".join(tail) + "\n" + chunk["error"])
    client.images.get(tag).tag(cfg.data["simulate"]["image"], "latest")
    return tag


def build_info(client: Any, tag: str) -> str:
    """BUILD_INFO of the image (HLDS build id + add-on pins), for the run metadata."""
    out = client.containers.run(
        tag, entrypoint=["cat", "/home/hlds/hlds/BUILD_INFO"], remove=True, network_disabled=True
    )
    return out.decode("utf-8", "replace")
