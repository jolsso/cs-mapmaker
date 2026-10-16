"""The topology page of the local website (graph.html): every own map with a layout.yaml, as
rooms and connections (mapforge.topology), with the design rules recomputed in the browser
(graph.js). Fase 8 → "Graf-laget" in docs/MAPMAKER.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from mapforge.config import Config
from mapforge.topology import extract

HERE = Path(__file__).parent
ASSET_VERSION = hashlib.sha256(
    (HERE / "graph.js").read_bytes() + (HERE / "graph.css").read_bytes()
).hexdigest()[:8]
DEFAULT_MAP = "de_cistern01"


def topologies(cfg: Config, maps: list[str]) -> dict[str, dict[str, Any]]:
    """Topology per own map with a layout.yaml (one that fails to expand is skipped), then the
    reference maps (`tier` A/B) that `./mf refgraphs` wrote."""
    out = {}
    for m in maps:
        src = cfg.path("maps_dir") / m / "layout.yaml"
        if not src.is_file():
            continue
        try:
            out[m] = extract(yaml.safe_load(src.read_text(encoding="utf-8")))
        except Exception:  # the site is a view; one broken layout must not hide the others
            continue
    for f in sorted((cfg.path("build_dir") / "topologies" / "refmap").glob("*.json")):
        if f.stem not in out:  # reference maps from `./mf refgraphs` (BSP walk graph)
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def graph_body(topos: dict[str, dict[str, Any]]) -> str:
    if not topos:
        return ("<section class='panel'><h1>Topologi</h1><p class='muted'>Ingen egne maps med "
                "<code>layout.yaml</code> endnu.</p></section>")  # fmt: skip
    default = DEFAULT_MAP if DEFAULT_MAP in topos else sorted(topos)[0]
    data = json.dumps(
        {"default": default, "maps": topos}, ensure_ascii=False, separators=(",", ":")
    )
    data = data.replace("</", "<\\/")
    routes = "".join(
        f"<button type='button' data-g-route='{r}'>{t}</button>"
        for r, t in (("T>A", "T til A"), ("T>B", "T til B"), ("CT>A", "CT til A"),
                     ("CT>B", "CT til B"), ("A>B", "Rotation"))
    )  # fmt: skip
    return f"""
<link rel='stylesheet' href='graph.css?v={ASSET_VERSION}'>
<section class='panel g-intro'>
  <div><span class='eyebrow'>Fase 8 · graf-laget</span><h1>Hvad grafen ved om et map</h1>
    <p class='muted small' id='g-concept'></p></div>
  <div><p class='muted'>Et map kogt ned til <b>rum og forbindelser</b>: den form, mapmakeren søger, lærer og regner på,
    før der findes geometri. Tryk på et rum eller en forbindelse for at se det som <code>topology.yaml</code>;
    fjern en forbindelse og se reglerne reagere.</p>
    <div class='g-pick' style='margin-top:10px'><label for='g-map' class='muted small'>Map</label><select id='g-map'></select>
    <span class='muted small' id='g-count'></span></div></div>
</section>
<div class='g-controls'>
  <div class='grp'><span>Vis som</span><button type='button' data-g-view='rooms'>Rum</button><button type='button' data-g-view='both'>Begge</button><button type='button' data-g-view='graph'>Graf</button></div>
  <div class='grp'><span>Niveau</span><span id='g-levels' class='grp'></span></div>
  <div class='grp'><span>Korteste vej</span>{routes}</div>
</div>
<div class='g-stage'>
  <div class='g-board' id='g-board' data-view='graph'><svg id='g-svg' role='img' aria-label='Topologien for det valgte map'></svg></div>
  <div class='g-side'>
    <div id='g-inspector' aria-live='polite'></div>
    <div><h3>Regler, beregnet på grafen</h3><ul class='g-rules' id='g-rules'></ul>
      <p class='muted small' style='margin:10px 0 0'>Graf-niveau-evaluatorens estimat ved 250 units/s (dør til dør i lige linjer).
      Kalibreres mod walk-grafen fra BSP'en (fase 8b).</p></div>
  </div>
</div>
<section class='panel'>
  <div class='g-cols'>
    <div><h2>Noder: rum med en rolle</h2><p class='muted small'>Rum, der rører hinanden uden væg imellem, er ét rum
      (samme regel som <code>layout_graph()</code>). En bro er sit eget niveau.</p><ul class='g-dict' id='g-roles'></ul></div>
    <div><h2>Kanter: hvordan man kommer videre</h2><p class='muted small'>Typen afgør, om man kan gå den, hvilken vej,
      og hvad den koster i tid. Et vindue er en sigtelinje, ikke en indgang.</p><ul class='g-dict' id='g-kinds'></ul></div>
    <div><h2>Egenskaber</h2><dl class='g-props'>
      <dt>level</dt><dd>Niveau ud fra gulvhøjden (192 units pr. niveau). Hvert niveau skal kunne tegnes uden krydsende forbindelser.</dd>
      <dt>size</dt><dd>S, M, L eller XL ud fra gulvarealet.</dd>
      <dt>length</dt><dd>Rutelængde i units, rummets midte → døren → næste rums midte. Det, Fit sigter efter.</dd>
      <dt>width</dt><dd>narrow, normal eller wide.</dd>
      <dt>choke</dt><dd>Navnet fra layoutets <code>chokes:</code>, når forbindelsen er et bevidst chokepoint.</dd>
      <dt>oneway</dt><dd>Kun for fald.</dd>
      <dt>pos</dt><dd>Grov placering, når grafen kommer fra en skitse eller et layout.</dd></dl></div>
    <div><h2>Hvad grafen ikke ved</h2><p class='muted'>Vægge, cover, lys, teksturer og præcise sigtelinjer. Den ved, at der er
      en dør ind på B, ikke hvor kassen står bag døren. Derfor kan tusindvis af varianter vurderes på sekunder, og kun de
      bedste får geometri, compile og walk-graf.</p></div>
  </div>
</section>
<section class='panel'><h2>Hvor grafen sidder i pipelinen</h2>
  <ol class='g-flow'>
    <li>Skitse eller brief<div class='muted small'>Du tegner, eller agenter tegner kandidater.</div></li>
    <li class='here'>Topologi<div class='muted small'>Denne side: rum, forbindelser, regler.</div></li>
    <li>Fit<div class='muted small'>Graf og skitse bliver til <code>layout.yaml</code>.</div></li>
    <li>Compile og walk<div class='muted small'>BSP, rigtige timings, render og review.</div></li>
    <li>Bots og loop<div class='muted small'>Diagnostik og små rettelser.</div></li>
  </ol>
  <p class='muted small'>Spec: <code>docs/MAPMAKER.md</code> (Graf-laget) og <code>docs/GRAPH_TRAINING.md</code>.
  Udtræk: <code>mapforge/topology.py</code> (<code>python -m mapforge.topology --map &lt;navn&gt;</code> skriver <code>build/&lt;map&gt;/topology.yaml</code>).</p>
</section>
<script type='application/json' id='graph-data'>{data}</script>
<script src='graph.js?v={ASSET_VERSION}'></script>
"""
