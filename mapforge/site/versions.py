"""The map page as a version timeline: every version of the map (history/<map>/<NNN>/) is a box
with its top-down and headline numbers; opening it shows that version's 8 phases:

  1 Input (the human's wishes and the changes that made this version) · 2 Compile · 3 Validate ·
  4 Render · 5 Review · 6 Simulate · 7 Analyze · 8 Decide

The newest version is the current one: it carries the "we are here" arrow. Files for a version
come from (in order) the current build (newest only), its history dir and the loop iterations
that measured it (history meta notes "loop iteration NNN").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mapforge.config import Config

PHASES8 = [
    ("input", "1 Input"), ("compile", "2 Compile"), ("validate", "3 Validate"), ("render", "4 Render"),
    ("review", "5 Review"), ("simulate", "6 Simulate"), ("analyze", "7 Analyze"), ("decide", "8 Decide"),
]  # fmt: skip


@dataclass
class Version:
    key: str  # "004" or "build"
    srcs: list[Path]
    meta: dict[str, Any]
    current: bool
    runs: list[Path] = field(default_factory=list)  # iterations that measured this version
    input_runs: list[Path] = field(default_factory=list)  # iterations whose plan created it

    def path(self, rel: str) -> Path | None:
        for s in self.srcs:
            if (s / rel).exists():
                return s / rel
        return None

    def json(self, rel: str) -> Any:
        p = self.path(rel)
        return json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else None


def collect_versions(cfg: Config, name: str) -> list[Version]:
    """Oldest first."""
    from mapforge.history import versions
    from mapforge.runs import iterations

    build = cfg.path("build_dir") / name
    hist = versions(cfg, name)
    runs = {r.name: r for r in iterations(cfg, name)}
    out: list[Version] = []
    linked: set[str] = set()
    for i, v in enumerate(hist):
        meta = (
            json.loads((v / "meta.json").read_text(encoding="utf-8"))
            if (v / "meta.json").is_file()
            else {}
        )
        its = sorted(
            {m for n in meta.get("notes", []) for m in re.findall(r"loop iteration (\d{3})", n)}
        )
        its = [runs[x] for x in its if x in runs]
        linked |= {r.name for r in its}
        current = i == len(hist) - 1
        srcs = ([build] if current else []) + [v] + its
        out.append(Version(v.name, srcs, meta, current, its))
    if not out:
        out.append(Version("build", [build], {}, True))
    # iterations nobody links (e.g. a dry-run Decide): with the newest version
    out[-1].runs += [r for k, r in sorted(runs.items()) if k not in linked]
    for prev, ver in zip(out, out[1:], strict=False):
        ver.input_runs = [r for r in prev.runs if (r / "applied.json").is_file()]
    return out


def wish_version(w: dict[str, Any], vers: list[Version]) -> str | None:
    """The version a wish was drawn on: the newest version created no later than the wish."""
    if w.get("version"):
        return str(w["version"])
    made = str(w.get("created") or "")
    keys = [v.key for v in vers if str(v.meta.get("created") or "") <= made]
    return keys[-1] if keys else (vers[0].key if vers else None)


WISH_COLORS = {
    "open": "#f2a93b",
    "done": "#5cc28a",
    "needs_human": "#ef6a55",
    "rejected": "#8d969f",
}
WISH_LABEL = {"open": "åben", "done": "udført", "needs_human": "kræver dig", "rejected": "afvist"}


def wish_overlay(v: Version, wishes: list[dict], img_rel: str) -> str:
    """The version's top-down with its wishes drawn on it (inline SVG, same marks as annotate.js)."""
    index = v.json("renders/index.json") or {}
    view = next(
        (im.get("view") for im in index.get("images", []) if im["file"] == "topdown.png"), None
    )
    if not view or not v.path("renders/topdown.png"):
        return ""
    (x0, y0, x1, y1), (w_px, h_px) = view["world_rect"], view["size"]

    def px(p: list[float]) -> tuple[float, float]:
        return (p[0] - x0) / (x1 - x0) * w_px, (y1 - p[1]) / (y1 - y0) * h_px

    marks = []
    for w in wishes:
        if not w.get("points"):
            continue
        c = WISH_COLORS.get(w["status"], "#fff")
        pts = [px(p) for p in w["points"]]
        if w["kind"] == "point":
            (x, y) = pts[0]
            marks.append(
                f"<circle cx='{x:.0f}' cy='{y:.0f}' r='12' fill='{c}' fill-opacity='.35' stroke='{c}' stroke-width='4'/>"
            )
        elif w["kind"] == "rect" and len(pts) >= 2:
            (ax, ay), (bx, by) = pts[:2]
            marks.append(f"<rect x='{min(ax, bx):.0f}' y='{min(ay, by):.0f}' width='{abs(bx - ax):.0f}' height='{abs(by - ay):.0f}' "
                         f"fill='{c}' fill-opacity='.18' stroke='{c}' stroke-width='4' stroke-dasharray='10 6'/>")  # fmt: skip
        else:
            line = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
            marks.append(f"<polyline points='{line}' fill='none' stroke='{c}' stroke-width='5'/>")
        x, y = pts[0]
        marks.append(f"<text x='{x + 14:.0f}' y='{y - 10:.0f}' fill='{c}' font-size='26' font-weight='bold' "
                     f"stroke='#000' stroke-width='5' paint-order='stroke'>#{w['id']}</text>")  # fmt: skip
    return (f"<svg class='wishmap' viewBox='0 0 {w_px} {h_px}' role='img' aria-label='Dine ønsker tegnet på denne version'>"
            f"<image href='{img_rel}/topdown.png' width='{w_px}' height='{h_px}'/>{''.join(marks)}</svg>")  # fmt: skip


def status(v: Version) -> dict[str, bool | None]:
    comp, val, rev = v.json("compile.json"), v.json("validation.json"), v.json("review.json")
    sim = v.json("simulation.json") or v.json("sim/simulation.json")
    met = v.json("analysis/metrics.json")
    applied = [json.loads((r / "applied.json").read_text(encoding="utf-8")) for r in v.input_runs]
    return {
        "input": True if any(a.get("applied") for a in applied) else None,
        "compile": None if comp is None else comp.get("ok"),
        "validate": None if val is None else val.get("ok"),
        "render": True if v.path("renders/index.json") else None,
        "review": None if rev is None else rev.get("passed"),
        "simulate": None if sim is None else sim.get("ok"),
        "analyze": None if met is None else met.get("targets_met"),
        "decide": True if any((r / "plan.json").is_file() for r in v.runs) else None,
    }


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def headline(v: Version) -> list[tuple[str, str, str]]:
    """(value, label, css) of a version's key numbers."""
    tiles = []
    m = v.json("analysis/metrics.json") or {}
    met = m.get("metrics", {})
    diag = set(m.get("diagnostics") or [])

    def cls(k: str) -> str:
        d = met.get(k, {}).get("distance")
        return "" if d is None or k in diag else "ok" if d == 0 else "bad"

    if met:
        tiles.append((_pct(met["t_winrate"]["value"]), "T-winrate (bots)", cls("t_winrate")))
        tiles.append((_pct(met["site_split_a"]["value"]), "plants på A", cls("site_split_a")))
        tiles.append(
            (
                str(m.get("score")),
                f"score · {m.get('rounds')} runder",
                "ok" if m.get("targets_met") else "",
            )
        )
    val = v.json("validation.json") or {}
    design = val.get("stats", {}).get("design", {})
    for r in design.get("rotation", [])[:1]:
        tiles.append((f"{r['seconds']:.0f} s", f"rotation {r['sites']}", ""))
    for t in val.get("stats", {}).get("timings", [])[:2]:
        ts = (t.get("T") or {}).get("median_s")
        if ts is not None:
            tiles.append((f"{ts:.0f} s", f"T → site {t.get('site')}", "t"))
    if val:
        s = val.get("summary", {})
        tiles.append(
            (
                f"{s.get('errors', 0)}/{s.get('warnings', 0)}",
                "errors/warnings",
                "bad" if s.get("errors") else "",
            )
        )
    rev = v.json("review.json") or {}
    if rev.get("rubric"):
        avg = sum(x["score"] for x in rev["rubric"]) / len(rev["rubric"])
        tiles.append(
            (
                f"{avg:.1f}",
                "design-rubrik (1–5)",
                "ok" if avg >= 3.5 else "bad" if avg < 2.5 else "",
            )
        )
    return tiles


def render_versions(
    cfg: Config, name: str, out: Path, current_phase: str | None, current_text: str
) -> str:
    from mapforge import annotations
    from mapforge.runs import runs_root
    from mapforge.site.build import _copy, _load, e, stepper

    vers = collect_versions(cfg, name)
    loop = _load(runs_root(cfg, name) / "loop.json") or {}
    wishes = annotations.load(cfg.path("maps_dir"), name)
    for w in wishes:
        w["_version"] = wish_version(w, vers)
    boxes = []
    for v in reversed(vers):
        st = status(v)
        tag = f"v{v.key}"
        img_dir, img_rel = out / "img" / tag, f"img/{tag}"
        thumb = ""
        top = v.path("renders/topdown.png")
        if top:
            _copy(top, img_dir / "topdown.png")
            thumb = f"<img src='{img_rel}/topdown.png' alt='top-down' loading='lazy'>"
        kpis = "".join(
            f"<div class='kpi {c}'><b>{e(val)}</b><span>{e(lbl)}</span></div>"
            for val, lbl, c in headline(v)
        )
        title = "Nuværende version" if v.current else "Version"
        chips = []
        if v.current:
            chips.append("<span class='chip run'>▶ her er vi</span>")
        if v.meta.get("created"):
            chips.append(f"<span class='chip'>{e(v.meta['created'])}</span>")
        if v.runs:
            chips.append(f"<span class='chip'>loop: {', '.join(r.name for r in v.runs)}</span>")
        cur = current_phase if v.current else None
        idle = loop.get("status") != "running"
        bar = stepper(st, link=False, current=cur, phases=PHASES8, idle=idle)
        now = (
            f"<p class='nowline small{' idle' if idle else ''}'>▸ {e(current_text)}</p>"
            if v.current and current_text
            else ""
        )
        summary = (f"<summary class='vhead'><div class='vthumb'>{thumb}</div><div class='vmain'>"
                   f"<div class='vtitle'><h3>{title} {e(v.key)}</h3><div class='phases'>{''.join(chips)}</div></div>"
                   f"{bar}{now}<div class='kpis'>{kpis}</div></div><span class='vtoggle'>▾</span></summary>")  # fmt: skip
        anchor = "vcur" if v.current else tag  # the hero's phase bar links to #vcur-<phase>
        body = phase_panels(cfg, name, v, out, img_dir, img_rel, anchor, st, wishes, loop)
        boxes.append(
            f"<details class='ver{' current' if v.current else ''}' id='{anchor}'>{summary}<div class='vbody'>{body}</div></details>"
        )
    return ("<section id='versions'><h2>Versioner <span class='muted small'>– nyeste først · klik på en kasse for alle 8 faser</span></h2>"
            f"<div class='vlist'>{''.join(boxes)}</div></section>"
            # a link to a phase inside a closed box opens the box first
            "<script>function mfOpen(){const t=document.getElementById(location.hash.slice(1));"
            "if(t){const d=t.closest('details');if(d&&!d.open){d.open=true;t.scrollIntoView();}}}"
            "window.addEventListener('hashchange',mfOpen);mfOpen();</script>")  # fmt: skip


def _strip_section(html: str) -> str:
    """Inner HTML of a <section> panel (drop its <section> and <h2>)."""
    html = re.sub(r"^<section[^>]*>(<h2>.*?</h2>)?", "", html, count=1)
    return html.removesuffix("</section>")


def phase_panels(cfg: Config, name: str, v: Version, out: Path, img_dir: Path, img_rel: str, tag: str,
                 st: dict[str, Any], wishes: list[dict], loop: dict[str, Any]) -> str:  # fmt: skip
    from mapforge.site import charts
    from mapforge.site.build import (
        _chip,
        _copy,
        _findings_table,
        analyze_section,
        e,
        iteration_card,
        live_block,
        simulate_section,
    )  # fmt: skip

    def panel(key: str, label: str, inner: str) -> str:
        no, title = label.split(" ", 1)
        mark = _chip(st.get(key), "ok", "fejl", "–")
        return (f"<section id='{tag}-{key}' class='panel phase'><h2><span class='no'>{no}</span>{e(title)} {mark}</h2>"
                f"{inner}</section>")  # fmt: skip

    parts = []
    # 1 Input
    inner = []
    mine = [w for w in wishes if w.get("_version") == v.key]
    if mine:
        rows = "".join(
            f"<li class='st-{e(w['status'])}'>#{w['id']} <span class='chip' style='color:{WISH_COLORS.get(w['status'], '#fff')}'>"
            f"{e(WISH_LABEL.get(w['status'], w['status']))}</span> {e(w['text'])}"
            + (
                f"<div class='muted small'>{e(w['resolution'])}</div>"
                if w.get("resolution")
                else ""
            )
            + "</li>"
            for w in mine
        )
        inner.append(f"<div class='card'><h3>Dine ønsker til denne version</h3><div class='wishwrap'>"
                     f"{wish_overlay(v, mine, img_rel)}<ul class='annlist'>{rows}</ul></div></div>")  # fmt: skip
    for r in v.input_runs:
        applied = json.loads((r / "applied.json").read_text(encoding="utf-8"))
        plan = (
            json.loads((r / "plan.json").read_text(encoding="utf-8"))
            if (r / "plan.json").is_file()
            else {}
        )
        effects = "".join(
            f"<li class='ok'>{e(a['effect'])}</li>" for a in applied.get("applied", [])
        )
        inner.append(f"<div class='card'><h3>Ændringer der skabte denne version (Decide, iteration {e(r.name)})</h3>"
                     f"<p>{e(plan.get('summary', ''))}</p><ul>{effects}</ul></div>")  # fmt: skip
        done = [
            w for w in wishes if str(w.get("resolution") or "").startswith(f"iteration {r.name}")
        ]
        if done:
            inner.append("<div class='card'><h3>Dine ønsker opfyldt her</h3><ul>" + "".join(
                f"<li>#{w['id']} {e(w['text'])} <span class='muted small'>– {e(w['resolution'])}</span></li>" for w in done) + "</ul></div>")  # fmt: skip
    if v.current:
        open_ = [w for w in wishes if w["status"] in ("open", "needs_human") and w not in mine]
        if open_:
            inner.append("<div class='card'><h3>Åbne ønsker fra tidligere versioner – går ind i næste Decide</h3><ul>" + "".join(
                f"<li>#{w['id']} {e(w['text'])} {_chip(None if w['status'] == 'open' else False, '', 'kræver dig', 'åben')}</li>" for w in open_)
                + "</ul><p class='muted small'>Tilføj flere under <a href='#annotate'>1 Input – dine ønsker</a> øverst.</p></div>")  # fmt: skip
    if not inner:
        inner.append(
            "<p class='muted'>Ingen input til denne version (første version eller lavet uden for loopet).</p>"
        )
    parts.append(panel("input", "1 Input", "".join(inner)))
    # 2 Compile
    c = v.json("compile.json")
    inner = (f"<p>{_chip(c.get('ok'))} {e(c.get('failure') or 'compile uden fejl')} · {c.get('seconds')} s</p>"
             if c else "<p class='muted'>Intet compile (referencemaps compiles ikke af os).</p>")  # fmt: skip
    parts.append(panel("compile", "2 Compile", inner))
    # 3 Validate
    val = v.json("validation.json")
    inner = []
    if val:
        s = val["summary"]
        inner.append(
            f"<p>{_chip(val['ok'])} {s.get('errors', 0)} errors · {s.get('warnings', 0)} warnings</p>"
        )
        inner.append(_findings_table([f for f in val["findings"] if f["severity"] in ("error", "warning")],
                                     ("severity", "rule", "message", "location")))  # fmt: skip
        stats, vt = val.get("stats", {}), cfg.data["validate"]
        boxes = []
        if stats.get("timings"):
            tc = vt.get("timings", {})
            boxes.append("<div class='chartbox'><h3>Løbetider spawn → site</h3>" + charts.timings(
                stats["timings"], (tc.get("min_t_s", 14), tc.get("max_t_s", 26)), tc.get("min_ct_lead_s", 3)) + "</div>")  # fmt: skip
        d = stats.get("design", {})
        if d:
            sl, terr, ss = (
                d.get("sightlines", {}),
                d.get("territory", {}),
                d.get("spawn_sightlines", {}),
            )
            rows = [("Rotation", ", ".join(f"{r['sites']} {r['seconds']} s" for r in d.get("rotation", [])) or "–", "officielle 6–17 s"),
                    ("Territorium T / CT", f"{_pct(terr.get('t_share'))} / {_pct(terr.get('ct_share'))}", "officielle T 29–54 %"),
                    ("Lange sigtelinjer ≥ 1500 u", _pct(sl.get("share_long")), "officielle 7–62 %"),
                    ("Nærkampssteder < 500 u", f"{(sl.get('share_close') or 0) * 100:.1f} %", "officielle 0,9–6,0 %"),
                    ("Spawn ser spawn / site", f"{ss.get('spawn_to_spawn_pairs', 0)} / {sum(ss.get('t_spawn_to_site', {}).values())}", "officielle 0 / 0")]  # fmt: skip
            lg = d.get("layout_graph")
            if lg:
                rows.append(
                    (
                        "Indgange pr. site",
                        ", ".join(f"{k}: {n}" for k, n in lg["site_entrances"].items()),
                        "norm 2–3",
                    )
                )
                rows.append(("4-vejskryds", ", ".join(lg["four_way"]) or "ingen", "Ølsted: ingen"))
            boxes.append("<div class='chartbox'><h3>Design-regler (struktur)</h3><div class='table'><table>"
                         + "".join(f"<tr><td>{e(a)}</td><td class='num'>{e(b)}</td><td class='muted small'>{e(c)}</td></tr>" for a, b, c in rows)
                         + "</table></div></div>")  # fmt: skip
        if boxes:
            inner.append(f"<div class='charts'>{''.join(boxes)}</div>")
    else:
        inner.append("<p class='muted'>Ikke valideret.</p>")
    parts.append(panel("validate", "3 Validate", "".join(inner)))
    # 4 Render
    index = v.json("renders/index.json")
    inner = []
    if index:
        inner.append("<div class='grid small'>")
        for im in index["images"]:
            p = v.path(f"renders/{im['file']}")
            if p:
                _copy(p, img_dir / im["file"])
                inner.append(f"<figure><a href='{img_rel}/{e(im['file'])}' target='_blank'><img src='{img_rel}/{e(im['file'])}' "
                             f"loading='lazy' alt=''></a><figcaption><b>{e(im['file'])}</b></figcaption></figure>")  # fmt: skip
        inner.append("</div>")
    else:
        inner.append("<p class='muted'>Ikke renderet.</p>")
    parts.append(panel("render", "4 Render", "".join(inner)))
    # 5 Review
    r = v.json("review.json")
    inner = []
    if r:
        inner.append(
            f"<p>{_chip(r.get('passed'), 'bestået', 'fejlet')}</p><div class='card'>{e(r.get('summary', ''))}</div>"
        )
        inner.append(_findings_table(r.get("findings", []), ("severity", "where", "what", "image")))
        if r.get("rubric"):
            inner.append("<div class='chartbox'><h3>Design-rubrik (1–5)</h3><div class='rubric'>" + "".join(
                f"<div class='rub'><span>{e(x['id'])}</span><div class='rubbar s{int(x['score'])}'>"
                + "".join(f"<i class='{'on' if k < x['score'] else ''}'></i>" for k in range(5))
                + f"</div><b>{int(x['score'])}</b><p class='muted small'>{e(x.get('reason', ''))}</p></div>" for x in r["rubric"]) + "</div></div>")  # fmt: skip
    else:
        inner.append("<p class='muted'>Ikke reviewet.</p>")
    parts.append(panel("review", "5 Review", "".join(inner)))
    # 6 Simulate (+ live on the current version)
    sim_dir = next(
        (p.parent for p in (v.path("simulation.json"), v.path("sim/simulation.json")) if p), None
    )
    inner = (
        _strip_section(simulate_section(sim_dir))
        if sim_dir
        else "<p class='muted'>Ikke simuleret.</p>"
    )
    if v.current:
        inner += live_block(cfg, name)
    parts.append(panel("simulate", "6 Simulate", inner))
    # 7 Analyze
    a_dir = next((s for s in v.srcs if (s / "analysis" / "metrics.json").is_file()), None)
    inner = (
        _strip_section(analyze_section(a_dir, out, f"{tag}/analysis"))
        if a_dir
        else "<p class='muted'>Ikke analyseret.</p>"
    )
    parts.append(panel("analyze", "7 Analyze", inner))
    # 8 Decide
    cards = "".join(iteration_card(cfg, name, run, out, loop) for run in reversed(v.runs))
    parts.append(panel("decide", "8 Decide", f"<div class='timeline'>{cards}</div>" if cards else
                       "<p class='muted'>Ingen beslutninger på denne version.</p>"))  # fmt: skip
    return "".join(parts)
