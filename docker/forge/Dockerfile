# syntax=docker/dockerfile:1
# MapForge toolchain: Python + uv + go-task + SDHLT (Linux). The repo is mounted at /work.
# SDHLT 1.3.0 Linux binaries need glibc >= 2.38, hence Debian trixie.

FROM ghcr.io/astral-sh/uv:0.9.14@sha256:fef8e5fb8809f4b57069e919ffcd1529c92b432a2c8d8ad1768087b0b018d840 AS uv

FROM python:3.11-slim-trixie@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

COPY --from=uv /uv /uvx /usr/local/bin/

# unar: unpack third-party reference maps (RAR with filters) from test_maps/.
# Mesa EGL + libGL (llvmpipe): offscreen OpenGL for the renderer, no GPU or display needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        unar libegl1 libegl-mesa0 libgl1 libgl1-mesa-dri libgbm1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python3.11 \
    UV_PYTHON_DOWNLOADS=never \
    UV_FROZEN=1 \
    UV_LINK_MODE=copy \
    MAPFORGE_TOOLS_DIR=/opt/tools \
    PATH=/opt/venv/bin:$PATH

WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync

# Bake the pinned compilers into the image (URL + SHA256 come from config/pipeline.yaml).
COPY config/pipeline.yaml config/
COPY mapforge/ mapforge/
RUN python -m mapforge.tools.fetch && rm -rf /src

WORKDIR /work
CMD ["task", "--list"]
