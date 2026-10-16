// MapForge: the topology page (graph.html). Shows a map's topology (mapforge.topology) as rooms
// and connections, lets the human inspect nodes/edges as topology.yaml, try the remove_edge
// operator and watch the design rules (DESIGN_GUIDE §2/§9) recomputed on the graph.
// Data: <script type="application/json" id="graph-data"> {maps: {name: topology}}. No libraries.
"use strict";
(() => {
  const DATA = JSON.parse(document.getElementById("graph-data").textContent);
  const NS = "http://www.w3.org/2000/svg";
  const SPEED = 250;
  const ZONE = {t: "var(--t)", ct: "var(--ct)", a: "var(--g-a)", b: "var(--g-b)", mid: "var(--g-mid)"};
  const ROLE_DA = {t_spawn: "T-spawn", ct_spawn: "CT-spawn", site: "Bombesite", mid: "Mid", corridor: "Korridor", room: "Rum", choke: "Chokepoint", connector: "Forbindelsesrum"};
  const KIND_DA = {door: "Dør", ramp: "Rampe", stairs: "Trappe", hatch: "Lem med stige", ladder: "Stige", vent: "Vent", drop: "Fald", window: "Vindue"};
  const LEVEL_DA = {"-2": "Dyb kælder", "-1": "Kælder", "0": "Gade", "1": "Over gaden", "2": "Højt oppe"};
  const R = {S: 72, M: 96, L: 124, XL: 150};
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const fmt = (v, d = 1) => v.toLocaleString("da-DK", {minimumFractionDigits: d, maximumFractionDigits: d});
  const el = (tag, attrs = {}, parent) => { const x = document.createElementNS(NS, tag); for (const k in attrs) x.setAttribute(k, attrs[k]); if (parent) parent.appendChild(x); return x; };
  const $ = id => document.getElementById(id);
  const sx = p => p[0], sy = p => -p[1];

  const names = Object.keys(DATA.maps);
  let T, N, E;
  const state = {map: null, removed: [], sel: null, route: null, view: "graph", level: "all"};

  /* ---------- graph logic ---------- */
  const active = () => T.edges.filter(e => !state.removed.includes(e.id));
  const walkable = () => active().filter(e => e.kind !== "window");
  const siteNode = k => (T.nodes.find(n => n.site === k) || {}).id;
  function neighbours() {
    const nb = new Map(T.nodes.map(n => [n.id, new Set()]));
    for (const e of walkable()) { nb.get(e.a).add(e.b); nb.get(e.b).add(e.a); }
    return nb;
  }
  function doorGraph() {
    const adj = new Map(), room = new Map();
    const d = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
    const add = (u, v, w) => { if (!adj.has(u)) adj.set(u, []); if (!adj.has(v)) adj.set(v, []); adj.get(u).push([v, w]); adj.get(v).push([u, w]); };
    for (const e of walkable()) for (const r of [e.a, e.b]) { if (!room.has(r)) room.set(r, []); room.get(r).push(e); }
    for (const [, ds] of room) for (let i = 0; i < ds.length; i++) for (let j = i + 1; j < ds.length; j++)
      add(ds[i].id, ds[j].id, d(ds[i]._p, ds[j]._p) + ((ds[i].kind === "hatch" || ds[j].kind === "hatch") ? 64 : 0));
    const pts = {};
    for (const team of ["T", "CT"]) if (T._spawns[team]) pts[team] = [T._spawns[team].node, T._spawns[team].at];
    for (const k of ["A", "B"]) { const s = siteNode(k); if (s) pts[k] = [s, N.get(s)._c]; }
    for (const k in pts) { const [r, p] = pts[k]; if (!adj.has(k)) adj.set(k, []); for (const e of room.get(r) || []) add(k, e.id, d(p, e._p)); }
    return {adj, pts};
  }
  function shortest(from, to) {
    const {adj, pts} = doorGraph();
    if (!pts[from] || !pts[to]) return null;
    const dist = new Map([[from, 0]]), prev = new Map(), done = new Set();
    for (;;) {
      let u = null, best = Infinity;
      for (const [k, v] of dist) if (!done.has(k) && v < best) { best = v; u = k; }
      if (u === null || u === to) break;
      done.add(u);
      for (const [v, w] of adj.get(u) || []) if (best + w < (dist.get(v) ?? Infinity)) { dist.set(v, best + w); prev.set(v, u); }
    }
    if (!dist.has(to)) return null;
    const seq = []; let c = to; while (c !== undefined) { seq.unshift(c); c = prev.get(c); }
    return {sec: dist.get(to) / SPEED, path: seq.map(k => pts[k] ? pts[k][1] : E.get(k)._p)};
  }
  function reachable(start) {
    const nb = neighbours(), seen = new Set([start]), q = [start];
    while (q.length) { const u = q.shift(); for (const v of nb.get(u)) if (!seen.has(v)) { seen.add(v); q.push(v); } }
    return seen;
  }
  function entrances(site) { const nb = neighbours(); return [...nb.get(site)].filter(v => nb.get(v).size > 1).length; }
  function rules() {
    const out = [], nb = neighbours(), count = r => T.nodes.filter(n => n.role === r).length;
    const A = siteNode("A"), B = siteNode("B"), tId = (T._spawns.T || {}).node, ctId = (T._spawns.CT || {}).node;
    out.push({ok: count("t_spawn") === 1 && count("ct_spawn") === 1 && count("site") === 2 ? "ok" : "bad", t: "Én T-spawn, én CT-spawn, to sites"});
    if (!tId || !ctId || !A || !B) return out;
    const all = reachable(tId);
    out.push({ok: all.size === T.nodes.length ? "ok" : "bad", t: "Alle rum hænger sammen", v: all.size === T.nodes.length ? "" : `${T.nodes.length - all.size} afskåret`});
    const rt = reachable(tId), rc = reachable(ctId);
    out.push({ok: [A, B].every(s => rt.has(s) && rc.has(s)) ? "ok" : "bad", t: "Begge sites nås fra begge spawns"});
    const direct = walkable().some(e => { const r = [N.get(e.a).role, N.get(e.b).role]; return r.includes("site") && (r.includes("t_spawn") || r.includes("ct_spawn")); });
    out.push({ok: direct ? "bad" : "ok", t: "Ingen dør direkte fra spawn til site"});
    for (const [k, s] of [["A", A], ["B", B]]) { const n = entrances(s); out.push({ok: n >= 2 && n <= 3 ? "ok" : "bad", t: `2–3 indgange til ${k}`, v: `${n}`}); }
    const ctSide = new Set([ctId, ...nb.get(ctId)]);
    for (const [k, s] of [["A", A], ["B", B]]) out.push({ok: [...nb.get(s)].some(v => ctSide.has(v)) ? "ok" : "bad", t: `CT har en retake-vej til ${k}`});
    const four = T.nodes.filter(n => !["site", "t_spawn", "ct_spawn"].includes(n.role) && nb.get(n.id).size >= 4).map(n => n.id);
    out.push({ok: four.length ? "bad" : "ok", t: "Ingen 4-vejskryds", v: four.join(", ")});
    for (const k of ["A", "B"]) {
      const t = shortest("T", k), c = shortest("CT", k);
      if (!t) { out.push({ok: "bad", t: `T når ${k}`, v: "ingen vej"}); continue; }
      out.push({ok: t.sec >= 14 && t.sec <= 26 ? "ok" : "warn", t: `T til ${k}, mål 14–26 s`, v: `${fmt(t.sec)} s`});
      if (!c) { out.push({ok: "bad", t: `CT når ${k}`, v: "ingen vej"}); continue; }
      const m = t.sec - c.sec;
      out.push({ok: m >= 3 ? "ok" : "bad", t: `CT mindst 3 s før T på ${k}`, v: `${m >= 0 ? "" : "−"}${fmt(Math.abs(m))} s før`});
    }
    const rot = shortest("A", "B");
    out.push(rot ? {ok: rot.sec <= 15 ? "ok" : rot.sec <= 20 ? "warn" : "bad", t: "Rotation A til B, mål 10–15 s", v: `${fmt(rot.sec)} s`} : {ok: "bad", t: "Rotation A til B", v: "ingen vej"});
    return out;
  }

  /* ---------- drawing ---------- */
  const svg = $("g-svg"), board = $("g-board");
  const L = {};
  const lvOf = e => { const a = N.get(e.a).level, b = N.get(e.b).level; return a === b ? `${a}` : `${a} ${b}`; };
  const pathD = pts => pts.map((p, i) => `${i ? "L" : "M"}${sx(p)} ${sy(p)}`).join("");

  function bounds() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const take = p => { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]); };
    for (const n of T.nodes) { take(n._c); for (const m of n._members) m.shape.forEach(take); }
    const pad = 260;
    return [x0 - pad, -(y1 + pad), (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad];
  }
  function build() {
    svg.replaceChildren();
    const [vx, vy, vw, vh] = bounds();
    svg.setAttribute("viewBox", `${vx} ${vy} ${vw} ${vh}`);
    const defs = el("defs", {}, svg);
    const pm = el("pattern", {id: "g-gmin", width: 128, height: 128, patternUnits: "userSpaceOnUse"}, defs);
    el("path", {d: "M128 0H0V128", class: "g-gridminor"}, pm);
    const pM = el("pattern", {id: "g-gmaj", width: 512, height: 512, patternUnits: "userSpaceOnUse"}, defs);
    el("rect", {width: 512, height: 512, fill: "url(#g-gmin)"}, pM);
    el("path", {d: "M512 0H0V512", class: "g-gridmajor"}, pM);
    el("rect", {x: vx, y: vy, width: vw, height: vh, fill: "url(#g-gmaj)"}, svg);
    const north = el("text", {x: vx + vw - 60, y: vy + 110, class: "g-north", "text-anchor": "end"}, svg); north.textContent = "N ↑";
    for (const k of ["rooms", "doors"]) L[k] = el("g", {class: `g-${k}`}, svg);
    L.g = el("g", {class: "g-layer"}, svg);
    for (const k of ["route", "sel", "edges", "marks", "hits", "nodes"]) L[k] = el("g", {}, L.g);
    L.labels = el("g", {}, svg);

    for (const n of T.nodes) for (const m of n._members) {
      const shape = el("polygon", {points: m.shape.map(p => `${sx(p)},${sy(p)}`).join(" "), class: `g-room${m.outdoor ? " out" : ""}${n.level < 0 ? " below" : ""}`, "data-lv": n.level}, L.rooms);
      shape.style.setProperty("--zone", ZONE[n._zone] || "var(--line2)");
    }
    for (const e of T.edges) {
      el("circle", {cx: sx(e._p), cy: sy(e._p), r: 26, class: "g-doorpt", "data-lv": lvOf(e)}, L.doors);
      const a = N.get(e.a)._c, b = N.get(e.b)._c;
      const d = `M${sx(a)} ${sy(a)}L${sx(e._p)} ${sy(e._p)}L${sx(b)} ${sy(b)}`;
      e._line = el("path", {d, class: `g-edge ${e.kind}`, "data-lv": lvOf(e)}, L.edges);
      const [x, y] = [sx(e._p), sy(e._p)];
      if (e.choke) el("path", {d: `M${x} ${y - 50}L${x + 50} ${y}L${x} ${y + 50}L${x - 50} ${y}Z`, class: "g-choke", "data-lv": lvOf(e)}, L.marks);
      if (e.kind === "hatch") el("circle", {cx: x, cy: y, r: 44, class: "g-hatch", "data-lv": lvOf(e)}, L.marks);
      const hit = el("path", {d, class: "g-hit", "data-lv": lvOf(e), tabindex: 0, role: "button", "aria-label": `${KIND_DA[e.kind] || e.kind} ${e.id} mellem ${e.a} og ${e.b}`}, L.hits);
      hit.addEventListener("click", () => select("edge", e.id));
      hit.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select("edge", e.id); } });
    }
    for (const n of T.nodes) {
      const [x, y] = [sx(n._c), sy(n._c)], r = R[n.size] || 96;
      const g = el("g", {class: `g-node r-${n.role}${n.site ? " s-" + n.site : ""}${n.level < 0 ? " below" : ""}`, tabindex: 0, role: "button", "data-lv": n.level, "aria-label": `${ROLE_DA[n.role] || n.role} ${n.id}, niveau ${n.level}, størrelse ${n.size}`}, L.nodes);
      el("circle", {cx: x, cy: y, r: Math.max(r + 60, 170), fill: "transparent"}, g);
      el("circle", {cx: x, cy: y, r: r + 30, class: "g-ring"}, g);
      el("circle", {cx: x, cy: y, r, class: "g-body"}, g);
      const glyph = n.site || (n.role === "t_spawn" ? "T" : n.role === "ct_spawn" ? "CT" : "");
      if (glyph) { const t = el("text", {x, y: y + 42, class: "g-glyph", "text-anchor": "middle"}, g); t.textContent = glyph; if (glyph === "CT") t.setAttribute("font-size", "88"); }
      if (n.level !== 0) { const b = el("text", {x: x + r * .78, y: y - r * .78, class: "g-lvbadge"}, g); b.textContent = n.level < 0 ? `−${-n.level}` : `+${n.level}`; }
      g.addEventListener("click", () => select("node", n.id));
      g.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select("node", n.id); } });
      n._g = g;
      const lt = el("text", {x, y: y + r + 96, class: "g-lbl", "text-anchor": "middle", "data-lv": n.level}, L.labels);
      lt.textContent = n.id;
    }
  }

  function draw() {
    board.dataset.view = state.view;
    for (const e of T.edges) e._line.classList.toggle("removed", state.removed.includes(e.id));
    L.sel.replaceChildren(); L.route.replaceChildren();
    for (const n of T.nodes) n._g.classList.toggle("sel", state.sel?.type === "node" && state.sel.id === n.id);
    if (state.sel?.type === "edge") el("path", {d: E.get(state.sel.id)._line.getAttribute("d"), class: "g-selband"}, L.sel);
    if (state.route) { const [f, t] = state.route.split(">"); const r = shortest(f, t); if (r) el("path", {d: pathD(r.path), class: "g-routeband"}, L.route); }
    for (const x of svg.querySelectorAll("[data-lv]")) x.classList.toggle("dim", state.level !== "all" && !String(x.dataset.lv).split(" ").includes(state.level));
    document.querySelectorAll("[data-g-view]").forEach(b => b.classList.toggle("on", b.dataset.gView === state.view));
    document.querySelectorAll("[data-g-level]").forEach(b => b.classList.toggle("on", b.dataset.gLevel === state.level));
    document.querySelectorAll("[data-g-route]").forEach(b => b.classList.toggle("on", b.dataset.gRoute === state.route));
    inspector(); renderRules();
  }

  /* ---------- panels ---------- */
  const yaml = rows => rows.map((r, i) => `${i ? "  " : "- "}<span class="g-k">${r[0]}:</span> ${esc(r[1])}`).join("\n");
  function inspector() {
    const box = $("g-inspector"), nb = neighbours();
    let html = "";
    if (state.sel?.type === "node") {
      const n = N.get(state.sel.id);
      const rows = [["id", n.id], ["role", n.role]];
      if (n.site) rows.push(["site", n.site]);
      rows.push(["level", n.level], ["size", n.size]);
      const facts = [["Niveau", `${LEVEL_DA[n.level] || ""} (${n.level})`], ["Forbindelser", `${nb.get(n.id).size}`]];
      const parts = [...new Set(n._members.map(m => m.name))];
      if (parts.length > 1) facts.push(["Lagt sammen af", parts.join(", ")]);
      if (n._deck) facts.push(["Bro", "eget niveau over rummet under den"]);
      if (n.role === "site") {
        facts.push(["Indgange", `${entrances(n.id)}`]);
        const t = shortest("T", n.site), c = shortest("CT", n.site);
        facts.push(["T når hertil", t ? `${fmt(t.sec)} s` : "ingen vej"], ["CT når hertil", c ? `${fmt(c.sec)} s` : "ingen vej"]);
      }
      html = `<div class="g-kind">Node: ${esc(ROLE_DA[n.role] || n.role)}</div><h3>${esc(n.id)}</h3><pre class="g-yaml">${yaml(rows)}</pre>
        <dl class="g-facts">${facts.map(f => `<dt>${f[0]}</dt><dd>${esc(f[1])}</dd>`).join("")}</dl>`;
    } else if (state.sel?.type === "edge") {
      const e = E.get(state.sel.id), gone = state.removed.includes(e.id);
      const rows = [["a", e.a], ["b", e.b], ["kind", e.kind]];
      if (e.length !== undefined) rows.push(["length", e.length]);
      rows.push(["width", e.width]);
      if (e.choke) rows.push(["choke", e.choke]);
      const facts = [["Mellem", `${e.a} og ${e.b}`], ["Bredde", `${e._w} units`]];
      facts.push(e.kind === "window" ? ["Gangbar", "nej, kun en sigtelinje"] : ["Tid", `ca. ${fmt(e.length / SPEED)} s ved 250 u/s`]);
      if (e._gate) facts.push(["Dørblad", e._gate]);
      html = `<div class="g-kind">Kant: ${esc(KIND_DA[e.kind] || e.kind)}${gone ? " (fjernet)" : ""}</div><h3>${esc(e.id)}</h3><pre class="g-yaml">${yaml(rows)}</pre>
        <dl class="g-facts">${facts.map(f => `<dt>${f[0]}</dt><dd>${esc(f[1])}</dd>`).join("")}</dl>
        <div class="g-actions"><button type="button" class="primary" id="g-toggle">${gone ? "Sæt forbindelsen tilbage" : "Fjern forbindelsen"}</button></div>`;
    }
    if (state.removed.length) html += `<div class="g-oplog">${state.removed.map(id => `remove_edge(${esc(id)})`).join("<br>")}</div>
      <div class="g-actions"><button type="button" id="g-reset">Nulstil grafen</button></div>`;
    else if (state.sel?.type !== "edge") html += `<p class="muted small">Vælg en forbindelse for at prøve operatoren <code>remove_edge</code>.</p>`;
    box.innerHTML = html;
    $("g-toggle")?.addEventListener("click", () => { const id = state.sel.id; state.removed = state.removed.includes(id) ? state.removed.filter(x => x !== id) : [...state.removed, id]; draw(); });
    $("g-reset")?.addEventListener("click", () => { state.removed = []; draw(); });
  }
  function renderRules() {
    const ICON = {ok: "✓", warn: "!", bad: "✕"}, WORD = {ok: "opfyldt", warn: "advarsel", bad: "brudt"};
    $("g-rules").innerHTML = rules().map(r => `<li class="${r.ok}"><span class="g-st ${r.ok}" aria-label="${WORD[r.ok]}">${ICON[r.ok]}</span><span>${esc(r.t)}</span><span class="g-v">${esc(r.v || "")}</span></li>`).join("");
  }
  function select(type, id) { state.sel = {type, id}; draw(); }

  /* ---------- dictionary ---------- */
  const gNode = (fill, dashed) => `<svg width="56" height="40" viewBox="0 0 56 40" aria-hidden="true"><circle cx="28" cy="20" r="14" fill="${fill}" stroke="var(--ink)" stroke-width="2.5" ${dashed ? 'stroke-dasharray="6 3"' : ""}/></svg>`;
  function gEdge(kind) {
    const base = 'stroke="var(--ink)" stroke-width="3.5" fill="none" stroke-linecap="round"';
    const pat = {door: base, ramp: base + ' stroke-dasharray="12 5"', stairs: 'stroke="var(--ink)" stroke-width="6" stroke-dasharray="3 3" fill="none"', hatch: base, ladder: base, vent: base, drop: base, window: 'stroke="var(--muted)" stroke-width="3" stroke-dasharray="1 6" stroke-linecap="round" fill="none"'}[kind];
    const extra = {
      hatch: '<circle cx="28" cy="20" r="6" fill="var(--panel)" stroke="var(--ink)" stroke-width="2.5"/>',
      drop: '<path d="M38 13L46 20L38 27" stroke="var(--ink)" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
      ladder: '<path d="M22 14V26M34 14V26" stroke="var(--ink)" stroke-width="2.5"/>',
      vent: '<rect x="21" y="15" width="14" height="10" fill="var(--panel)" stroke="var(--ink)" stroke-width="2"/>',
    }[kind] || "";
    return `<svg width="56" height="40" viewBox="0 0 56 40" aria-hidden="true"><path d="M6 20H50" ${pat}/>${extra}</svg>`;
  }
  function dictionary() {
    const count = r => T.nodes.filter(n => n.role === r).length;
    const roles = [
      ["t_spawn", "Hvor T starter.", gNode("var(--t)")],
      ["ct_spawn", "Hvor CT starter.", gNode("var(--ct)")],
      ["site", "Bombesite A eller B. Altid præcis to.", `<svg width="56" height="40" viewBox="0 0 56 40" aria-hidden="true"><circle cx="17" cy="20" r="13" fill="var(--g-a)" stroke="var(--ink)" stroke-width="2.5"/><circle cx="40" cy="20" r="13" fill="var(--g-b)" stroke="var(--ink)" stroke-width="2.5"/></svg>`],
      ["mid", "Midten, hvor ruterne mødes og der skal træffes valg.", gNode("var(--g-mid)")],
      ["corridor", "En rute mellem to steder.", gNode("var(--panel2)")],
      ["room", "Et rum, man går ind i: en hal, et kontor.", gNode("var(--panel2)")],
      ["choke", "Et bevidst flaskehals-rum. Fra et layout sidder chokes på dørene, vist med en rombe.", `<svg width="56" height="40" viewBox="0 0 56 40" aria-hidden="true"><path d="M6 20H50" stroke="var(--ink)" stroke-width="3.5"/><path d="M28 11L37 20L28 29L19 20Z" fill="var(--ink)" stroke="var(--panel)" stroke-width="2"/></svg>`],
    ];
    $("g-roles").innerHTML = roles.map(([r, d, g]) => {
      const shown = r === "choke" ? T.edges.filter(e => e.choke).length : count(r);
      return `<li class="${shown ? "" : "absent"}">${g}<span><b>${ROLE_DA[r]}</b> <code>${r}</code><span class="g-desc">${d}</span></span><span class="g-count">${r === "choke" ? shown + " døre" : shown + " her"}</span></li>`;
    }).join("") + `<li>${gNode("var(--panel2)", true)}<span><b>Stiplet omrids</b><span class="g-desc">Rummet ligger under gaden (niveau under 0).</span></span><span class="g-count">${T.nodes.filter(n => n.level < 0).length} her</span></li>`;
    const kinds = [["door", "Gå igennem i samme højde."], ["ramp", "Gå op eller ned ad en skrå flade."], ["stairs", "Som en rampe, men med trin."], ["hatch", "Hul i gulvet med en stige mellem to etager."], ["ladder", "Stige uden lem, fx op på en platform."], ["vent", "Smal skakt, man skal dukke sig gennem."], ["drop", "Fald. Kun den ene vej, og ofte den hurtigste."], ["window", "Kan ses igennem, ikke gås igennem. Tæller ikke som indgang."]];
    $("g-kinds").innerHTML = kinds.map(([k, d]) => {
      const c = T.edges.filter(e => e.kind === k).length;
      return `<li class="${c ? "" : "absent"}">${gEdge(k)}<span><b>${KIND_DA[k]}</b> <code>${k}</code><span class="g-desc">${d}</span></span><span class="g-count">${c ? c + " her" : "ikke i dette map"}</span></li>`;
    }).join("");
  }

  /* ---------- map switching ---------- */
  function levelChips() {
    const levels = [...new Set(T.nodes.map(n => n.level))].sort((a, b) => b - a);
    $("g-levels").innerHTML = `<button type="button" data-g-level="all">Alle</button>` + levels.map(l => `<button type="button" data-g-level="${l}">${LEVEL_DA[l] || l} (${l < 0 ? "−" + (-l) : l})</button>`).join("");
    document.querySelectorAll("[data-g-level]").forEach(b => b.addEventListener("click", () => { state.level = b.dataset.gLevel; draw(); }));
  }
  function load(name, animate) {
    T = DATA.maps[name];
    N = new Map(T.nodes.map(n => [n.id, n]));
    E = new Map(T.edges.map(e => [e.id, e]));
    Object.assign(state, {map: name, removed: [], route: null, level: "all"});
    const site = T.nodes.find(n => n.site === "B") || T.nodes[0];
    state.sel = {type: "node", id: site.id};
    $("g-map").value = name;
    $("g-concept").textContent = T._concept || (T.source === "bsp" ? "Udtrukket fra BSP'en (walk-graf, rum mellem indsnævringer) – ikke mapperens egne rum." : "");
    $("g-count").textContent = `${T.nodes.length} rum og ${T.edges.length} forbindelser`;
    build(); dictionary(); levelChips();
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (animate && !reduce) { state.view = "rooms"; draw(); setTimeout(() => { state.view = "graph"; draw(); }, 900); }
    else draw();
  }

  const GROUPS = [[undefined, "Egne maps"], ["A", "Officielle (tier A)"], ["B", "Community (tier B)"]];
  $("g-map").innerHTML = GROUPS.map(([t, label]) => {
    const ns = names.filter(n => DATA.maps[n].tier === t);
    return ns.length ? `<optgroup label="${label}">${ns.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join("")}</optgroup>` : "";
  }).join("");
  $("g-map").addEventListener("change", ev => { history.replaceState(null, "", "#" + ev.target.value); load(ev.target.value, true); });
  document.querySelectorAll("[data-g-view]").forEach(b => b.addEventListener("click", () => { state.view = b.dataset.gView; draw(); }));
  document.querySelectorAll("[data-g-route]").forEach(b => b.addEventListener("click", () => {
    state.route = state.route === b.dataset.gRoute ? null : b.dataset.gRoute;
    if (state.route && state.view === "rooms") state.view = "both";
    draw();
  }));
  const fromHash = decodeURIComponent(location.hash.slice(1));
  load(names.includes(fromHash) ? fromHash : DATA.default, true);
})();
