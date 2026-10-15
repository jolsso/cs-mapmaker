"""Live collector: UDP datagrams from the tracker plugins -> Server-Sent Events for the dashboard.

Every running simulation server (mf_live_host = this container) sends positions, kills, plants
and round results (format: server/plugins/mapforge_tracker.sma). This process keeps the latest
state per run and streams it to browsers. Standard library only; nothing is written to disk.

  UDP  :27500  in   (docker network mapforge-sim; containers reach it as "mapforge-live")
  HTTP :8090   out  GET /events (text/event-stream, ~4 updates/s), GET /state (JSON)
                   GET/POST/DELETE /api/annotations/<map>: the human's wishes drawn on the map
                   /api/maps: new map projects (brief v2), images, intent (mapforge.brief)
                   GET /api/project[/<map>] · POST /api/project/<map> {state: open|closed}
                   page (maps/<map>/annotations.json, mapforge.annotations); writes only from
                   the dashboard's origin (MAPFORGE_SITE_ORIGINS)

Usage: python -m mapforge.live.collector [--udp 27500] [--http 8090]
Published on 127.0.0.1 only (compose.yaml, service `live`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

STALE_S = 20  # a run not heard from for this long is shown as finished
FORGET_S = 900  # and dropped after this


class State:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.version = 0

    def run(self, run_id: str, map_name: str) -> dict[str, Any]:
        key = f"{map_name}/{run_id}"
        r = self.runs.get(key)
        if r is None:
            r = self.runs[key] = {
                "key": key, "run": run_id, "map": map_name, "round": 0, "t": 0.0, "live": False,
                "score": {"T": 0, "CT": 0}, "players": [], "kills": [], "rounds": [], "plants": [],
                "done": False, "started": time.time(),
            }  # fmt: skip
        r["seen"] = time.time()
        return r

    def handle(self, text: str) -> None:
        f = text.strip().split("|")
        if len(f) < 3:
            return
        kind, run_id, map_name = f[0], f[1], f[2]
        r = self.run(run_id, map_name)
        try:
            if kind == "P" and len(f) >= 8:
                r["round"], r["t"] = int(f[3]), float(f[4])
                r["score"] = {"T": int(f[5]), "CT": int(f[6])}
                r["live"] = f[7] == "1"
                players = []
                for item in (f[8] if len(f) > 8 else "").split(";"):
                    p = item.split(",")
                    if len(p) == 6:
                        players.append({"id": int(p[0]), "team": p[1], "alive": p[2] == "1",
                                        "x": float(p[3]), "y": float(p[4]), "yaw": float(p[5])})  # fmt: skip
                r["players"] = players
            elif kind == "K" and len(f) >= 10:
                r["kills"] = (r["kills"] + [{"round": int(f[3]), "t": float(f[4]), "killer": f[5],
                                             "victim": f[6], "x": float(f[7]), "y": float(f[8]),
                                             "weapon": f[9]}])[-40:]  # fmt: skip
            elif kind == "B" and len(f) >= 8:
                r["plants"] = (r["plants"] + [{"round": int(f[3]), "site": f[5], "x": float(f[6]),
                                               "y": float(f[7])}])[-20:]  # fmt: skip
            elif kind == "R" and len(f) >= 9:
                r["rounds"] = (r["rounds"] + [{"round": int(f[3]), "winner": f[4], "reason": f[5],
                                               "site": f[6]}])[-100:]  # fmt: skip
                r["score"] = {"T": int(f[7]), "CT": int(f[8])}
            elif kind == "Q":
                r["done"] = True
        except ValueError:
            return
        self.version += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        for key in [k for k, r in self.runs.items() if now - r["seen"] > FORGET_S]:
            del self.runs[key]
        runs = []
        for r in self.runs.values():
            runs.append(
                {**r, "stale": now - r["seen"] > STALE_S, "age_s": round(now - r["seen"], 1)}
            )
        runs.sort(key=lambda r: (r["done"] or r["stale"], r["map"], r["run"]))
        return {"time": now, "runs": runs}


class Udp(asyncio.DatagramProtocol):
    def __init__(self, state: State) -> None:
        self.state = state

    def datagram_received(self, data: bytes, addr: Any) -> None:
        self.state.handle(data.decode("utf-8", "replace"))


HEADERS = "Access-Control-Allow-Origin: *\r\nCache-Control: no-cache\r\n"
# Writes (annotations) only from the local dashboard: a page on another site open in the same
# browser must not be able to put wishes into the loop.
SITE_ORIGINS = set(
    os.environ.get("MAPFORGE_SITE_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(
        ","
    )
)
MAPS_DIR = Path(os.environ.get("MAPFORGE_MAPS_DIR", "maps"))
MAP_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
}


def _respond(writer: asyncio.StreamWriter, code: int, body: Any, origin: str = "*") -> None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    writer.write(
        f"HTTP/1.1 {code} {REASONS.get(code, 'OK')}\r\nContent-Type: application/json; charset=utf-8\r\n"
        f"Access-Control-Allow-Origin: {origin}\r\nVary: Origin\r\nCache-Control: no-cache\r\n"
        f"Content-Length: {len(data)}\r\n\r\n".encode()
        + data
    )


async def annotations_api(
    method: str, path: str, headers: dict[str, str], body: bytes, writer: asyncio.StreamWriter
) -> None:
    """GET /api/annotations/<map> · POST (JSON annotation) · DELETE /api/annotations/<map>/<id>."""
    from mapforge import annotations as ann

    origin = headers.get("origin", "")
    allow = origin if origin in SITE_ORIGINS else "null"
    parts = [p for p in path.split("?")[0].split("/") if p][2:]  # after /api/annotations
    if method == "OPTIONS":
        writer.write(
            f"HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: {allow}\r\nVary: Origin\r\n"
            "Access-Control-Allow-Methods: GET, POST, DELETE\r\nAccess-Control-Allow-Headers: Content-Type\r\n"
            "Content-Length: 0\r\n\r\n".encode()
        )
        return
    if not parts or not MAP_NAME.match(parts[0]) or not (MAPS_DIR / parts[0]).is_dir():
        _respond(writer, 404, {"error": "unknown map"}, allow)
        return
    map_name = parts[0]
    if method == "GET":
        _respond(writer, 200, ann.load(MAPS_DIR, map_name), allow)
        return
    if origin not in SITE_ORIGINS:
        _respond(writer, 403, {"error": "writes only from the local dashboard"}, allow)
        return
    try:
        if method == "POST" and len(parts) == 1:
            if headers.get("content-type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Content-Type must be application/json")
            item = ann.add(MAPS_DIR, map_name, json.loads(body.decode("utf-8")))
            _respond(writer, 201, item, allow)
        elif method == "DELETE" and len(parts) == 2 and parts[1].isdigit():
            ok = ann.remove(MAPS_DIR, map_name, int(parts[1]))
            _respond(writer, 200 if ok else 404, {"deleted": ok}, allow)
        else:
            _respond(writer, 400, {"error": "unsupported"}, allow)
    except (ValueError, json.JSONDecodeError) as exc:
        _respond(writer, 400, {"error": str(exc)}, allow)


def create_map(req: dict[str, Any]) -> dict[str, Any]:
    """A new map project from the dashboard: maps/<name>/brief.json (brief v2, mapforge.brief),
    no layout yet (the Interpreter reads the brief, then a layout is drafted from it)."""
    from mapforge import brief

    return brief.create(MAPS_DIR, req, BRIEF_CANVAS)


def list_briefs() -> list[dict[str, Any]]:
    from mapforge import brief

    out = []
    for f in sorted(MAPS_DIR.glob("*/brief.json")):
        try:
            b = brief.normalize(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        b["has_layout"] = (f.parent / "layout.yaml").is_file()
        b["has_intent"] = (f.parent / "intent.json").is_file()
        out.append(b)
    return out


def map_brief(name: str) -> dict[str, Any]:
    """GET /api/maps/<map>: the brief, its images and the intent (if the Interpreter ran)."""
    from mapforge import brief

    b = brief.load(MAPS_DIR, name)
    if b is None:
        raise ValueError("unknown map")
    intent = MAPS_DIR / name / "intent.json"
    return {"brief": b, "images": brief.images(MAPS_DIR, name),
            "intent": json.loads(intent.read_text(encoding="utf-8")) if intent.is_file() else None}  # fmt: skip


# The drawing area of a brief before any geometry exists: world units (x0, y0, x1, y1).
BRIEF_CANVAS = [-3072, -3072, 3072, 3072]


async def maps_api(
    method: str, path: str, headers: dict[str, str], body: bytes, writer: asyncio.StreamWriter
) -> None:
    """GET /api/maps (briefs) · POST /api/maps {brief v2} · GET /api/maps/<map> (brief, images,
    intent) · POST /api/maps/<map>/images {file, data (base64), tag, license, note} ·
    PUT /api/maps/<map>/intent {intent} (writes: dashboard origin only)."""
    from mapforge import brief

    origin = headers.get("origin", "")
    allow = origin if origin in SITE_ORIGINS else "null"
    parts = [p for p in path.split("?")[0].split("/") if p][2:]  # after /api/maps
    if method == "OPTIONS":
        writer.write(
            f"HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: {allow}\r\nVary: Origin\r\n"
            "Access-Control-Allow-Methods: GET, POST, PUT\r\nAccess-Control-Allow-Headers: Content-Type\r\n"
            "Content-Length: 0\r\n\r\n".encode()
        )
        return
    if parts and not brief.NAME.match(parts[0]):
        _respond(writer, 404, {"error": "unknown map"}, allow)
        return
    try:
        if method == "GET":
            _respond(writer, 200, map_brief(parts[0]) if parts else list_briefs(), allow)
            return
        if origin not in SITE_ORIGINS:
            _respond(writer, 403, {"error": "writes only from the local dashboard"}, allow)
            return
        if headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Content-Type must be application/json")
        req = json.loads(body.decode("utf-8"))
        if method == "POST" and not parts:
            _respond(writer, 201, create_map(req), allow)
        elif method == "POST" and parts[1:] == ["images"]:
            _respond(writer, 201, brief.add_image(MAPS_DIR, parts[0], req), allow)
        elif method == "PUT" and parts[1:] == ["intent"]:
            from mapforge import interpret

            _respond(writer, 200, interpret.save_edit(MAPS_DIR, parts[0], req), allow)
        else:
            raise ValueError("unsupported")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        _respond(writer, 400, {"error": str(exc)}, allow)


async def project_api(
    method: str, path: str, headers: dict[str, str], body: bytes, writer: asyncio.StreamWriter
) -> None:
    """GET /api/project (all maps) or /api/project/<map> · POST /api/project/<map> {state}:
    close ("afslut") or reopen a map (dashboard origin only)."""
    from mapforge import project

    origin = headers.get("origin", "")
    allow = origin if origin in SITE_ORIGINS else "null"
    parts = [p for p in path.split("?")[0].split("/") if p][2:]  # after /api/project
    if method == "OPTIONS":
        writer.write(
            f"HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: {allow}\r\nVary: Origin\r\n"
            "Access-Control-Allow-Methods: GET, POST\r\nAccess-Control-Allow-Headers: Content-Type\r\n"
            "Content-Length: 0\r\n\r\n".encode()
        )
        return
    if method == "GET" and not parts:
        _respond(writer, 200, project.load_all(MAPS_DIR), allow)
        return
    if not parts or not MAP_NAME.match(parts[0]) or not (MAPS_DIR / parts[0]).is_dir():
        _respond(writer, 404, {"error": "unknown map"}, allow)
        return
    if method == "GET":
        _respond(writer, 200, project.load(MAPS_DIR, parts[0]), allow)
        return
    if origin not in SITE_ORIGINS:
        _respond(writer, 403, {"error": "writes only from the local dashboard"}, allow)
        return
    try:
        if method != "POST" or len(parts) != 1:
            raise ValueError("unsupported")
        if headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise ValueError("Content-Type must be application/json")
        req = json.loads(body.decode("utf-8"))
        _respond(writer, 200, project.set_state(MAPS_DIR, parts[0], str(req.get("state"))), allow)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        _respond(writer, 400, {"error": str(exc)}, allow)


async def http(state: State, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = (await reader.readline()).decode("latin-1")
        headers: dict[str, str] = {}
        while True:
            h = await reader.readline()
            if h in (b"\r\n", b"\n", b""):
                break
            k, _, v = h.decode("latin-1").partition(":")
            headers[k.strip().lower()] = v.strip()
        method, path = ([*line.split(" "), "", ""])[:2]
        bare = path.split("?")[0].rstrip("/")
        if path.startswith(("/api/annotations", "/api/project", "/api/maps")):
            cap = 12_000_000 if bare.endswith("/images") else 200_000  # an image: up to 8 MB
            length = min(int(headers.get("content-length", "0") or 0), cap)
            body = await reader.readexactly(length) if length else b""
            api = (annotations_api if path.startswith("/api/annotations")
                   else project_api if path.startswith("/api/project") else maps_api)  # fmt: skip
            await api(method, path, headers, body, writer)
            await writer.drain()
            return
        if path.startswith("/events"):
            writer.write(
                (
                    "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                    + HEADERS
                    + "Connection: keep-alive\r\n\r\n"
                ).encode()
            )
            last = -1
            while True:
                if state.version != last or int(time.time()) % 5 == 0:
                    last = state.version
                    writer.write(f"data: {json.dumps(state.snapshot())}\n\n".encode())
                    await writer.drain()
                await asyncio.sleep(0.25)
        if path.startswith("/state"):
            body, ctype = json.dumps(state.snapshot()).encode(), "application/json"
        else:
            body, ctype = b"MapForge live: /events, /state, /api/annotations/<map>\n", "text/plain"
        writer.write(
            f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\n{HEADERS}Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, ValueError):
        pass
    finally:
        writer.close()


async def main_async(udp_port: int, http_port: int) -> None:
    state = State()
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: Udp(state), local_addr=("0.0.0.0", udp_port))
    server = await asyncio.start_server(lambda r, w: http(state, r, w), "0.0.0.0", http_port)
    print(f"live collector: udp {udp_port} -> http {http_port} (/events, /state)", flush=True)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--udp", type=int, default=27500)
    parser.add_argument("--http", type=int, default=8090)
    args = parser.parse_args()
    asyncio.run(main_async(args.udp, args.http))


if __name__ == "__main__":
    main()
