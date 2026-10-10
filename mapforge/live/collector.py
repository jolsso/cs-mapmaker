"""Live collector: UDP datagrams from the tracker plugins -> Server-Sent Events for the dashboard.

Every running simulation server (mf_live_host = this container) sends positions, kills, plants
and round results (format: server/plugins/mapforge_tracker.sma). This process keeps the latest
state per run and streams it to browsers. Standard library only; nothing is written to disk.

  UDP  :27500  in   (docker network mapforge-sim; containers reach it as "mapforge-live")
  HTTP :8090   out  GET /events (text/event-stream, ~4 updates/s), GET /state (JSON)

Usage: python -m mapforge.live.collector [--udp 27500] [--http 8090]
Published on 127.0.0.1 only (compose.yaml, service `live`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
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


async def http(state: State, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = (await reader.readline()).decode("latin-1")
        while (await reader.readline()) not in (b"\r\n", b"\n", b""):
            pass
        path = line.split(" ")[1] if " " in line else "/"
        if path.startswith("/events"):
            writer.write(("HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n" + HEADERS
                          + "Connection: keep-alive\r\n\r\n").encode())  # fmt: skip
            last = -1
            while True:
                if state.version != last or int(time.time()) % 5 == 0:
                    last = state.version
                    writer.write(f"data: {json.dumps(state.snapshot())}\n\n".encode())
                    await writer.drain()
                await asyncio.sleep(0.25)
        body = (
            json.dumps(state.snapshot()).encode()
            if path.startswith("/state")
            else b"MapForge live collector: /events, /state\n"
        )
        ctype = "application/json" if path.startswith("/state") else "text/plain"
        writer.write(
            f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\n{HEADERS}Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
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
