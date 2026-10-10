"""Inline SVG charts for the local site: no JavaScript, no libraries, themed by CSS classes.

Classes used (style.css): .ax axis/grid, .lbl labels, .band target range, .val value marker,
.ci interval whisker, .t / .ct team colours, .ok / .bad states, .bar neutral bars.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

e = html.escape


def _svg(w: int, h: int, body: str, label: str, cls: str = "chart") -> str:
    return (f"<svg class='{cls}' viewBox='0 0 {w} {h}' role='img' aria-label='{e(label)}'>"
            f"<title>{e(label)}</title>{body}</svg>")  # fmt: skip


def _fmt(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "–"
    return f"{v:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{v:.0f}"


def bullet(label: str, value: float | None, target: Sequence[float] | None,
           ci: Sequence[float | None] | None = None, lo: float = 0.0, hi: float | None = None,
           unit: str = "", digits: int = 2) -> str:  # fmt: skip
    """One metric on a scale: shaded target band, interval whisker, value marker."""
    w, h, x0, x1 = 560, 54, 190, 540
    vals = [v for v in [value, *(target or []), *(ci or [])] if v is not None]
    hi = hi if hi is not None else (max(vals) * 1.25 if vals else 1.0) or 1.0
    sx = lambda v: x0 + (min(max(v, lo), hi) - lo) / (hi - lo) * (x1 - x0)  # noqa: E731
    ok = target is not None and value is not None and target[0] <= value <= target[1]
    parts = [f"<text class='lbl' x='0' y='24'>{e(label)}</text>",
             f"<text class='lbl big {'ok' if ok else 'bad' if value is not None and target else ''}' x='0' y='44'>"
             f"{_fmt(value, digits)}{e(unit)}</text>",
             f"<rect class='track' x='{x0}' y='18' width='{x1 - x0}' height='14' rx='3'/>"]  # fmt: skip
    if target:
        a, b = sx(target[0]), sx(target[1])
        parts.append(
            f"<rect class='band' x='{a:.1f}' y='18' width='{max(b - a, 2):.1f}' height='14' rx='3'/>"
        )
        parts.append(f"<text class='lbl small' x='{a:.1f}' y='48'>{_fmt(target[0], digits)}</text>")
        parts.append(
            f"<text class='lbl small' x='{b:.1f}' y='48' text-anchor='end'>{_fmt(target[1], digits)}</text>"
        )
    if ci and ci[0] is not None and ci[1] is not None:
        a, b = sx(ci[0]), sx(ci[1])
        parts.append(f"<line class='ci' x1='{a:.1f}' y1='25' x2='{b:.1f}' y2='25'/>"
                     f"<line class='ci' x1='{a:.1f}' y1='20' x2='{a:.1f}' y2='30'/>"
                     f"<line class='ci' x1='{b:.1f}' y1='20' x2='{b:.1f}' y2='30'/>")  # fmt: skip
    if value is not None:
        x = sx(value)
        parts.append(f"<path class='val {'ok' if ok else 'bad' if target else ''}' "
                     f"d='M{x:.1f},12 l6,-8 h-12 z M{x - 1.5:.1f},14 h3 v22 h-3 z'/>")  # fmt: skip
    return _svg(w, h, "".join(parts), f"{label}: {_fmt(value, digits)}{unit}, mål {target}")


def running_rate(series: Sequence[bool], target: Sequence[float] | None, label: str) -> str:
    """Running share (e.g. T wins) over rounds with a target band and the 50 % line."""
    w, h, x0, x1, y0, y1 = 560, 200, 34, 548, 12, 178
    n = len(series)
    if not n:
        return ""
    sx = lambda i: x0 + i / max(n - 1, 1) * (x1 - x0)  # noqa: E731
    sy = lambda v: y1 - v * (y1 - y0)  # noqa: E731
    parts = []
    if target:
        parts.append(f"<rect class='band' x='{x0}' y='{sy(target[1]):.1f}' width='{x1 - x0}' "
                     f"height='{sy(target[0]) - sy(target[1]):.1f}'/>")  # fmt: skip
    for v in (0, 0.25, 0.5, 0.75, 1):
        parts.append(f"<line class='ax' x1='{x0}' y1='{sy(v):.1f}' x2='{x1}' y2='{sy(v):.1f}'/>"
                     f"<text class='lbl small' x='{x0 - 6}' y='{sy(v) + 4:.1f}' text-anchor='end'>{v:.0%}</text>")  # fmt: skip
    wins, pts = 0, []
    for i, won in enumerate(series):
        wins += bool(won)
        pts.append(f"{sx(i):.1f},{sy(wins / (i + 1)):.1f}")
    parts.append(f"<polyline class='line t' points='{' '.join(pts)}'/>")
    for i, won in enumerate(series):
        parts.append(
            f"<rect class='{'t' if won else 'ct'}' x='{sx(i) - 2:.1f}' y='{y1 + 6}' width='4' height='8'/>"
        )
    parts.append(
        f"<text class='lbl small' x='{x1}' y='{y0 + 2}' text-anchor='end'>runde 1 → {n}</text>"
    )
    return _svg(w, h + 8, "".join(parts), label)


def stacked(parts_: Sequence[tuple[str, int, str]], label: str) -> str:
    """One horizontal 100 % bar of (name, count, css class) with a legend underneath."""
    w = 560
    total = sum(c for _, c, _ in parts_) or 1
    x, body, legend_x = 0.0, [], 0
    for _name, count, cls in parts_:
        width = count / total * w
        if width > 0:
            body.append(f"<rect class='{cls}' x='{x:.1f}' y='0' width='{width:.1f}' height='26'/>")
            if width > 34:
                body.append(
                    f"<text class='lbl inbar' x='{x + width / 2:.1f}' y='18' text-anchor='middle'>{count}</text>"
                )
        x += width
    legend_y = 40
    for name, count, cls in parts_:
        text = f"{name} ({count})"
        step = 16 + 6.4 * len(text) + 16
        if legend_x and legend_x + step > w:
            legend_x, legend_y = 0, legend_y + 18
        body.append(f"<rect class='{cls}' x='{legend_x:.0f}' y='{legend_y}' width='11' height='11' rx='2'/>"
                    f"<text class='lbl small' x='{legend_x + 16:.0f}' y='{legend_y + 10}'>{e(text)}</text>")  # fmt: skip
        legend_x += step
    h = legend_y + 18
    return _svg(w, h, "".join(body), label)


def histogram(values: Sequence[float], bins: int, target: Sequence[float] | None, label: str,
              unit: str = "s") -> str:  # fmt: skip
    w, h, x0, x1, y0, y1 = 560, 170, 30, 550, 10, 140
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if target:
        lo, hi = min(lo, target[0]), max(hi, target[1])
    span = (hi - lo) or 1.0
    width = span / bins
    counts = [0] * bins
    for v in vals:
        counts[min(int((v - lo) / width), bins - 1)] += 1
    top = max(counts) or 1
    sx = lambda v: x0 + (v - lo) / span * (x1 - x0)  # noqa: E731
    parts = []
    if target:
        parts.append(f"<rect class='band' x='{sx(target[0]):.1f}' y='{y0}' "
                     f"width='{sx(target[1]) - sx(target[0]):.1f}' height='{y1 - y0}'/>")  # fmt: skip
    bw = (x1 - x0) / bins
    for i, c in enumerate(counts):
        bh = c / top * (y1 - y0)
        parts.append(
            f"<rect class='bar' x='{x0 + i * bw + 1:.1f}' y='{y1 - bh:.1f}' width='{bw - 2:.1f}' height='{bh:.1f}'/>"
        )
    parts.append(f"<line class='ax' x1='{x0}' y1='{y1}' x2='{x1}' y2='{y1}'/>")
    for v in (lo, (lo + hi) / 2, hi):
        parts.append(
            f"<text class='lbl small' x='{sx(v):.1f}' y='{y1 + 16}' text-anchor='middle'>{v:.0f} {unit}</text>"
        )
    parts.append(f"<text class='lbl small' x='{x0}' y='{y0 + 2}'>max {top}</text>")
    return _svg(w, h, "".join(parts), label)


def timings(rows: Sequence[dict], t_range: Sequence[float], min_lead: float) -> str:
    """Spawn -> site run times: T and CT bar per site, the T target band and the CT lead."""
    rows = [r for r in rows if (r.get("T") or {}).get("median_s") is not None
            and (r.get("CT") or {}).get("median_s") is not None]  # fmt: skip
    if not rows:
        return ""
    w, x0, x1 = 560, 60, 520
    hi = max(max(r["T"]["median_s"], r["CT"]["median_s"]) for r in rows)
    hi = max(hi, t_range[1]) * 1.1
    sx = lambda v: x0 + v / hi * (x1 - x0)  # noqa: E731
    h = 30 + 54 * len(rows)
    parts = [
        f"<rect class='band' x='{sx(t_range[0]):.1f}' y='0' width='{sx(t_range[1]) - sx(t_range[0]):.1f}' height='{h - 22}'/>"
    ]
    for i, r in enumerate(rows):
        y = 6 + i * 54
        parts.append(f"<text class='lbl' x='0' y='{y + 26}'>site {e(str(r['site']))}</text>")
        for j, (team, cls) in enumerate((("T", "t"), ("CT", "ct"))):
            v = r[team]["median_s"]
            parts.append(f"<rect class='{cls}' x='{x0}' y='{y + j * 20}' width='{sx(v) - x0:.1f}' height='16' rx='2'/>"
                         f"<text class='lbl small' x='{sx(v) + 6:.1f}' y='{y + j * 20 + 12}'>{team} {v:.1f} s</text>")  # fmt: skip
        lead_ok = r.get("ct_lead_s", 0) >= min_lead
        parts.append(f"<text class='lbl small {'ok' if lead_ok else 'bad'}' x='{x1 + 38}' y='{y + 26}' text-anchor='end'>"
                     f"+{r.get('ct_lead_s', 0):.1f} s</text>")  # fmt: skip
    for v in range(0, int(hi) + 1, 5):
        parts.append(
            f"<text class='lbl small' x='{sx(v):.1f}' y='{h - 6}' text-anchor='middle'>{v}</text>"
        )
    return _svg(
        w, h, "".join(parts), "Løbetid spawn → site (T-målbånd skraveret; CT-forspring til højre)"
    )


def limits(rows: Sequence[dict], warn: float, err: float, top: int = 8) -> str:
    """Engine limit usage (%), highest first, with the warning and error thresholds."""
    rows = sorted(rows, key=lambda r: -r.get("pct", 0))[:top]
    if not rows:
        return ""
    w, x0, x1 = 560, 110, 500
    h = 16 + 22 * len(rows)
    sx = lambda v: x0 + min(v, 100) / 100 * (x1 - x0)  # noqa: E731
    parts = [f"<line class='ax warn' x1='{sx(warn):.1f}' y1='0' x2='{sx(warn):.1f}' y2='{h - 12}'/>",
             f"<line class='ax bad' x1='{sx(err):.1f}' y1='0' x2='{sx(err):.1f}' y2='{h - 12}'/>"]  # fmt: skip
    for i, r in enumerate(rows):
        y, pct = 4 + i * 22, float(r.get("pct", 0))
        cls = "bad" if pct > err else "warn" if pct > warn else "bar"
        parts.append(f"<text class='lbl small' x='0' y='{y + 12}'>{e(r['name'])}</text>"
                     f"<rect class='track' x='{x0}' y='{y}' width='{x1 - x0}' height='15' rx='2'/>"
                     f"<rect class='{cls}' x='{x0}' y='{y}' width='{max(sx(pct) - x0, 1.5):.1f}' height='15' rx='2'/>"
                     f"<text class='lbl small' x='{x1 + 8}' y='{y + 12}'>{pct:.1f} %</text>")  # fmt: skip
    return _svg(
        w, h, "".join(parts), f"Engine-limits, højeste {len(rows)} (gul {warn} %, rød {err} %)"
    )


def trend(
    points: Sequence[tuple[str, float | None]], label: str, lower_is_better: bool = True
) -> str:
    """A value per history version (e.g. score) as a line with dots."""
    pts = [(n, v) for n, v in points if v is not None]
    if len(pts) < 2:
        return ""
    w, h, x0, x1, y0, y1 = 560, 150, 40, 545, 14, 118
    vals = [v for _, v in pts]
    lo, hi = min(0.0, min(vals)), max(vals) * 1.15 or 1.0
    sx = lambda i: x0 + i / (len(pts) - 1) * (x1 - x0)  # noqa: E731
    sy = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
    parts = [f"<line class='ax' x1='{x0}' y1='{y1}' x2='{x1}' y2='{y1}'/>",
             f"<polyline class='line accent' points='{' '.join(f'{sx(i):.1f},{sy(v):.1f}' for i, (_, v) in enumerate(pts))}'/>"]  # fmt: skip
    for i, (name, v) in enumerate(pts):
        parts.append(f"<circle class='dot' cx='{sx(i):.1f}' cy='{sy(v):.1f}' r='4'/>"
                     f"<text class='lbl small' x='{sx(i):.1f}' y='{sy(v) - 9:.1f}' text-anchor='middle'>{v:.2f}</text>"
                     f"<text class='lbl small' x='{sx(i):.1f}' y='{y1 + 18}' text-anchor='middle'>v{e(name)}</text>")  # fmt: skip
    note = "lavere er bedre" if lower_is_better else "højere er bedre"
    parts.append(f"<text class='lbl small' x='{x0}' y='10'>{e(note)}</text>")
    return _svg(w, h, "".join(parts), label)


def ring(pct: float, label: str, cls: str = "accent") -> str:
    """Small progress ring (0-1) with the percentage in the middle (map cards)."""
    import math

    r, c = 22, 2 * math.pi * 22
    off = c * (1 - max(0.0, min(pct, 1.0)))
    return _svg(56, 56, f"<circle class='track-ring' cx='28' cy='28' r='{r}'/>"
                f"<circle class='ring {cls}' cx='28' cy='28' r='{r}' stroke-dasharray='{c:.1f}' "
                f"stroke-dashoffset='{off:.1f}' transform='rotate(-90 28 28)'/>"
                f"<text class='lbl ringtxt' x='28' y='33' text-anchor='middle'>{pct:.0%}</text>", label, "ringsvg")  # fmt: skip
