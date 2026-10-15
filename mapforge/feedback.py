"""In-game feedback: a human walks the map on a feedback server and leaves notes where they look.

  --start (default)  start a HLDS server with the current build of the map, the feedback plugin
                     (server/plugins/mapforge_feedback.sma), no bots, sv_cheats 1 (noclip) and
                     no round limit; join with `connect localhost:27015`
  --collect          copy the notes out of the running server into the map's wishes
                     (maps/<map>/annotations.json: a point at the aimed spot, source "ingame")
                     with an image from our renderer of exactly what the player looked at
                     (build/<map>/feedback/<id>.png)
  --stop             collect, then remove the server

The notes arrive as wishes like the ones drawn on the dashboard, so Decide handles them the same
way (layout changes are still subject to the locked decisions).

Usage: python -m mapforge.feedback --map de_forge01 [--start|--collect|--stop]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mapforge.config import Config, load_config

CSTRIKE = "/home/hlds/hlds/cstrike"
PORT = 27015
CVARS = {  # a calm server to walk around on
    "mp_freezetime": 0, "mp_roundtime": 9, "mp_timelimit": 0, "mp_buytime": 9,
    "mp_startmoney": 16000, "mp_autoteambalance": 0, "mp_limitteams": 0, "sv_cheats": 1,
    "mp_friendlyfire": 0, "mf_max_rounds": 0, "sys_timescale": 1, "sv_alltalk": 1,
    "mf_feedback_nobots": 1,  # the plugin kicks any bot that still joins
}  # fmt: skip
# No bots: quota 0 and none of YaPB's own graph analysis on a map without a graph (it added
# bots on the first feedback server, 2026-10-15).
YAPB = 'yb_quota 0\nyb_quota_mode normal\nyb_graph_analyze_auto_start 0\nyb_graph_url ""\n'


def container_name(map_name: str) -> str:
    return f"mapforge-feedback-{map_name}"


def _client():
    import docker

    return docker.from_env()


def start(cfg: Config, map_name: str, log=print) -> str:
    from mapforge.simulate.image import ensure_image
    from mapforge.simulate.server import _tar

    bsp = cfg.path("build_dir") / map_name / f"{map_name}.bsp"
    if not bsp.is_file():
        raise RuntimeError(f"no {bsp}: compile the map first (./mf compile MAP={map_name})")
    client = _client()
    tag = ensure_image(cfg, client, log)
    name = container_name(map_name)
    for old in client.containers.list(all=True, filters={"name": f"^{name}$"}):
        old.remove(force=True)
    cfg_text = "// mapforge.feedback: a server to walk around on\n" + "".join(
        f"{k} {v}\n" for k, v in CVARS.items()
    )
    files = {
        "mapforge.cfg": cfg_text.encode(),
        "addons/yapb/conf/mapforge_yapb.cfg": YAPB.encode(),
        f"maps/{map_name}.bsp": bsp.read_bytes(),
    }
    sim = cfg.data["simulate"]
    container = client.containers.create(
        tag, name=name, detach=True,
        environment={"MF_MAP": map_name, "MF_RUN_ID": "feedback", "MF_MAXPLAYERS": "8",
                     "MF_TICRATE": "100", "MF_DEMO": "0"},
        ports={f"{PORT}/udp": (sim["bind"], PORT)},
    )  # fmt: skip
    container.put_archive(CSTRIKE, _tar(files))
    container.start()
    return name


def notes_from(path: Path) -> list[dict[str, Any]]:
    """The plugin's JSON lines (a broken line is skipped)."""
    out = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def merge(cfg: Config, map_name: str, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add notes that are not wishes yet; -> the new wishes. A note is identified by its time
    and text, so collecting twice adds nothing."""
    from mapforge import annotations

    maps_dir = cfg.path("maps_dir")
    items = annotations.load(maps_dir, map_name)
    seen = {a.get("ingame", {}).get("key") for a in items}
    new = []
    for n in notes:
        key = f"{n.get('time')}|{n.get('text')}"
        if key in seen or not n.get("text"):
            continue
        cat = f"[{n['category']}] " if n.get("category") else ""
        item = annotations.add(maps_dir, map_name, {
            "kind": "point", "text": f"{cat}{n['text']} (in game)",
            "points": [[n["aim"][0], n["aim"][1]]],
        })  # fmt: skip
        item["ingame"] = {"key": key, "eye": n["eye"], "aim": n["aim"], "player": n.get("player"),
                          "time": n.get("time"), "category": n.get("category") or None}  # fmt: skip
        new.append(item)
        seen.add(key)
    if new:
        items = annotations.load(maps_dir, map_name)
        by_id = {a["id"]: a for a in new}
        annotations.save(maps_dir, map_name, [by_id.get(a["id"], a) for a in items])
    return new


def render_views(
    cfg: Config, map_name: str, wishes: list[dict[str, Any]], suffix: str = ""
) -> list[Path]:
    """An image per wish from our renderer: the player's eye, looking at the aimed spot
    (<id>.png when the note is collected = "then"; suffix "_now" for a later check)."""
    import numpy as np
    from PIL import Image

    from mapforge.bsp.reader import read_bsp
    from mapforge.render.gl import Renderer, look_at
    from mapforge.render.mesh import build_mesh
    from mapforge.render.run import _dirs
    from mapforge.render.textures import WadIndex, wad_search_paths

    if not wishes:
        return []
    bsp_path = cfg.path("build_dir") / map_name / f"{map_name}.bsp"
    bsp = read_bsp(bsp_path)
    renderer = Renderer(
        bsp, build_mesh(bsp), WadIndex(wad_search_paths(bsp_path, _dirs(cfg, "wad_dirs")))
    )
    w, h = cfg.data["render"].get("camera_size", [1280, 720])
    out_dir = cfg.path("build_dir") / map_name / "feedback"
    out = []
    for wsh in wishes:
        g = wsh["ingame"]
        eye, aim = np.array(g["eye"], dtype=float), np.array(g["aim"], dtype=float)
        if np.linalg.norm(aim - eye) < 1:
            continue
        img = renderer.render(look_at(eye, aim, 70, w, h), background=(0.55, 0.62, 0.72))
        out_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img).save(out_dir / f"{wsh['id']}{suffix}.png")
        out.append(out_dir / f"{wsh['id']}{suffix}.png")
    return out


VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "resolved": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["resolved", "reason"],
}

VERIFY_PROMPT = """A player walked a Counter-Strike 1.6 map and left this note while looking at the spot in the image: "{text}"

The image has two halves from exactly the player's eye and line of sight: LEFT = the map when the note was written, RIGHT = the map now (our own renderer: decals, models, sprites and the sky are not drawn; the sky is a flat colour). Judge only the RIGHT half against the note:
- a complaint or a wish: resolved = true only if the RIGHT half clearly no longer has the problem (or now has what was wished for);
- praise ("nice", "better"): resolved = true if the RIGHT half still has what was praised.
Give a short reason (one sentence, English) that names what you see in the RIGHT half. Answer only with JSON."""


VERIFY_PROMPT_NOW = """A player walked a Counter-Strike 1.6 map and left this note while looking at the spot in the image: "{text}"

The image shows the map NOW from exactly the player's eye and line of sight (our own renderer: decals, models, sprites and the sky are not drawn; the sky is a flat colour). Has the note been dealt with?
- a complaint or a wish: resolved = true only if the image clearly does not have the problem (or has what was wished for);
- praise ("nice", "better"): resolved = true if the image still has what was praised.
Give a short reason (one sentence, English) that names what you see. Answer only with JSON."""


def pair(then: Path, now: Path, out: Path) -> Path:
    """'then | now' side by side (each 640x360), labelled."""
    from PIL import Image, ImageDraw

    w, h = 640, 360
    sheet = Image.new("RGB", (2 * w + 8, h + 22), (18, 18, 18))
    for k, (p, label) in enumerate(((then, "THEN (note written)"), (now, "NOW"))):
        sheet.paste(Image.open(p).convert("RGB").resize((w, h)), (k * (w + 8), 22))
        ImageDraw.Draw(sheet).text((k * (w + 8) + 6, 5), label, fill=(255, 255, 255))
    sheet.save(out)
    return out


def verify(cfg: Config, map_name: str, ids: list[int] | None = None, log=print) -> list[dict]:
    """Re-render every in-game note's view on the current build and ask the local vision model
    whether the note is resolved (then | now side by side). Unresolved notes are reopened with
    the model's reason; resolved ones are marked verified. -> the verdicts (also verify.json)."""
    import base64

    from mapforge import annotations
    from mapforge.style.local import _post

    maps_dir = cfg.path("maps_dir")
    items = annotations.load(maps_dir, map_name)
    todo = [a for a in items if a.get("ingame") and (ids is None or a["id"] in ids)]
    fb = cfg.path("build_dir") / map_name / "feedback"
    fb.mkdir(parents=True, exist_ok=True)
    render_views(cfg, map_name, todo, "_now")
    lc = cfg.data["style"]["local"]
    verdicts = []
    for a in todo:
        then, now = fb / f"{a['id']}.png", fb / f"{a['id']}_now.png"
        if not now.is_file():
            continue
        # without the 'then' image (lost, or never rendered) the model judges 'now' alone
        img = pair(then, now, fb / f"{a['id']}_pair.png") if then.is_file() else now
        prompt = VERIFY_PROMPT if then.is_file() else VERIFY_PROMPT_NOW
        text = a["text"].removesuffix(" (in game)")
        body = {
            "model": lc["model"], "temperature": lc.get("temperature", 0.2),
            "max_tokens": lc.get("max_tokens", 8000),
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "verdict", "schema": VERIFY_SCHEMA}},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt.format(text=text)},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode()}},
            ]}],
        }  # fmt: skip
        try:
            resp = _post(
                lc["url"].rstrip("/") + "/chat/completions", body, lc.get("timeout_s", 600)
            )
            got = json.loads(resp["choices"][0]["message"].get("content") or "{}")
            ok, why = bool(got["resolved"]), str(got["reason"])
        except (OSError, ValueError, KeyError) as exc:
            ok, why = None, f"could not check: {exc}"
        verdicts.append({"id": a["id"], "text": text, "resolved": ok, "reason": why})
        log(f"  #{a['id']} {'OK ' if ok else '?? ' if ok is None else 'NO '} {text[:60]} - {why}")
    stamp = __import__("time").strftime("%Y-%m-%d %H:%M")
    by_id = {v["id"]: v for v in verdicts}
    for a in items:  # write the verdicts onto the wishes
        v = by_id.get(a["id"])
        if v is None or v["resolved"] is None:
            continue
        a["ingame"]["verified"] = {"time": stamp, "resolved": v["resolved"], "reason": v["reason"]}
        if not v["resolved"] and a.get("status") == "done":
            a["status"] = "open"  # the fix did not hold: back on the list
    annotations.save(maps_dir, map_name, items)
    (fb / "verify.json").write_text(
        json.dumps(verdicts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return verdicts


def collect(cfg: Config, map_name: str) -> list[dict[str, Any]]:
    from mapforge.simulate.server import _fetch

    client = _client()
    found = client.containers.list(all=True, filters={"name": f"^{container_name(map_name)}$"})
    if not found:
        raise RuntimeError(f"no feedback server for {map_name} (start one with --start)")
    dest = cfg.path("build_dir") / map_name / "feedback"
    _fetch(found[0], f"{CSTRIKE}/logs/mapforge/feedback_{map_name}.jsonl", dest)
    new = merge(cfg, map_name, notes_from(dest / f"feedback_{map_name}.jsonl"))
    render_views(cfg, map_name, new)
    return new


def stop(cfg: Config, map_name: str) -> list[dict[str, Any]]:
    new = collect(cfg, map_name)
    for c in _client().containers.list(all=True, filters={"name": f"^{container_name(map_name)}$"}):
        c.remove(force=True)
    return new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--map", required=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--start", action="store_true")
    g.add_argument("--collect", action="store_true")
    g.add_argument("--stop", action="store_true")
    g.add_argument("--verify", nargs="*", type=int, metavar="ID",
                   help="re-render the notes' views and let the local vision model check them")  # fmt: skip
    args = ap.parse_args(argv)
    cfg = load_config()
    try:
        if args.verify is not None:
            got = verify(cfg, args.map, args.verify or None)
            done = sum(1 for v in got if v["resolved"])
            print(f"feedback {args.map}: {done} of {len(got)} note(s) resolved")
            return 0 if done == len(got) else 3
        if args.collect or args.stop:
            new = (stop if args.stop else collect)(cfg, args.map)
            for w in new:
                print(f"  wish #{w['id']}: {w['text']} at {w['ingame']['aim']}")
            print(f"feedback {args.map}: {len(new)} new note(s)"
                  + (" - server stopped" if args.stop else ""))  # fmt: skip
            return 0
        name = start(cfg, args.map)
        print(f"feedback {args.map}: server {name} is up - in CS 1.6: connect localhost:{PORT}")
        print('  notes: say !fb <text>  |  !fbm (menu)  |  bind f "messagemode mf_fb"')
        return 0
    except RuntimeError as exc:
        print(f"feedback failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
