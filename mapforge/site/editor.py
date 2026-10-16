"""The graph editor page of the local website (editor.html + editor.js/css + refgraphs.json).

Spec: docs/superpowers/specs/2026-10-16-graph-editor-design.md. The page is static; it loads the
reference graphs from refgraphs.json and talks to the live API (graph.json, a map's current
graph, change wishes).
"""

# ruff: noqa: E501  (the page body is an HTML template)
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from mapforge.config import Config

HERE = Path(__file__).parent
ASSET_VERSION = hashlib.sha256(
    (HERE / "editor.js").read_bytes() + (HERE / "editor.css").read_bytes()
).hexdigest()[:8]


def _compact(topo: dict[str, Any]) -> dict[str, Any]:
    """A topology as the editor reads it: [id, role, site, level, [x, y]] nodes, [a, b, kind] edges."""
    return {
        "nodes": [[n["id"], n["role"], n.get("site"), n["level"], n["_c"]] for n in topo["nodes"]],
        "edges": [[e["a"], e["b"], e["kind"]] for e in topo["edges"] if e["kind"] != "window"],
        "choke_edges": [[e["a"], e["b"]] for e in topo["edges"] if e.get("choke")],
    }


def refgraphs(cfg: Config, own_maps: list[str]) -> dict[str, Any]:
    """Reference maps (`./mf refgraphs`, tier A/B) for similarity and templates; own maps with a
    layout as templates only (key "own:<map>")."""
    from mapforge.topology import extract

    out: dict[str, Any] = {}
    for f in sorted((cfg.path("build_dir") / "topologies" / "refmap").glob("*.json")):
        topo = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = {"tier": topo.get("tier", "B"), **_compact(topo)}
    for m in own_maps:
        src = cfg.path("maps_dir") / m / "layout.yaml"
        if not src.is_file():
            continue
        try:
            topo = extract(yaml.safe_load(src.read_text(encoding="utf-8")))
        except Exception:  # the site is a view; one broken layout must not hide the others
            continue
        out[f"own:{m}"] = {"tier": "own", **_compact(topo)}
    return out


def editor_body() -> str:
    kinds = (("corridor", "corridor"), ("choke", "door / chokepoint"), ("drop", "drop (one-way)"),
             ("ladder", "ladder / stairs"))  # fmt: skip
    return f"""
<link rel='stylesheet' href='editor.css?v={ASSET_VERSION}'>
<div class='ed'>
<div class='ed-head'><h1>Graph editor</h1><span>Place spawns and sites, add rooms, connect them. The board is 6144 × 6144 units (one grid square = 256 u ≈ 1 s at 250 u/s).</span>
  <div class='mode' id='ed-modebar'></div></div>
<div id='ed-banner'></div>
<p class='hint' style='margin:6px 16px 0'><span id='ed-status' class='saved'></span></p>
<div class='ed-main'>
<div class='tools'>
  <div class='lbl'>Start from</div>
  <select id='tpl'><option value=''>empty board</option></select>
  <label class='hint'><input type='checkbox' id='simple' checked> simplified (skeleton)</label>
  <div class='lbl'>Place</div>
  <button data-tool='select'>Select (inspect)</button>
  <button data-tool='T' style='border-left:6px solid var(--t)'>T spawn</button>
  <button data-tool='CT' style='border-left:6px solid var(--ct)'>CT spawn</button>
  <button data-tool='A' style='border-left:6px solid var(--a)'>Site A</button>
  <button data-tool='B' style='border-left:6px solid var(--b)'>Site B</button>
  <button data-tool='room'>Room</button>
  <div class='lbl'>Edit</div>
  <button data-tool='connect'>Connect</button>
  <button data-tool='move'>Move</button>
  <button data-tool='delete'>Delete</button>
  <div class='lbl'>Connection type</div>
  <select id='kind'>{"".join(f"<option value='{v}'>{t}</option>" for v, t in kinds)}</select>
  <div class='lbl'>Level for new rooms</div>
  <select id='level'><option value='1'>upper (+1)</option><option value='0' selected>ground (0)</option><option value='-1'>below (−1)</option></select>
  <div class='lbl'>Graph</div>
  <button id='ed-undo'>Undo</button>
  <button id='ed-clear'>Clear</button>
  <button id='ed-export'>Download JSON</button>
  <p class='hint'>Double-click a node to rename it. Drag any node to move it (except in Connect/Delete). Connect: click a node, then another; a drop goes from the first to the second. Corridor length = straight distance × 1.3.</p>
</div>
<div class='board'><svg id='ed-svg' viewBox='0 0 640 640' role='img' aria-label='The map as a graph'></svg><div id='scale' class='hint' style='position:absolute;left:10px;bottom:8px'></div></div>
<div class='side'>
  <div class='card'><h3>Inspector</h3><div id='insp'></div></div>
  <div class='card'><h3>Live check</h3><div id='checks'></div></div>
  <div class='card'><h3>Closest reference maps</h3><div id='refs'></div><svg class='mini' id='mini' viewBox='0 0 300 150'></svg></div>
  <div class='card'><h3>Suggestions</h3><div id='sugs'></div></div>
</div>
</div>
</div>
<script src='editor.js?v={ASSET_VERSION}'></script>"""
