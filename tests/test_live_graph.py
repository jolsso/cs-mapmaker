"""Live API for the graph editor: graph.json, a layout as a graph, change wishes, skip."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from mapforge import annotations, skip
from mapforge.live import collector

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:8080"


class Writer:
    def __init__(self) -> None:
        self.data = b""

    def write(self, b: bytes) -> None:
        self.data += b

    def response(self) -> tuple[int, dict]:
        head, _, body = self.data.partition(b"\r\n\r\n")
        return int(head.split()[1]), (json.loads(body) if body else {})


def call(api, method: str, path: str, body=None, origin: str = ORIGIN) -> tuple[int, dict]:
    w = Writer()
    headers = {"origin": origin, "content-type": "application/json"}
    raw = json.dumps(body).encode() if body is not None else b""
    asyncio.run(api(method, path, headers, raw, w))
    return w.response()


@pytest.fixture
def maps(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "MAPS_DIR", tmp_path / "maps")
    monkeypatch.setattr(collector, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(collector, "SITE_ORIGINS", {ORIGIN})
    (tmp_path / "maps" / "de_test01").mkdir(parents=True)
    return tmp_path


def graph() -> dict:
    n = lambda i, r, p: {"id": i, "role": r, "pos": p}  # noqa: E731
    return {"nodes": [n("t", "T", [0, -2000]), n("ct", "CT", [0, 2000]), n("a", "A", [1500, 0]),
                      n("b", "B", [-1500, 0])],
            "edges": [{"a": "t", "b": "a"}, {"a": "t", "b": "b"}, {"a": "ct", "b": "a"},
                      {"a": "ct", "b": "b"}]}  # fmt: skip


def test_graph_put_get_roundtrip(maps):
    code, saved = call(collector.maps_api, "PUT", "/api/maps/de_test01/graph",
                       {"graph": graph(), "approve": True})  # fmt: skip
    assert code == 200 and saved["status"] == "approved" and saved["map"] == "de_test01"
    code, got = call(collector.maps_api, "GET", "/api/maps/de_test01/graph")
    assert code == 200 and got == saved
    assert call(collector.maps_api, "GET", "/api/maps/de_none01/graph")[0] == 404


def test_graph_put_rejects_invalid_with_400_and_writes_nothing(maps):
    bad = graph()
    bad["nodes"] = bad["nodes"][1:]  # no T spawn
    code, body = call(collector.maps_api, "PUT", "/api/maps/de_test01/graph", {"graph": bad})
    assert code == 400 and "T" in body["error"]
    assert not (maps / "maps" / "de_test01" / "graph.json").exists()


def test_topology_endpoint_folds_layout(maps):
    shutil.copytree(ROOT / "maps" / "de_forge01", maps / "maps" / "de_forge01",
                    ignore=shutil.ignore_patterns("src"))  # fmt: skip
    code, body = call(collector.maps_api, "GET", "/api/maps/de_forge01/topology")
    assert code == 200 and body["frozen"] is True
    roles = {n["role"] for n in body["graph"]["nodes"]}
    assert {"T", "CT", "A", "B"} <= roles


def test_changes_creates_graph_wish(maps, monkeypatch):
    # a map without its own locked_maps entry falls back to the locked block (frozen)
    monkeypatch.setattr(collector, "map_frozen", lambda name: False)
    before = graph()
    after = graph()
    after["edges"].append({"a": "a", "b": "b"})
    code, wish = call(collector.maps_api, "POST", "/api/maps/de_test01/changes",
                      {"before": before, "after": after})  # fmt: skip
    assert code == 201 and wish["kind"] == "graph" and wish["status"] == "open"
    assert wish["ops"][0]["type"] == "add_corridor"
    assert annotations.load(maps / "maps", "de_test01")[0]["id"] == wish["id"]


def test_skip_writes_flag_and_409_when_stopped(maps):
    loop = maps / "runs" / "de_test01" / "loop.json"
    loop.parent.mkdir(parents=True)
    loop.write_text(json.dumps({"status": "running", "step": "sim", "iteration": "003"}))
    code, body = call(
        collector.loop_api, "POST", "/api/loop/de_test01/skip", {"reason": "my change"}
    )
    assert code == 202 and body["requested"] and body["loop"]["step"] == "sim"
    assert skip.pending(maps / "maps", "de_test01")["reason"] == "my change"
    code, body = call(collector.loop_api, "GET", "/api/loop/de_test01")
    assert code == 200 and body["skip"]["reason"] == "my change"
    loop.write_text(json.dumps({"status": "stopped", "step": "done", "iteration": "003"}))
    assert call(collector.loop_api, "POST", "/api/loop/de_test01/skip", {})[0] == 409


def test_writes_refused_from_foreign_origin(maps):
    code, _ = call(collector.maps_api, "PUT", "/api/maps/de_test01/graph", {"graph": graph()},
                   origin="http://evil.example")  # fmt: skip
    assert code == 403
    assert (
        call(collector.loop_api, "POST", "/api/loop/de_test01/skip", {}, origin="http://x")[0]
        == 403
    )


def test_changes_on_a_frozen_map_wait_for_the_human(maps, monkeypatch):
    monkeypatch.setattr(collector, "map_frozen", lambda name: True)
    after = graph()
    after["edges"].append({"a": "a", "b": "b"})
    code, wish = call(collector.maps_api, "POST", "/api/maps/de_test01/changes",
                      {"before": graph(), "after": after})  # fmt: skip
    assert code == 201 and wish["status"] == "needs_human" and "locked" in wish["resolution"]


def test_graph_put_on_an_unknown_map_is_404(maps):
    code, _ = call(collector.maps_api, "PUT", "/api/maps/de_ghost01/graph", {"graph": graph()})
    assert code == 404 and not (maps / "maps" / "de_ghost01").exists()
