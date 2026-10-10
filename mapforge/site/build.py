"""Local website: architecture + roadmap, and one page per map (project) with every phase.

Usage: python -m mapforge.site.build      -> build/site/ (open index.html or `docker compose up site`)
Built from the repo's own data (docs/, build/<map>/, runs/<map>/); images are copied in, so the
site is self-contained. It is rebuilt automatically at the end of validate/render/review/decide.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from mapforge.config import Config, load_config
from mapforge.history import versions
from mapforge.runs import iterations, stage_of

PHASES = [  # (key, label, built?)
    ("compile", "2 Compile", True), ("validate", "3 Validate", True),
    ("render", "4 Render", True), ("review", "5 Review", True),
    ("simulate", "6 Simulate", True), ("analyze", "7 Analyze", False),
    ("decide", "8 Decide", True),
]  # fmt: skip
SKIP_BUILD_DIRS = {"refmaps", "site", "no-hl-install"}

e = html.escape


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _md(text: str) -> str:
    """Tiny Markdown subset for NOTES.md: headings, bullets, bold, code."""
    out, in_list = [], False
    for raw in text.splitlines():
        line = e(raw)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
        if m := re.match(r"(#{1,3}) (.*)", line):
            out.append(("</ul>" if in_list else "") + f"<h3>{m.group(2)}</h3>")
            in_list = False
        elif re.match(r"\s*[-*] ", line):
            item = re.sub(r"^\s*[-*] ", "", line)
            out.append(("" if in_list else "<ul>") + f"<li>{item}</li>")
            in_list = True
        elif line.strip():
            out.append(("</ul>" if in_list else "") + f"<p>{line}</p>")
            in_list = False
    return "".join(out) + ("</ul>" if in_list else "")


def _page(title: str, body: str, depth: int, active: str, maps: list[str]) -> str:
    up = "../" * depth
    links = [f"<a href='{up}index.html' class='{'on' if active == 'home' else ''}'>Projekter</a>",
             f"<a href='{up}architecture.html' class='{'on' if active == 'arch' else ''}'>"
             "Arkitektur &amp; roadmap</a>"]  # fmt: skip
    if active not in ("home", "arch"):
        links.append(f"<span class='muted'>›</span> <a class='on'>{e(active)}</a>")
    return (
        f"<!doctype html><html lang='da'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{e(title)}</title><link rel='stylesheet' href='{up}style.css'></head><body>"
        f"<div class='wrap'><nav><span class='brand'>MapForge</span>{''.join(links)}</nav>"
        f"{body}<p class='muted'>Genereret {time.strftime('%Y-%m-%d %H:%M')} af "
        f"<code>mapforge.site.build</code> fra repoets data.</p></div></body></html>"
    )


def _chip(state: bool | None, yes: str = "ok", no: str = "fejl", none: str = "–") -> str:
    if state is True:
        return f"<span class='chip ok'>{yes}</span>"
    if state is False:
        return f"<span class='chip bad'>{no}</span>"
    return f"<span class='chip todo'>{none}</span>"


def discover_maps(cfg: Config) -> list[str]:
    names = set()
    build = cfg.path("build_dir")
    if build.is_dir():
        for d in build.iterdir():
            if (
                d.is_dir()
                and d.name not in SKIP_BUILD_DIRS
                and ((d / "validation.json").is_file() or (d / "renders" / "index.json").is_file())
            ):
                names.add(d.name)
    for root in (cfg.path("maps_dir"), cfg.root / cfg.data["paths"].get("runs_dir", "runs")):
        if root.is_dir():
            names |= {d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")}
    return sorted(names)


def map_status(cfg: Config, name: str) -> dict[str, Any]:
    b = cfg.path("build_dir") / name
    validation, review = _load(b / "validation.json"), _load(b / "review.json")
    index, compile_ = _load(b / "renders" / "index.json"), _load(b / "compile.json")
    sim = _load(b / "simulation.json")
    stage = stage_of(b) if b.is_dir() else {}
    return {
        "compile": None if compile_ is None else compile_.get("ok"),
        "validate": None if validation is None else validation.get("ok"),
        "render": None if index is None else True,
        "review": None if stage.get("review_passed") is None else stage["review_passed"],
        "review_stale": review is not None and stage.get("review_passed") is None,
        "simulate": None if sim is None else sim.get("ok"), "analyze": None,
        "decide": True if iterations(cfg, name) else None,
        "source": None if validation is None else validation.get("source"),
        "next": stage.get("next"), "why": stage.get("why"),
        "thumb": "topdown.png" if index else None,
    }  # fmt: skip


def simulate_section(b: Path) -> str:
    """Simulation summary (build/<map>/simulation.json): rounds, win rate, plants, demos."""
    sim = _load(b / "simulation.json")
    parts = ["<section id='simulate'><h2>6 Simulate</h2>"]
    if not sim:
        parts.append(
            "<p class='muted'>Ikke simuleret endnu (<code>./mf simulate MAP=…</code>).</p></section>"
        )
        return "".join(parts)
    smoke = sim.get("smoke") or {}
    parts.append(f"<p>{_chip(sim.get('ok'), 'OK', 'fejlet')} <span class='muted'>{e(str(sim.get('stop_reason')))}"
                 f" · {sim.get('wall_s')} s · {sim.get('servers')} server(e) · timescale {sim.get('timescale')}"
                 f" · {sim.get('bots_per_team')} mod {sim.get('bots_per_team')} bots</span></p>")  # fmt: skip
    if smoke:
        checks = smoke.get("checks", {})
        sites = checks.get("sites_reached", {}).get("samples_per_site", {})
        parts.append(f"<p>Smoke: {_chip(smoke.get('ok'), 'OK', 'fejlet')} "
                     f"<span class='muted'>gyldige runder {checks.get('valid_rounds', {}).get('value')}"
                     f" · bots i bevægelse {checks.get('bots_move', {}).get('value')}/{checks.get('bots_move', {}).get('of')}"
                     f" · samples pr. site {e(json.dumps(sites))}</span></p>")  # fmt: skip
    summ = sim.get("summary") or {}
    if summ:
        rows = []
        for key, label in (("t_winrate", "T-winrate"), ("site_split_a", "andel plants på A")):
            m = summ.get(key, {})
            rows.append(f"<tr><td>{label}</td><td>{m.get('value')}</td><td>{m.get('ci')}</td>"
                        f"<td>{m.get('target')}</td><td>{m.get('n')}</td><td>{e(str(m.get('relation')))}</td></tr>")  # fmt: skip
        parts.append(f"<p class='muted'>{summ.get('rounds')} gyldige runder af {summ.get('rounds_logged')} logget"
                     f" · {summ.get('plants')} plants · schema-fejl {summ.get('schema_errors')}</p>"
                     "<table><tr><th>metrik</th><th>værdi</th><th>95 %-interval</th><th>mål</th><th>n</th>"
                     "<th>ift. mål</th></tr>" + "".join(rows) + "</table>")  # fmt: skip
    demos = sim.get("demos") or []
    if demos:
        parts.append(f"<p class='muted'>Demoer ({len(demos)}): kopiér til <code>cstrike/</code> og afspil med "
                     f"<code>playdemo &lt;navn&gt;</code> – {e(', '.join(Path(d).name for d in demos))}</p>")  # fmt: skip
    parts.append("</section>")
    return "".join(parts)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dst)


def _findings_table(findings: list[dict], cols: tuple[str, ...]) -> str:
    if not findings:
        return "<p class='muted'>Ingen fund.</p>"
    head = "".join(f"<th>{c}</th>" for c in cols)
    rows = []
    for f in findings:
        sev = f.get("severity", "")
        cells = [f"<td class='sev-{e(sev)}'>{e(sev)}</td>"]
        for c in cols[1:]:
            v = f.get(c, "")
            cells.append(f"<td>{e(json.dumps(v) if isinstance(v, (list, dict)) else str(v))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<div class='table'><table><tr>{head}</tr>{''.join(rows)}</table></div>"


def map_page(cfg: Config, name: str, out: Path) -> str:
    b = cfg.path("build_dir") / name
    st = map_status(cfg, name)
    parts = [f"<section><span class='eyebrow'>Projekt</span><h1>{e(name)}</h1>"]
    src = {"reference": "referencemap (kun .bsp, ikke vores)", "map": "vores eget map"}.get(
        st["source"] or "", "ikke valideret endnu"
    )
    nxt = f"Næste trin: <b>{e(st['next'] or '-')}</b> – {e(st['why'] or '')}"
    parts.append(f"<p class='muted'>{e(src)} · {nxt}</p><div class='phases'>")
    for key, label, built in PHASES:
        state = st.get(key)
        cls = "todo" if not built else ("ok" if state else "bad" if state is False else "todo")
        parts.append(f"<a href='#{key}' class='chip {cls}'>{label}</a>")
    parts.append("</div></section>")

    compile_ = _load(b / "compile.json")
    parts.append("<section id='compile'><h2>2 Compile</h2>")
    if compile_:
        parts.append(f"<p>{_chip(compile_.get('ok'))} {e(compile_.get('failure') or 'compile uden fejl')}"
                     f" · {compile_.get('seconds')} s · {e(str(compile_.get('compiler')))}</p>")  # fmt: skip
        if compile_.get("leak"):
            parts.append(f"<pre>{e(json.dumps(compile_['leak'], indent=1)[:2000])}</pre>")
    else:
        parts.append("<p class='muted'>Intet compile (referencemaps compiles ikke af os).</p>")
    parts.append("</section>")

    v = _load(b / "validation.json")
    parts.append("<section id='validate'><h2>3 Validate</h2>")
    if v:
        s = v["summary"]
        parts.append(f"<p>{_chip(v['ok'])} {s.get('errors', 0)} errors · {s.get('warnings', 0)} "
                     f"warnings · {s.get('info', 0)} info</p>")  # fmt: skip
        main = [f for f in v["findings"] if f["severity"] in ("error", "warning")]
        parts.append(_findings_table(main, ("severity", "rule", "message", "location")))
        st_ = v.get("stats", {})
        sites = st_.get("reachability", {}).get("sites", [])
        if sites:
            rows = "".join(f"<tr><td>site {x.get('label', x['site'])}</td><td class='num'>{x['centre']}</td>"
                           f"<td class='num'>{x['spawns_reaching']}</td></tr>" for x in sites)  # fmt: skip
            parts.append("<h3>Nåbarhed</h3><div class='table'><table><tr><th>Site</th><th>Centrum"
                         f"</th><th>Spawns der når det</th></tr>{rows}</table></div>")  # fmt: skip
        timings = st_.get("timings", [])
        if timings:
            rows = "".join(
                f"<tr><td>site {e(str(t['site']))}</td><td class='num'>{t.get('T', {}).get('median_s')} s</td>"
                f"<td class='num'>{t.get('CT', {}).get('median_s')} s</td><td class='num'>{t.get('ct_lead_s')} s</td></tr>"
                for t in timings
            )
            parts.append(
                "<h3>Løbetider (250 units/s)</h3><p class='muted'>Officielle maps: T 14–25 s, CT-forspring typisk 7–13 s (DESIGN_GUIDE.md).</p>"
                f"<div class='table'><table><tr><th>Site</th><th>T</th><th>CT</th><th>CT-forspring</th></tr>{rows}</table></div>"
            )
        limits = sorted(st_.get("limits", []), key=lambda x: -x["pct"])[:6]
        if limits:
            rows = "".join(f"<tr><td>{e(x['name'])}</td><td class='num'>{x['used']}/{x['max']}</td>"
                           f"<td class='num'>{x['pct']:.1f} %</td></tr>" for x in limits)  # fmt: skip
            parts.append("<h3>Højeste limits</h3><div class='table'><table><tr><th>Limit</th>"
                         f"<th>Brugt</th><th>Fyldt</th></tr>{rows}</table></div>")  # fmt: skip
        info = [f for f in v["findings"] if f["severity"] == "info"]
        if info:
            parts.append(f"<details><summary>{len(info)} design-norm-noter (info)</summary>"
                         + _findings_table(info, ("severity", "rule", "message", "location"))
                         + "</details>")  # fmt: skip
    else:
        parts.append("<p class='muted'>Ikke valideret endnu.</p>")
    parts.append("</section>")

    index = _load(b / "renders" / "index.json")
    parts.append("<section id='render'><h2>4 Render</h2>")
    if index:
        bright = index.get("brightness", {})
        parts.append(f"<p class='muted'>{len(index['images'])} billeder på {index.get('seconds')} s · "
                     f"{len(bright.get('dark_zones', []))} mørke zoner (luma &lt; {bright.get('dark_luma')})"
                     f" · manglende teksturer: {e(', '.join(index.get('missing_textures', [])) or 'ingen')}</p>"
                     "<div class='grid'>")  # fmt: skip
        for im in index["images"]:
            _copy(b / "renders" / im["file"], out / "img" / im["file"])
            parts.append(f"<figure><a href='img/{e(im['file'])}' target='_blank'><img src='img/"
                         f"{e(im['file'])}' loading='lazy' alt='{e(im['file'])}'></a><figcaption><b>"
                         f"{e(im['file'])}</b> – {e(im['purpose'])}</figcaption></figure>")  # fmt: skip
        parts.append("</div>")
    else:
        parts.append("<p class='muted'>Ikke renderet endnu.</p>")
    parts.append("</section>")

    r = _load(b / "review.json")
    parts.append("<section id='review'><h2>5 Review</h2>")
    if r:
        stale = " <span class='chip bad'>forældet – billeder/validering ændret siden</span>" if st[
            "review_stale"] else ""  # fmt: skip
        parts.append(f"<p>{_chip(r.get('passed'), 'bestået', 'fejlet')}{stale} "
                     f"<span class='muted'>({e(str(r.get('executor') or r.get('stage')))})</span></p>"
                     f"<div class='card'>{e(r.get('summary', ''))}</div>")  # fmt: skip
        parts.append(_findings_table(r.get("findings", []), ("severity", "where", "what", "image")))
    else:
        parts.append("<p class='muted'>Ikke reviewet endnu.</p>")
    parts.append("</section>")

    parts.append(simulate_section(b))
    parts.append("<section id='analyze'><h2>7 Analyze</h2><p class='muted'>Ikke bygget endnu "
                 "(fase 5).</p></section>")  # fmt: skip

    parts.append("<section id='decide'><h2>8 Decide – iterationer</h2>")
    runs = iterations(cfg, name)
    if not runs:
        parts.append("<p class='muted'>Ingen iterationer endnu.</p>")
    for run in reversed(runs):
        stage, plan, dec = (_load(run / "stage.json") or {}), _load(run / "plan.json"), _load(
            run / "decision.json")  # fmt: skip
        head = f"<h3>Iteration {run.name}</h3><p class='muted'>Stoppede ved: {e(str(stage.get('reached')))}"
        head += f" – {e(str(stage.get('why')))} · næste: {e(str(stage.get('next')))}</p>"
        parts.append(f"<div class='card'>{head}")
        if plan:
            esc = (f"<p><span class='chip bad'>eskaleret</span> {e(plan.get('escalation_reason', ''))}</p>"
                   if plan.get("escalate") else "")  # fmt: skip
            parts.append(f"<p><b>Plan:</b> {e(plan.get('summary', ''))}</p>{esc}")
            if plan.get("changes"):
                rows = "".join(f"<tr><td><code>{e(c.get('type', ''))}</code></td><td>"
                               f"{e(json.dumps(c.get('params', {}), ensure_ascii=False))}</td><td>"
                               f"{e(c.get('rationale', ''))}</td></tr>" for c in plan["changes"])  # fmt: skip
                parts.append("<div class='table'><table><tr><th>Ændring</th><th>Params</th><th>"
                             f"Hvorfor</th></tr>{rows}</table></div>")  # fmt: skip
        if dec:
            parts.append(f"<p>Politik-tjek: {_chip(dec.get('ok'), 'accepteret', 'afvist')} "
                         f"{len(dec.get('accepted', []))} accepteret, {len(dec.get('rejected', []))} "
                         f"afvist · anvendt: {'ja' if dec.get('applied') else 'nej (tørkørsel)'}</p>")  # fmt: skip
        if (run / "NOTES.md").is_file():
            notes = _md((run / "NOTES.md").read_text(encoding="utf-8"))
            parts.append(
                f"<details><summary>NOTES.md</summary><div class='notes'>{notes}</div></details>"
            )
        parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


def _version_chip(meta: dict) -> str:
    if meta.get("review_passed") is True:
        return "<span class='chip ok'>review bestået</span>"
    if meta.get("review_passed") is False:
        return "<span class='chip bad'>review fejlet</span>"
    if meta.get("validate_ok") is False:
        return "<span class='chip bad'>validering fejlet</span>"
    return "<span class='chip todo'>ikke reviewet</span>"


def history_section(cfg: Config, name: str, mdir: Path, maps: list[str]) -> str:
    """Thumbnail list of all versions (newest first) + one page per version."""
    vers = versions(cfg, name)
    if not vers:
        return ""
    cards = []
    for v in reversed(vers):
        meta = _load(v / "meta.json") or {}
        out = mdir / "history" / v.name
        out.mkdir(parents=True, exist_ok=True)
        index = _load(v / "renders" / "index.json") or {"images": []}
        for im in index["images"]:
            if (v / "renders" / im["file"]).is_file():
                _copy(v / "renders" / im["file"], out / "img" / im["file"])
        # version page
        parts = [
            f"<section><span class='eyebrow'>{e(name)} · historik</span><h1>Version {e(v.name)}</h1>"
            f"<p class='muted'>Oprettet {e(meta.get('created', ''))} · opdateret {e(meta.get('updated', ''))}"
            f" · commit <code>{e(str(meta.get('git_commit') or '-'))}</code></p><div class='phases'>"
            f"{_version_chip(meta)}</div></section>"
        ]
        if meta.get("notes"):
            parts.append(
                "<section><h2>Noter</h2><ul>"
                + "".join(f"<li>{e(n)}</li>" for n in meta["notes"])
                + "</ul></section>"
            )
        if meta.get("review_summary"):
            r = _load(v / "review.json") or {}
            parts.append(
                f"<section><h2>Review</h2><div class='card'>{e(meta['review_summary'])}</div>"
                + _findings_table(r.get("findings", []), ("severity", "where", "what", "image"))
                + "</section>"
            )
        vjson = _load(v / "validation.json")
        if vjson:
            main = [f for f in vjson["findings"] if f["severity"] in ("error", "warning")]
            parts.append(
                f"<section><h2>Validering</h2><p>{_chip(vjson['ok'])} {vjson['summary'].get('errors', 0)} errors · "
                f"{vjson['summary'].get('warnings', 0)} warnings</p>"
                + _findings_table(main, ("severity", "rule", "message", "location"))
                + "</section>"
            )
        if meta.get("timings"):
            rows = "".join(
                f"<tr><td>site {e(str(t['site']))}</td><td class='num'>{t.get('T', {}).get('median_s')} s</td>"
                f"<td class='num'>{t.get('CT', {}).get('median_s')} s</td><td class='num'>{t.get('ct_lead_s')} s</td></tr>"
                for t in meta["timings"]
            )
            parts.append(
                "<section><h2>Løbetider</h2><div class='table'><table><tr><th>Site</th><th>T</th><th>CT</th>"
                f"<th>CT-forspring</th></tr>{rows}</table></div></section>"
            )
        if (v / "layout.yaml").is_file():
            parts.append(
                f"<section><h2>Layout</h2><details><summary>layout.yaml</summary><pre>{e((v / 'layout.yaml').read_text(encoding='utf-8'))}</pre></details></section>"
            )
        parts.append("<section><h2>Billeder</h2><div class='grid'>")
        for im in index["images"]:
            parts.append(
                f"<figure><a href='{v.name}/img/{e(im['file'])}' target='_blank'><img src='{v.name}/img/{e(im['file'])}' "
                f"loading='lazy' alt='{e(im['file'])}'></a><figcaption><b>{e(im['file'])}</b> – {e(im['purpose'])}</figcaption></figure>"
            )
        parts.append("</div></section>")
        back = f"<p><a href='../index.html#history'>← tilbage til {e(name)}</a></p>"
        (mdir / "history" / f"{v.name}.html").write_text(
            _page(f"{name} – version {v.name}", back + "".join(parts), 3, name, maps),
            encoding="utf-8",
        )
        thumb = f"history/{v.name}/img/topdown.png"
        t = {x["site"]: x for x in meta.get("timings", [])}
        tim = " · ".join(f"{k}: T {x.get('T', {}).get('median_s')} s" for k, x in t.items())
        cards.append(
            f"<figure><a href='history/{v.name}.html'><img src='{thumb}' loading='lazy' alt='version {v.name}'></a>"
            f"<figcaption><b>Version {e(v.name)}</b> · {e(meta.get('created', ''))}<br>{_version_chip(meta)}"
            f"{'<br>' + e(tim) if tim else ''}</figcaption></figure>"
        )
    return (
        f"<section id='history'><h2>Historik</h2><p class='muted'>{len(vers)} versioner, nyeste først. "
        "En ny version oprettes, når mappet ændrer sig; klik for alle billeder og data.</p>"
        f"<div class='grid'>{''.join(cards)}</div></section>"
    )


def build_site(cfg: Config) -> Path:
    out = cfg.path("build_dir") / "site"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).with_name("style.css"), out / "style.css")
    maps = discover_maps(cfg)

    # Architecture & roadmap: the overview page (it carries its own styles).
    overview = (cfg.root / "docs" / "overview.html").read_text(encoding="utf-8")
    nav = "".join(f"<a href='maps/{m}/index.html'>{e(m)}</a> " for m in maps)
    banner = ("<div style='padding:10px 20px;font:14px system-ui;background:#24272b;color:#e4e2dd'>"
              "<b>MapForge</b> · <a style='color:#f0904a' href='index.html'>Projekter</a> · "
              f"{nav}</div>")  # fmt: skip
    (out / "architecture.html").write_text(
        "<!doctype html><meta charset='utf-8'>" + banner + overview, encoding="utf-8"
    )

    def progress(m: str) -> int:
        st = map_status(cfg, m)
        return sum(1 for k, _, built in PHASES if built and st.get(k))

    def row(m: str) -> str:
        st = map_status(cfg, m)
        chips = "".join(
            f"<span class='chip {'todo' if not built else 'ok' if st[k] else 'bad' if st[k] is False else 'todo'}'"
            f" title='{e(label)}'>{e(label.split()[1])}</span>"
            for k, label, built in PHASES
        )
        thumb = ""
        if st["thumb"]:
            _copy(
                cfg.path("build_dir") / m / "renders" / "topdown.png",
                out / "maps" / m / "img" / "topdown.png",
            )
            thumb = f"<img class='thumb' src='maps/{m}/img/topdown.png' alt=''>"
        return (
            f"<tr><td><a href='maps/{m}/index.html'>{thumb}</a></td><td><a href='maps/{m}/"
            f"index.html'><b>{e(m)}</b></a></td><td><div class='phases'>{chips}</div></td>"
            f"<td>{e(st['next'] or '-')}<br><span class='muted'>{e(st['why'] or '')}</span></td></tr>"
        )

    own = [m for m in maps if map_status(cfg, m)["source"] != "reference"]
    refs = sorted((m for m in maps if m not in own), key=lambda m: (-progress(m), m))
    head = "<tr><th></th><th>Map</th><th>Faser</th><th>Næste trin</th></tr>"
    rows = []
    for title, group, note in (
        ("Egne maps", own, "Maps vi selv bygger (compile fra .map). Generatoren kommer i fase 2."),
        (
            "Referencemaps",
            refs,
            "Officielle og community-maps (kun .bsp), brugt til at teste og kalibrere pipelinen.",
        ),
    ):
        if group:
            rows.append(
                f"<h2>{title}</h2><p class='muted'>{note}</p><div class='table'><table>"
                f"{head}{''.join(row(m) for m in group)}</table></div>"
            )
    home = ("<section><span class='eyebrow'>Oversigt</span><h1>Projekter</h1><p class='muted'>Ét "
            "projekt pr. map. Grøn = fasen er kørt og bestået, rød = kørt og fejlet, stiplet = ikke "
            "kørt eller ikke bygget endnu. <a href='architecture.html'>Arkitektur og roadmap</a>.</p>"
            f"{''.join(rows)}</section>")  # fmt: skip
    (out / "index.html").write_text(_page("MapForge – projekter", home, 0, "home", maps),
                                    encoding="utf-8")  # fmt: skip
    for m in maps:
        mdir = out / "maps" / m
        mdir.mkdir(parents=True, exist_ok=True)
        body = map_page(cfg, m, mdir)
        hist = history_section(cfg, m, mdir, maps)
        if hist:  # right after the project header
            cut = body.index("</section>") + len("</section>")
            body = body[:cut] + hist + body[cut:]
        (mdir / "index.html").write_text(
            _page(f"MapForge – {m}", body, 2, m, maps), encoding="utf-8"
        )
    return out


def refresh_site(cfg: Config | None = None) -> None:
    """Best-effort rebuild, called at the end of pipeline CLIs (never fails the caller)."""
    cfg = cfg or load_config()
    if not cfg.data.get("site", {}).get("auto_refresh", True):
        return
    try:
        build_site(cfg)
    except Exception as exc:  # the site is a view; a bug here must not break the pipeline
        print(f"(site refresh failed: {exc})", file=sys.stderr)


def main() -> int:
    out = build_site(load_config())
    print(f"site: {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
