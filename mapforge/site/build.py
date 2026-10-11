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
from mapforge.site import charts

PHASES = [  # (key, label, built?)
    ("input", "1 Input", True),
    ("compile", "2 Compile", True), ("validate", "3 Validate", True),
    ("render", "4 Render", True), ("review", "5 Review", True),
    ("simulate", "6 Simulate", True), ("analyze", "7 Analyze", True),
    ("decide", "8 Decide", True),
]  # fmt: skip
# cache-buster for the stylesheet: browsers keep style.css otherwise
CSS_VERSION = (
    __import__("hashlib").sha256(Path(__file__).with_name("style.css").read_bytes()).hexdigest()[:8]
)
ANN_VERSION = (
    __import__("hashlib")
    .sha256(Path(__file__).with_name("annotate.js").read_bytes())
    .hexdigest()[:8]
)
NEW_VERSION = (
    __import__("hashlib").sha256(Path(__file__).with_name("newmap.js").read_bytes()).hexdigest()[:8]
)
JS_VERSION = (
    __import__("hashlib").sha256(Path(__file__).with_name("live.js").read_bytes()).hexdigest()[:8]
)
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
             f"<a href='{up}live.html' class='{'on' if active == 'live' else ''}'>● Live</a>",
             f"<a href='{up}architecture.html' class='{'on' if active == 'arch' else ''}'>"
             "Arkitektur &amp; roadmap</a>"]  # fmt: skip
    if active not in ("home", "arch", "live"):
        links.append(f"<span class='crumb'>›</span><a class='on'>{e(active)}</a>")
    return (
        f"<!doctype html><html lang='da'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{e(title)}</title><link rel='stylesheet' href='{up}style.css?v={CSS_VERSION}'>"
        "<link rel='icon' href='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22%3E"
        "%3Crect width=%2216%22 height=%2216%22 rx=%223%22 fill=%22%23f2a93b%22/%3E%3C/svg%3E'></head><body>"
        f"<header class='topbar'><div class='in'><a class='brand' href='{up}index.html'><span class='mark'>MF</span>"
        f"MapForge</a><nav>{''.join(links)}</nav></div></header>"
        f"<main class='wrap'>{body}<footer>Genereret {time.strftime('%Y-%m-%d %H:%M')} af "
        f"<code>mapforge.site.build</code> fra repoets data · kun lokalt (127.0.0.1)</footer></main></body></html>"
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
    sim, metrics = _load(b / "simulation.json"), _load(b / "analysis" / "metrics.json")
    from mapforge import annotations

    wishes = annotations.load(cfg.path("maps_dir"), name) if cfg.path("maps_dir").is_dir() else []
    stage = stage_of(b) if b.is_dir() else {}
    return {
        "input": True if wishes else None,
        "compile": None if compile_ is None else compile_.get("ok"),
        "validate": None if validation is None else validation.get("ok"),
        "render": None if index is None else True,
        "review": None if stage.get("review_passed") is None else stage["review_passed"],
        "review_stale": review is not None and stage.get("review_passed") is None,
        "simulate": None if sim is None else sim.get("ok"),
        "analyze": None if metrics is None else metrics.get("targets_met"),
        "decide": True if iterations(cfg, name) else None,
        "source": None if validation is None else validation.get("source"),
        "next": stage.get("next"), "why": stage.get("why"),
        "thumb": "topdown.png" if index else None,
    }  # fmt: skip


def _state_cls(built: bool, state: bool | None) -> str:
    return "todo" if not built else ("ok" if state else "bad" if state is False else "todo")


LOOP_STEP_PHASE = {"build": "validate", "review": "review", "sim": "simulate", "decide": "decide"}
NEXT_PHASE = {"validate": "validate", "review": "review", "simulate": "simulate", "fix": "decide",
              "improve or stop": "decide"}  # fmt: skip


def current_phase(cfg: Config, name: str, st: dict[str, Any]) -> tuple[str | None, str]:
    """Where the work on this map is now: (phase key, short text) – from a running loop
    (runs/<map>/loop.json), else from the stage of the build."""
    from mapforge.runs import runs_root

    loop = _load(runs_root(cfg, name) / "loop.json") or {}
    if loop.get("status") == "running":
        step = loop.get("step", "")
        wait = loop.get("awaiting")
        what = {"build": "bygger (generate → compile → validate → render)", "review": "review",
                "sim": "simulerer (bots spiller)", "decide": "Decide"}.get(step, step)  # fmt: skip
        text = f"Loopet: iteration {loop.get('iteration')} · " + (
            f"venter på svar til {wait['step']}" if wait else f"i gang: {what}")  # fmt: skip
        return LOOP_STEP_PHASE.get(step), text
    if loop.get("status") == "stopped":
        return None, f"Loopet stoppede: {loop.get('stop_reason')}"
    nxt = st.get("next")
    return NEXT_PHASE.get(nxt or ""), (f"Næste trin: {nxt}" if nxt else "")


def stepper(
    st: dict[str, Any], link: bool = True, current: str | None = None, phases: list | None = None
) -> str:
    """Pipeline phases as a segmented bar (green passed, red failed, dashed not run); the
    phase the work is at now gets a pulsing arrow."""
    tag = "a" if link else "span"
    steps = "".join(
        f"<{tag} class='step {_state_cls(built, st.get(k))}{' now' if k == current else ''}'"
        + (f" href='#{k}'" if link else "")
        + f" title='{e(label)}{' – her er vi nu' if k == current else ''}'><i></i>{e(label.split()[1])}</{tag}>"
        for k, label, built in (phases and [(k, lbl, True) for k, lbl in phases] or PHASES)
    )
    return f"<div class='stepper'>{steps}</div>"


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{v:.0%}"


def kpis(b: Path) -> str:
    """Headline numbers of a map: balance, sites, contact, round length, score, review."""
    m = _load(b / "analysis" / "metrics.json") or {}
    met = m.get("metrics", {})
    v = _load(b / "validation.json") or {}
    tiles = []

    def tile(value: str, label: str, cls: str = "") -> None:
        tiles.append(f"<div class='kpi {cls}'><b>{value}</b><span>{e(label)}</span></div>")

    def ok(key: str) -> str:
        if key in (m.get("diagnostics") or []):
            return ""
        d = met.get(key, {}).get("distance")
        return "" if d is None else "ok" if d == 0 else "bad"

    if met:
        tile(_pct(met["t_winrate"]["value"]), f"T-winrate · mål {_pct(met['t_winrate']['target'][0])}–"
             f"{_pct(met['t_winrate']['target'][1])}", ok("t_winrate"))  # fmt: skip
        tile(_pct(met["site_split_a"]["value"]), "plants på A", ok("site_split_a"))
        fc = met["first_contact_s"]["value"]
        tile("–" if fc is None else f"{fc:.0f} s", "første kontakt", ok("first_contact_s"))
        rl = met["round_length_median_s"]["value"]
        tile("–" if rl is None else f"{rl:.0f} s", "rundelængde", ok("round_length_median_s"))
        tile(
            f"{m.get('score')}",
            f"score · {m.get('rounds')} runder",
            "ok" if m.get("targets_met") else "",
        )
    for t in v.get("stats", {}).get("timings", [])[:2]:
        ts = (t.get("T") or {}).get("median_s")
        if ts is not None:
            tile(f"{ts:.0f} s", f"T → site {t.get('site')}", "t")
    if not tiles:
        return ""
    return f"<div class='kpis'>{''.join(tiles)}</div>"


def simulate_section(b: Path) -> str:
    """Simulation run (build/<map>/simulation.json): smoke checks, batches, demos."""
    sim = _load(b / "simulation.json")
    parts = ["<section id='simulate' class='panel'><h2><span class='no'>6</span>Simulate</h2>"]
    if not sim:
        parts.append(
            "<p class='muted'>Ikke simuleret endnu (<code>./mf simulate MAP=…</code>).</p></section>"
        )
        return "".join(parts)
    smoke = sim.get("smoke") or {}
    summ = sim.get("summary") or {}
    parts.append(
        f"<p>{_chip(sim.get('ok'), 'OK', 'fejlet')} <span class='muted'>{e(str(sim.get('stop_reason')))}</span></p>"
    )
    tiles = [
        (f"{summ.get('rounds', 0)}", "gyldige runder"),
        (f"{(sim.get('wall_s') or 0) / 60:.1f} min", "wall clock"),
        (f"{sim.get('timescale')}×", "spiltid pr. realtid"),
        (f"{sim.get('servers')}", "servere parallelt"),
        (f"{sim.get('bots_per_team')} v {sim.get('bots_per_team')}", "YaPB-bots"),
        (f"{len(sim.get('demos') or [])}", "HLTV-demoer"),
    ]
    parts.append("<div class='kpis'>" + "".join(f"<div class='kpi'><b>{e(v)}</b><span>{e(lbl)}</span></div>"
                                                 for v, lbl in tiles) + "</div>")  # fmt: skip
    if smoke:
        c = smoke.get("checks", {})
        vr, bm, sr = c.get("valid_rounds", {}), c.get("bots_move", {}), c.get("sites_reached", {})
        sites = sr.get("samples_per_site", {})
        items = [("gyldige runder", vr.get("ok"), f"{vr.get('value')}/{vr.get('want')}"),
                 ("bots bevæger sig", bm.get("ok"), f"{bm.get('value')}/{bm.get('of')}"),
                 ("begge sites nået", sr.get("ok"), " · ".join(f"{k}: {v}" for k, v in sites.items())),
                 ("CSV-skema", not smoke.get("schema_errors"), f"{len(smoke.get('schema_errors') or [])} fejl")]  # fmt: skip
        parts.append("<div class='card'><h3>Smoke-kørsel</h3><div class='phases'>"
                     + "".join(f"{_chip(ok, e(n), e(n))} <span class='muted small'>{e(str(val))}</span> " for n, ok, val in items)
                     + "</div></div>")  # fmt: skip
    groups = [g for g in sim.get("groups", []) if g.get("servers")]
    if groups:
        rows = "".join(f"<tr><td>{e(g['name'])}</td><td class='num'>{len(g['servers'])}</td>"
                       f"<td class='num'>{sum(s.get('rounds_wanted', 0) for s in g['servers'])}</td>"
                       f"<td class='num'>{max(s.get('wall_s') or 0 for s in g['servers']):.0f} s</td>"
                       f"<td>{_chip(all(s.get('done') for s in g['servers']), 'færdig', 'afbrudt')}</td></tr>" for g in groups)  # fmt: skip
        parts.append("<details><summary>Kørsler pr. gruppe</summary><div class='table'><table><tr><th>gruppe</th>"
                     f"<th>servere</th><th>runder</th><th>tid</th><th></th></tr>{rows}</table></div></details>")  # fmt: skip
    demos = sim.get("demos") or []
    if demos:
        parts.append(f"<p class='muted small'>Demoer: kopiér til <code>cstrike/</code> og afspil med <code>playdemo &lt;navn&gt;</code> "
                     f"(klienten skal have samme .bsp) – {e(', '.join(Path(d).name for d in demos))}</p>")  # fmt: skip
    parts.append("</section>")
    return "".join(parts)


ANALYZE_NAMES = {
    "t_winrate": "T-winrate", "site_split_a": "Andel plants på A",
    "first_contact_s": "Første kontakt (median)", "dead_zone_share": "Døde zoner",
    "max_kill_cell_share": "Kill-koncentration", "round_length_median_s": "Rundelængde (median)",
}  # fmt: skip
# scale max, unit, digits, shown as percent
ANALYZE_SCALES = {
    "t_winrate": (1.0, "%", 0, True), "site_split_a": (1.0, "%", 0, True),
    "first_contact_s": (40.0, " s", 1, False), "dead_zone_share": (0.3, "%", 0, True),
    "max_kill_cell_share": (0.2, "%", 0, True), "round_length_median_s": (150.0, " s", 0, False),
}  # fmt: skip


def _verdict_chip(verdict: str) -> str:
    state = True if verdict == "bedre" else False if verdict == "værre" else None
    return _chip(state, "bedre", "værre", e(verdict))


def analyze_section(b: Path, out: Path, img_sub: str = "analysis") -> str:
    """Metrics as bullet charts, round charts, delta and heatmaps (build/<map>/analysis/)."""
    a = b / "analysis"
    m = _load(a / "metrics.json")
    parts = ["<section id='analyze' class='panel'><h2><span class='no'>7</span>Analyze</h2>"]
    if not m:
        parts.append(
            "<p class='muted'>Ikke analyseret endnu (<code>./mf analyze MAP=…</code>).</p></section>"
        )
        return "".join(parts)
    enough = (
        ""
        if m.get("enough_rounds")
        else f" – for få til en fuld måling (FITNESS: {m.get('min_rounds')})"
    )
    parts.append(f"<p>{_chip(m.get('targets_met'), 'alle mål ramt', 'mål ikke ramt')} "
                 f"<span class='muted'>score <b>{m.get('score')}</b> (0 = alle mål) · {m.get('rounds')} gyldige runder{e(enough)}</span></p>")  # fmt: skip
    bullets = []
    for k, v in m.get("metrics", {}).items():
        hi, unit, digits, pct = ANALYZE_SCALES.get(k, (None, "", 2, False))
        f = 100.0 if pct else 1.0

        def sc(x, f=f):
            return None if x is None else x * f

        target = [sc(t) for t in v["target"]] if v.get("target") else None
        diag = k in (m.get("diagnostics") or [])
        bullets.append(charts.bullet(ANALYZE_NAMES.get(k, k) + (" (diagnostik)" if diag else ""), sc(v["value"]), target,
                                     [sc(c) for c in v["ci"]], 0.0, sc(hi) if hi else None, unit, digits))  # fmt: skip
    parts.append("<div class='chartbox'><h3>Metrikker mod mål (grønt bånd = mål, streg = 95 %-interval)</h3>"
                 f"<div class='bullets'>{''.join(bullets)}</div></div>")  # fmt: skip
    series = m.get("series") or []
    boxes = []
    if series:
        tw = m["metrics"]["t_winrate"].get("target")
        boxes.append("<div class='chartbox'><h3>T-winrate undervejs (felt = hvem vandt runden)</h3>"
                     + charts.running_rate([r["winner"] == "T" for r in series], tw, "Løbende T-winrate") + "</div>")  # fmt: skip
        counts: dict[tuple, int] = {}
        for r in series:
            counts[(r["winner"], r["reason"])] = counts.get((r["winner"], r["reason"]), 0) + 1
        segs = [("T eliminering", counts.get(("T", "elimination"), 0), "t"),
                ("T bombe", counts.get(("T", "bomb"), 0), "t2"),
                ("CT eliminering", counts.get(("CT", "elimination"), 0), "ct"),
                ("CT defuse", counts.get(("CT", "defuse"), 0), "ct2"),
                ("CT tid", counts.get(("CT", "time"), 0), "ct3")]  # fmt: skip
        by_site = m.get("plants", {}).get("by_site", {})
        site_segs = [
            (f"site {s}", n, "bar" if i == 0 else "muted")
            for i, (s, n) in enumerate(sorted(by_site.items()))
        ]
        no_plant = len(series) - sum(by_site.values())
        boxes.append("<div class='chartbox'><h3>Rundeudfald</h3>" + charts.stacked(segs, "Rundeudfald")
                     + "<h3>Bombe plantet</h3>"
                     + charts.stacked([*site_segs, ("ingen plant", no_plant, "track")], "Plants pr. site")
                     + "</div>")  # fmt: skip
        boxes.append("<div class='chartbox'><h3>Rundelængde</h3>"
                     + charts.histogram([r["length_s"] for r in series], 14,
                                        m["metrics"]["round_length_median_s"].get("target"), "Rundelængde")
                     + "</div>")  # fmt: skip
        boxes.append("<div class='chartbox'><h3>Første kontakt</h3>"
                     + charts.histogram([r["contact_s"] for r in series if r.get("contact_s") is not None], 14,
                                        m["metrics"]["first_contact_s"].get("target"), "Første kontakt")
                     + "</div>")  # fmt: skip
    eng = m.get("engagements") or {}
    if eng.get("by_distance"):
        dd = eng["by_distance"]
        segs = [
            ("tæt < 500 u", dd.get("close", 0), "ct"),
            ("mellem", dd.get("mid", 0), "bar"),
            ("lang > 1500 u", dd.get("long", 0), "t"),
        ]
        wc = [
            (k, v, "muted" if i else "bar")
            for i, (k, v) in enumerate((eng.get("by_weapon_class") or {}).items())
        ]
        boxes.append("<div class='chartbox'><h3>Kills efter kampafstand</h3>" + charts.stacked(segs, "Kampafstand")
                     + "<h3>Kills efter våbenklasse</h3>" + charts.stacked(wc[:6], "Våbenklasse") + "</div>")  # fmt: skip
    parts.append(f"<div class='charts'>{''.join(boxes)}</div>")
    d = m.get("delta")
    if d:
        drows = "".join(f"<tr><td>{e(ANALYZE_NAMES.get(k, k))}</td><td class='num'>{v['before']}</td><td class='num'>{v['after']}</td>"
                        f"<td class='num'>{v['change']:+}</td><td>{_verdict_chip(v['verdict'])}</td></tr>"
                        for k, v in d["metrics"].items())  # fmt: skip
        parts.append(f"<div class='card'><h3>Delta mod {e(d.get('baseline', ''))}: {e(d['verdict'])}</h3><div class='table'><table><tr><th>metrik</th>"
                     f"<th>før</th><th>efter</th><th>ændring</th><th>vurdering</th></tr>{drows}</table></div></div>")  # fmt: skip
    if m.get("heatmaps"):
        parts.append("<h3>Heatmaps</h3><div class='grid'>")
        for h in m["heatmaps"]:
            src = a / h["file"]
            if src.is_file():
                _copy(src, out / "img" / img_sub / Path(h["file"]).name)
                f = f"img/{img_sub}/{Path(h['file']).name}"
                parts.append(f"<figure><a href='{e(f)}' target='_blank'><img src='{e(f)}' loading='lazy' alt=''></a>"
                             f"<figcaption><b>{e(h['purpose'])}</b> · n={h['n']}</figcaption></figure>")  # fmt: skip
        parts.append("</div>")
    parts.append(
        "<p class='muted small'>Rapport: <code>build/…/analysis/report.md</code>. Tallene beskriver YaPB-bots, ikke mennesker.</p></section>"
    )
    return "".join(parts)


def loop_section(cfg: Config, name: str) -> str:
    """The autonomous loop (runs/<map>/loop.json): status, score per iteration, history."""
    from mapforge.runs import runs_root

    st = _load(runs_root(cfg, name) / "loop.json")
    if not st:
        return ""
    best = st.get("best") or {}
    running = st.get("status") == "running"
    chip = (
        "<span class='chip run'>kører</span>"
        if running
        else f"<span class='chip ok'>stoppet</span> <span class='muted'>{e(str(st.get('stop_reason')))}</span>"
    )
    wait = st.get("awaiting")
    wait_html = (f"<p class='muted'>Venter på <b>{e(wait['step'])}</b>: <code>{e(wait['prompt'])}</code> → <code>{e(wait['answer'])}</code></p>"
                 if wait and running else "")  # fmt: skip
    hist = st.get("history", [])
    trend = charts.trend([(h["iteration"], h.get("score")) for h in hist], "Score pr. iteration")
    rows = "".join(
        f"<tr><td>{e(h['iteration'])}{' ★' if h['iteration'] == best.get('iteration') else ''}</td><td>{e(str(h.get('reached')))}</td>"
        f"<td>{e(str(h.get('review', '–')))}</td><td class='num'>{h.get('score', '–')}</td><td class='num'>{_pct(h.get('t_winrate'))}</td>"
        f"<td class='num'>{_pct(h.get('site_split_a'))}</td><td>{e(str(h.get('verdict') or '–'))}</td>"
        f"<td>{e('; '.join(h.get('applied', [])) or '–')}</td></tr>"
        for h in hist
    )  # fmt: skip
    c = st.get("counters", {})
    return (f"<section id='loop' class='panel'><h2><span class='no'>∞</span>Autonomt loop</h2><p>{chip} "
            f"<span class='muted'>iteration {e(st.get('iteration', ''))} · trin {e(st.get('step', ''))} · bedste {e(str(best.get('iteration', '–')))} "
            f"(score {best.get('score', '–')}) · målinger {c.get('measured', 0)}</span></p>{wait_html}"
            + (f"<div class='chartbox'><h3>Score pr. iteration</h3>{trend}</div>" if trend else "")
            + "<div class='table'><table><tr><th>iteration</th><th>nåede</th><th>review</th><th>score</th><th>T-winrate</th>"
            f"<th>A-plants</th><th>ift. bedste</th><th>anvendte ændringer</th></tr>{rows}</table></div></section>")  # fmt: skip


def topdown_view(cfg: Config, name: str) -> dict[str, Any] | None:
    index = _load(cfg.path("build_dir") / name / "renders" / "index.json")
    top = next((im for im in (index or {}).get("images", []) if im["file"] == "topdown.png"), None)
    return top.get("view") if top else None


def live_block(cfg: Config, name: str) -> str:
    """Live view of this map's running simulations (same stream as the Live page)."""
    view = topdown_view(cfg, name)
    maps = (
        {name: {"img": "img/topdown.png", "rect": view["world_rect"], "size": view["size"]}}
        if view
        else {}
    )
    return (f"<div class='card'><h3>● Live – kørende simuleringer af {e(name)}</h3><p id='status' class='muted small'>forbinder …</p>"
            "<div id='totals' class='kpis'></div><div id='runs' class='livegrid'></div></div>"
            f"<script>const LIVE_MAP = {json.dumps(name)}; const MAPS = {json.dumps(maps)};</script>")  # fmt: skip


def brief_of(cfg: Config, name: str) -> dict[str, Any] | None:
    """maps/<name>/brief.json: a map project started from the dashboard (description)."""
    return _load(cfg.path("maps_dir") / name / "brief.json")


GRID_PX = 1024


def brief_grid(out: Path) -> None:
    """A blank drawing grid for briefs (no geometry yet): img/brief_grid.png over BRIEF_CANVAS."""
    from PIL import Image, ImageDraw

    from mapforge.live.collector import BRIEF_CANVAS

    x0, y0, x1, y1 = BRIEF_CANVAS
    im = Image.new("RGB", (GRID_PX, GRID_PX), (12, 15, 18))
    d = ImageDraw.Draw(im)
    for u in range(x0, x1 + 1, 256):
        px = (u - x0) / (x1 - x0) * GRID_PX
        col = (52, 62, 72) if u % 1024 == 0 else (28, 34, 40)
        w = 2 if u == 0 else 1
        d.line([(px, 0), (px, GRID_PX)], fill=col, width=w)
        d.line([(0, GRID_PX - px), (GRID_PX, GRID_PX - px)], fill=col, width=w)
    d.text((GRID_PX - 22, 8), "N", fill=(220, 220, 220))
    bar = 1024 / (x1 - x0) * GRID_PX
    d.rectangle([12, GRID_PX - 18, 12 + bar, GRID_PX - 13], fill=(220, 220, 220))
    d.text((12, GRID_PX - 34), "1024 units (ca. 4 s lob)", fill=(220, 220, 220))
    d.text((12, 8), "T-spawn typisk mod syd, CT mod nord (vejledende)", fill=(140, 150, 160))
    (out / "img").mkdir(parents=True, exist_ok=True)
    im.save(out / "img" / "brief_grid.png")


def annotate_section(cfg: Config, name: str) -> str:
    """Draw wishes on the map (point / area / line + text) for the loop's Decide step; a brief
    without geometry yet gets the blank grid."""
    from mapforge.live.collector import BRIEF_CANVAS

    if not (cfg.path("maps_dir") / name).is_dir():
        return ""
    view = topdown_view(cfg, name)
    if view:
        ann = {"map": name, "img": "img/topdown.png", "rect": view["world_rect"],
               "size": view["size"]}  # fmt: skip
    elif brief_of(cfg, name):
        ann = {"map": name, "img": "../../img/brief_grid.png", "rect": BRIEF_CANVAS,
               "size": [GRID_PX, GRID_PX]}  # fmt: skip
    else:
        return ""
    return (
        "<section id='annotate' class='panel'><h2><span class='no'>1</span>Input – dine ønsker til mappet</h2>"
        "<p class='muted'>Første fase i hver iteration: dit input. Skriv et ønske som <b>tekst</b> (hele mappet), eller tegn på kortet – fx et <b>punkt</b> med \"flere kasser her\", "
        "et <b>område</b> med \"fjern disse korridorer\" eller en <b>streg</b> med \"en rute som denne\". Loopets næste "
        "Decide behandler åbne ønsker først (låste beslutninger gælder stadig; konflikter eskaleres til dig), og ønsket "
        "markeres som udført, når ændringen er anvendt.</p>"
        "<div class='annwrap'><div><div class='phases tools'><button data-tool='point' class='on'>● Punkt</button>"
        "<button data-tool='rect'>▭ Område</button><button data-tool='path'>✎ Streg</button><button data-tool='note'>¶ Kun tekst</button></div>"
        "<canvas class='anncanvas'></canvas></div><div class='annside'>"
        "<textarea rows='3' maxlength='500' placeholder='Hvad vil du gerne have gjort her?'></textarea>"
        "<div class='phases'><button class='annsave primary'>Gem ønske</button><button class='anncancel'>Annullér</button></div>"
        "<p class='annmsg muted small'></p><h3>Ønsker</h3><ul class='annlist'></ul></div></div>"
        f"<script>const ANN = {json.dumps(ann)};</script><script src='../../annotate.js?v={ANN_VERSION}'></script></section>"
    )  # fmt: skip


def new_page() -> str:
    """Start a map: name + description (POST /api/maps), then sketch on a blank grid."""
    from mapforge.live.collector import BRIEF_CANVAS

    new = {"img": "img/brief_grid.png", "rect": BRIEF_CANVAS, "size": [GRID_PX, GRID_PX],
           "annotate": f"annotate.js?v={ANN_VERSION}"}  # fmt: skip
    return (
        "<section><span class='eyebrow'>Egne maps</span><h1>Nyt map</h1><p class='muted'>Beskriv mappet, "
        "og tegn bagefter, hvad du forestiller dig: sites, ruter, et landmærke, en stemning. Tegningen er "
        "vejledende; Claude laver et layout (<code>layout.yaml</code>) ud fra begge dele, og loopet "
        "itererer derfra. Gemmes i <code>maps/&lt;navn&gt;/brief.json</code> og "
        "<code>annotations.json</code>.</p></section>"
        "<form id='newmap' class='panel'><h2><span class='no'>1</span>Beskrivelse</h2>"
        "<label>Navn <input name='name' required pattern='de_[a-z0-9_]{2,28}' placeholder='de_harbour01'>"
        "</label><label>Beskrivelse <textarea name='description' rows='6' required minlength='10' "
        "maxlength='4000' placeholder='Fx: En havn ved nat. A er et lagerhus med en kran, B ligger på "
        "kajen. Mid er en smal gyde med et vindue ud mod vandet. CT bør kunne rotere på under 12 s.'>"
        "</textarea></label><div class='phases'><button class='primary'>Opret og tegn</button></div>"
        "<p class='annmsg muted small'></p></form>"
        "<section id='annotate' class='panel' hidden><h2><span class='no'>2</span>Tegn – "
        "<span class='mapname'></span></h2><p class='muted'>Punkt, område, streg eller kun tekst – med et "
        "ønske til hver. Et felt er 256 units.</p>"
        "<div class='annwrap'><div><div class='phases tools'><button data-tool='point' class='on'>● Punkt"
        "</button><button data-tool='rect'>▭ Område</button><button data-tool='path'>✎ Streg</button>"
        "<button data-tool='note'>¶ Kun tekst</button></div><canvas class='anncanvas'></canvas></div>"
        "<div class='annside'><textarea rows='3' maxlength='500' placeholder='Hvad skal der være her?'>"
        "</textarea><div class='phases'><button class='annsave primary'>Gem ønske</button>"
        "<button class='anncancel'>Annullér</button></div><p class='annmsg muted small'></p>"
        "<h3>Ønsker</h3><ul class='annlist'></ul>"
        "<p><a id='done' class='chip ok'>Færdig – til map-siden →</a></p></div></div></section>"
        f"<script>const NEW = {json.dumps(new)};</script><script src='newmap.js?v={NEW_VERSION}'></script>"
    )


def live_page(cfg: Config, maps: list[str], out: Path) -> str:
    """Live view of running simulations: SSE from the live collector, drawn by live.js."""
    views = {}
    for m in maps:
        index = _load(cfg.path("build_dir") / m / "renders" / "index.json")
        top = next(
            (im for im in (index or {}).get("images", []) if im["file"] == "topdown.png"), None
        )
        if top and "view" in top:
            _copy(
                cfg.path("build_dir") / m / "renders" / "topdown.png",
                out / "maps" / m / "img" / "topdown.png",
            )
            views[m] = {
                "img": f"maps/{m}/img/topdown.png",
                "rect": top["view"]["world_rect"],
                "size": top["view"]["size"],
            }
    return ("<section><span class='eyebrow'>Simulering</span><h1>Live</h1><p class='muted'>Bots i alle kørende "
            "simuleringer, streamet fra tracker-pluginet (UDP) via live-collectoren (<code>docker compose up -d live</code>, "
            "Server-Sent Events på localhost:8090). Orange = T, blå = CT, grå = død, rødt kryds = kill i runden; streg = sigteretning. "
            "Spiltiden kører hurtigere end realtid (timescale).</p><p id='status' class='muted'>forbinder …</p>"
            "<div id='totals' class='kpis'></div></section><div id='runs' class='livegrid'></div>"
            f"<script>const MAPS = {json.dumps(views)};</script><script src='live.js?v={JS_VERSION}'></script>")  # fmt: skip


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
    src = {"reference": "referencemap (kun .bsp, ikke vores)", "map": "vores eget map"}.get(
        st["source"] or "", "ikke valideret endnu"
    )
    nxt = f"Næste trin: <b>{e(st['next'] or '-')}</b> – {e(st['why'] or '')}"
    if brief_of(cfg, name) and not (cfg.path("maps_dir") / name / "layout.yaml").is_file():
        nxt = "Næste trin: <b>layout</b> – Claude laver <code>layout.yaml</code> ud fra din beskrivelse og tegning"
    cur, cur_text = current_phase(cfg, name, st)
    img = ""
    if st["thumb"]:
        _copy(b / "renders" / "topdown.png", out / "img" / "topdown.png")
        img = "<a href='img/topdown.png' target='_blank'><img src='img/topdown.png' alt='top-down'></a>"
    bar = stepper(st, current=cur).replace(
        "href='#", "href='#vcur-"
    )  # into the current version box
    parts = [f"<section class='hero'><div>{img}</div><div class='side'><div><span class='eyebrow'>Projekt · "
             f"{e(src)}</span><h1>{e(name)}</h1><p class='muted'>{nxt}</p></div>"
             f"{bar}<p class='nowline'>▸ {e(cur_text)}</p>"
             f"{kpis(b)}</div></section>"]  # fmt: skip

    brief = brief_of(cfg, name)
    if brief:
        has_layout = (cfg.path("maps_dir") / name / "layout.yaml").is_file()
        state = ("Layout lavet ud fra briefen." if has_layout else
                 "Venter på layout: Claude laver <code>layout.yaml</code> ud fra beskrivelsen og dine "
                 "tegninger.")  # fmt: skip
        parts.append(f"<section class='panel'><h2><span class='no'>1</span>Input – din beskrivelse</h2>"
                     f"<p class='muted small'>Startet {e(brief.get('created', ''))} fra dashboardet · {state}</p>"
                     f"<div class='card brief'>{e(brief.get('description', ''))}</div></section>")  # fmt: skip

    from mapforge.site.versions import render_versions

    parts.append(render_versions(cfg, name, out, cur, cur_text))
    parts.append(loop_section(cfg, name))
    return "".join(parts)


def iterations_section(cfg: Config, name: str, out: Path) -> str:
    """Timeline of all iterations (runs/<map>/<NNN>/), newest first: what was measured, what
    Decide saw and why it changed what it changed, and what was actually applied."""
    from mapforge.runs import runs_root

    runs = iterations(cfg, name)
    parts = [
        "<section id='decide' class='panel'><h2><span class='no'>8</span>Iterationer – målinger, beslutninger og rationaler</h2>"
    ]
    if not runs:
        parts.append("<p class='muted'>Ingen iterationer endnu.</p></section>")
        return "".join(parts)
    loop = _load(runs_root(cfg, name) / "loop.json") or {}
    {h["iteration"]: h for h in loop.get("history", [])}
    (loop.get("best") or {}).get("iteration")
    parts.append("<p class='muted'>Nyeste først. Hver iteration: billedet og målingen, Decides plan med begrundelse "
                 "(hvilke fund den adresserer, forventet effekt, risiko) og hvad loopet faktisk ændrede.</p><div class='timeline'>")  # fmt: skip
    for run in reversed(runs):
        parts.append(iteration_card(cfg, name, run, out, loop))
    parts.append("</div></section>")
    return "".join(parts)


def iteration_card(cfg: Config, name: str, run: Path, out: Path, loop: dict[str, Any]) -> str:
    """One iteration: thumbnails, measurement, blocking review findings, Decide's plan with
    rationale, what the loop applied, NOTES.md."""
    hist = {h["iteration"]: h for h in loop.get("history", [])}
    best = (loop.get("best") or {}).get("iteration")
    if True:
        h = hist.get(run.name, {})
        plan, dec, applied = (
            _load(run / "plan.json"),
            _load(run / "decision.json"),
            _load(run / "applied.json"),
        )
        review, m = _load(run / "review.json"), _load(run / "analysis" / "metrics.json")
        base = _load(run / "baseline_analysis" / "metrics.json")
        img_dir = out / "img" / "runs" / run.name
        thumbs = []
        for src, label in ((run / "renders" / "topdown.png", "top-down"),
                           (run / "analysis" / "heatmaps" / "traffic_t.png", "trafik T"),
                           (run / "analysis" / "heatmaps" / "traffic_ct.png", "trafik CT"),
                           (run / "analysis" / "heatmaps" / "kills.png", "kills")):  # fmt: skip
            if src.is_file():
                _copy(src, img_dir / src.name)
                f = f"img/runs/{run.name}/{src.name}"
                thumbs.append(
                    f"<a href='{f}' target='_blank' title='{e(label)}'><img src='{f}' loading='lazy' alt='{e(label)}'><span>{e(label)}</span></a>"
                )
        # status chips
        chips = []
        if review:
            chips.append(_chip(review.get("passed"), "review bestået", "review fejlet"))
        elif h.get("reached") in ("generate", "validate"):
            chips.append("<span class='chip bad'>hårde krav fejlede</span>")
        if h.get("reached") == "smoke":
            chips.append("<span class='chip bad'>smoke fejlede</span>")
        if run.name == best:
            chips.append("<span class='chip ok'>★ bedste</span>")
        if h.get("rollback"):
            chips.append("<span class='chip bad'>rollback</span>")
        if h.get("verdict"):
            chips.append(f"<span class='chip'>ift. bedste: {e(h['verdict'])}</span>")
        # measurement
        meas = ""
        for title, mm in (("Måling", m), ("Baseline-måling (ubalanceret udgangspunkt)", base)):
            if not mm:
                continue
            met = mm.get("metrics", {})

            def val(k, pct=True, met=met):
                v = met.get(k, {}).get("value")
                d = met.get(k, {}).get("distance")
                txt = "–" if v is None else (f"{v:.0%}" if pct else f"{v:.0f} s")
                cls = "" if d is None else "ok" if d == 0 else "bad"
                return f"<span class='kv {cls}'><b>{txt}</b>{e(ANALYZE_NAMES.get(k, k))}</span>"

            meas += (f"<div class='meas'><h4>{e(title)} · {mm.get('rounds')} runder · score <b>{mm.get('score')}</b></h4>"
                     f"{val('t_winrate')}{val('site_split_a')}{val('first_contact_s', False)}{val('round_length_median_s', False)}"
                     f"{val('dead_zone_share')}{val('max_kill_cell_share')}</div>")  # fmt: skip
        if review and review.get("findings"):
            sev = [f for f in review["findings"] if f["severity"] in ("critical", "major")]
            if sev:
                meas += (
                    "<div class='meas'><h4>Review-fund der blokerede</h4><ul>"
                    + "".join(
                        f"<li><span class='sev-{e(f['severity'])}'>{e(f['severity'])}</span> {e(f['what'])}</li>"
                        for f in sev
                    )
                    + "</ul></div>"
                )
        if h.get("note"):
            meas += f"<p class='muted small'>Note: {e(h['note'])}</p>"
        # decision
        decision = ""
        if plan:
            if plan.get("escalate"):
                decision += f"<p><span class='chip bad'>eskaleret</span> {e(plan.get('escalation_reason', ''))}</p>"
            decision += f"<p class='plan'><b>Beslutning:</b> {e(plan.get('summary', ''))}</p>"
            for c in plan.get("changes", []):
                addr = "".join(f"<span class='chip'>{e(a)}</span>" for a in c.get("addresses", []))
                decision += (f"<div class='change'><div><code>{e(c.get('type', ''))}</code> "
                             f"<span class='muted small'>{e(json.dumps(c.get('params', {}), ensure_ascii=False))}</span></div>"
                             f"<p><b>Hvorfor:</b> {e(c.get('rationale', ''))}</p>"
                             + (f"<div class='phases'><span class='muted small'>adresserer:</span>{addr}</div>" if addr else "")
                             + "</div>")  # fmt: skip
            decision += (f"<p class='small'><b>Forventet effekt:</b> {e(plan.get('expected_effect', ''))}</p>"
                         f"<p class='small muted'><b>Risiko:</b> {e(plan.get('risk', ''))}</p>")  # fmt: skip
        if applied:
            done = "".join(
                f"<li class='ok'>{e(a['effect'])}</li>" for a in applied.get("applied", [])
            )
            skipped = "".join(f"<li class='bad'>{e(f.get('type', ''))}: {e(f['reason'])}</li>"
                              for f in applied.get("failed", []) + applied.get("rejected_by_policy", []))  # fmt: skip
            decision += (f"<div class='applied'><b>Anvendt af loopet</b> <span class='muted small'>(på {e(applied.get('base', ''))})</span>"
                         f"<ul>{done}{skipped or ''}</ul></div>")  # fmt: skip
        elif dec:
            decision += f"<p class='small'>Politik-tjek: {_chip(dec.get('ok'), 'accepteret', 'afvist')} · anvendt: {'ja' if dec.get('applied') else 'nej (tørkørsel)'}</p>"
        if not plan:
            step = loop.get("step") if loop.get("iteration") == run.name else None
            decision += (
                f"<p class='muted'>{'I gang: ' + e(step) if step else 'Ingen plan endnu.'}</p>"
            )
        notes = ""
        if (run / "NOTES.md").is_file():
            notes = f"<details open><summary>NOTES.md – Decides noter</summary><div class='notes'>{_md((run / 'NOTES.md').read_text(encoding='utf-8'))}</div></details>"
        return (f"<article class='iter' id='it{run.name}'><div class='iter-head'><h3>Iteration {e(run.name)}</h3>"
                f"<div class='phases'>{''.join(chips)}</div></div>"
                f"<div class='iter-body'><div class='thumbs'>{''.join(thumbs)}</div><div class='iter-text'>"
                f"{meas}{decision}{notes}</div></div></article>")  # fmt: skip


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
    trend_pts = [
        (v.name, ((_load(v / "meta.json") or {}).get("analysis") or {}).get("score")) for v in vers
    ]
    trend = charts.trend(trend_pts, "Score pr. version (bot-analyse)")
    trend_html = f"<div class='chartbox'><h3>Score pr. version</h3>{trend}</div>" if trend else ""
    return (
        f"<section id='history' class='panel'><h2><span class='no'>H</span>Historik</h2>{trend_html}<p class='muted'>{len(vers)} versioner, nyeste først. "
        "En ny version oprettes, når mappet ændrer sig; klik for alle billeder og data.</p>"
        f"<div class='grid small'>{''.join(cards)}</div></section>"
    )


def build_site(cfg: Config) -> Path:
    out = cfg.path("build_dir") / "site"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).with_name("style.css"), out / "style.css")
    maps = discover_maps(cfg)

    # Architecture & roadmap: the overview page (it carries its own styles).
    overview = (cfg.root / "docs" / "overview.html").read_text(encoding="utf-8")
    topbar = ("<header class='topbar'><div class='in'><a class='brand' href='index.html'><span class='mark'>MF</span>"
              "MapForge</a><nav><a href='index.html'>Projekter</a><a href='live.html'>● Live</a><a class='on' href='architecture.html'>"
              "Arkitektur &amp; roadmap</a></nav></div></header>")  # fmt: skip
    marker = '<div class="wrap">'
    page = overview.replace(marker, topbar + marker, 1) if marker in overview else topbar + overview
    (out / "architecture.html").write_text(
        "<!doctype html><html lang='da'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>" + page,
        encoding="utf-8",
    )

    def progress(m: str) -> int:
        st = map_status(cfg, m)
        return sum(1 for k, _, built in PHASES if built and st.get(k))

    def card(m: str) -> str:
        st = map_status(cfg, m)
        cur, cur_text = current_phase(cfg, m, st)
        b = cfg.path("build_dir") / m
        bg = ""
        if st["thumb"]:
            _copy(b / "renders" / "topdown.png", out / "maps" / m / "img" / "topdown.png")
            bg = f" style=\"background-image:url('maps/{m}/img/topdown.png')\""
        done = progress(m)
        met = (_load(b / "analysis" / "metrics.json") or {}).get("metrics", {})
        mini = []
        if met.get("t_winrate", {}).get("value") is not None:
            mini.append(f"<span>T-winrate <b>{_pct(met['t_winrate']['value'])}</b></span>")
        if met.get("site_split_a", {}).get("value") is not None:
            mini.append(f"<span>A-plants <b>{_pct(met['site_split_a']['value'])}</b></span>")
        n_versions = len(versions(cfg, m))
        if n_versions:
            mini.append(f"<span>versioner <b>{n_versions}</b></span>")
        badge = "<span class='chip run badge'>referencemap</span>" if st["source"] == "reference" else (
            "<span class='chip ok badge'>eget map</span>")  # fmt: skip
        return (
            f"<a class='pcard' href='maps/{m}/index.html'><div class='img'{bg}>{badge}</div><div class='body'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;gap:10px'>"
            f"<div><div class='name'>{e(m)}</div><div class='muted small'>næste: {e(st['next'] or '-')}</div></div>"
            f"{charts.ring(done / sum(1 for *_, bl in PHASES if bl), f'{done} faser bestået')}</div>"
            f"{stepper(st, link=False, current=cur)}<p class='nowline small'>▸ {e(cur_text)}</p>"
            f"<div class='mini'>{''.join(mini)}</div></div></a>"
        )

    own = [m for m in maps if map_status(cfg, m)["source"] != "reference"]
    refs = sorted((m for m in maps if m not in own), key=lambda m: (-progress(m), m))
    rows = []
    new_card = ("<a class='pcard newcard' href='new.html'><div class='plus'>+</div><div class='body'>"
                "<div class='name'>Nyt map</div><p class='muted small'>Start med en beskrivelse og tegn, "
                "hvad du forestiller dig.</p></div></a>")  # fmt: skip
    rows.append(f"<section><h2>Egne maps</h2><p class='muted'>Maps vi selv genererer og compiler.</p>"
                f"<div class='cards' data-own-maps='{e(json.dumps(own))}'>{new_card}"
                f"{''.join(card(m) for m in own)}</div></section>")  # fmt: skip
    for title, group, note in (
        (
            "Referencemaps",
            refs,
            "Officielle og community-maps (kun .bsp), brugt til at teste og kalibrere pipelinen.",
        ),
    ):
        if group:
            rows.append(f"<section><h2>{title}</h2><p class='muted'>{note}</p>"
                        f"<div class='cards'>{''.join(card(m) for m in group)}</div></section>")  # fmt: skip
    home = ("<section><span class='eyebrow'>Oversigt</span><h1>Projekter</h1><p class='muted'>Ét "
            "projekt pr. map. Bjælken viser pipelinens faser: grøn = kørt og bestået, rød = kørt og "
            "fejlet, stiplet = ikke kørt. <a href='architecture.html'>Arkitektur og roadmap</a>.</p></section>"
            f"{''.join(rows)}<script src='newmap.js?v={NEW_VERSION}'></script>")  # fmt: skip
    (out / "live.html").write_text(
        _page("MapForge – live", live_page(cfg, maps, out), 0, "live", maps), encoding="utf-8"
    )
    shutil.copy2(Path(__file__).with_name("live.js"), out / "live.js")
    shutil.copy2(Path(__file__).with_name("annotate.js"), out / "annotate.js")
    shutil.copy2(Path(__file__).with_name("newmap.js"), out / "newmap.js")
    brief_grid(out)
    (out / "new.html").write_text(_page("MapForge – nyt map", new_page(), 0, "nyt map", maps),
                                  encoding="utf-8")  # fmt: skip
    (out / "index.html").write_text(_page("MapForge – projekter", home, 0, "home", maps),
                                    encoding="utf-8")  # fmt: skip
    for m in maps:
        mdir = out / "maps" / m
        mdir.mkdir(parents=True, exist_ok=True)
        body = map_page(cfg, m, mdir)
        hist = annotate_section(cfg, m)
        if hist:  # right after the project header (and the brief, if the map started as one)
            cut = body.index("</section>") + len("</section>")
            if brief_of(cfg, m):
                cut = body.index("</section>", cut) + len("</section>")
            body = body[:cut] + hist + body[cut:]
        body += f"<script src='../../live.js?v={JS_VERSION}'></script>"
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
