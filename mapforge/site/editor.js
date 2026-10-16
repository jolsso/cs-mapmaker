// MapForge: the graph editor (editor.html; spec docs/superpowers/specs/2026-10-16-graph-editor-design.md).
// Draw a map as spawns, sites, rooms and connections; live design checks, closest reference maps
// and suggestions. Modes (URL hash): #new/<map> (graph.json: autosave, approve) and
// #change/<map> (the map's current graph; "Send as change" = a wish for the next iteration).
// Board: 640 px = 6144 units; graph.json keeps world units. No libraries.
"use strict";
let REFS = {}, REF_FEAT = {}, REF_SIG = {};   // reference graphs: refgraphs.json (site build)
const U = 9.6, SPEED = 250, DETOUR = 1.3;          // units per board pixel; walk speed; corridor detour
const NS = "http://www.w3.org/2000/svg";
const svg = document.getElementById("ed-svg");
let prevM = null, lastM = null;
let G = {nodes: [], edges: []}, tool = "select", pick = null, sel = null, drag = null, hist = [], rejected = new Set(), seq = 1;
const COLOR = {T: "var(--t)", CT: "var(--ct)", A: "var(--a)", B: "var(--b)", room: "#555"};
const el = (t, a, p) => { const x = document.createElementNS(NS, t); for (const k in a) x.setAttribute(k, a[k]); if (p) p.appendChild(x); return x; };
const save = () => { hist.push(JSON.stringify(G)); if (hist.length > 100) hist.shift(); };
const byId = id => G.nodes.find(n => n.id === id);
function freeId(base) {   // an id no node has yet: "t", "ct", "a", "b", or "r<n>" for rooms
  if (base !== "r" && !byId(base)) return base;
  while (byId(base + seq)) seq++;
  return base + seq++;
}
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y) * U;

/* ---------- graph maths ---------- */
function edgeLen(g, e) {
  const a = g.nodes.find(n => n.id === e.a), b = g.nodes.find(n => n.id === e.b);
  if (e.len) return e.len;                                   // a length set in the inspector
  const climb = e.kind === "ladder" ? 2 : 1;                  // a ladder is slower than walking
  return dist(a, b) * DETOUR + (a.level !== b.level ? 96 * climb : 0);
}
function adj(g) {
  const m = new Map(g.nodes.map(n => [n.id, []]));
  for (const e of g.edges) { const w = edgeLen(g, e); m.get(e.a).push([e.b, w]); if (e.kind !== "drop") m.get(e.b).push([e.a, w]); }
  return m;
}
function sp(g, from, to, avoid = []) {
  if (!from || !to) return Infinity;
  const m = adj(g), d = new Map([[from, 0]]), done = new Set();
  while (true) {
    let u = null, best = Infinity;
    for (const [k, v] of d) if (!done.has(k) && v < best) { best = v; u = k; }
    if (u === null) return Infinity;
    if (u === to) return best;
    done.add(u);
    for (const [v, w] of m.get(u) || []) if (!avoid.includes(v) || v === to) if (best + w < (d.get(v) ?? Infinity)) d.set(v, best + w);
  }
}
const role = n => n.role;
function nbrs(g) { const m = new Map(g.nodes.map(n => [n.id, new Set()])); for (const e of g.edges) { m.get(e.a).add(e.b); m.get(e.b).add(e.a); } return m; }
function metrics(g) {
  const id = r => (g.nodes.find(n => n.role === r) || {}).id;
  const T = id("T"), CT = id("CT"), A = id("A"), B = id("B");
  const s = x => x / SPEED, nb = nbrs(g), out = {};
  out.tA = s(sp(g, T, A)); out.tB = s(sp(g, T, B)); out.cA = s(sp(g, CT, A)); out.cB = s(sp(g, CT, B));
  out.rot = s(Math.min(sp(g, A, B), sp(g, B, A)));
  const ent = x => x ? [...nb.get(x)].filter(y => nb.get(y).size > 1).length : 0;
  out.eA = ent(A); out.eB = ent(B);
  const ctSide = new Set(CT ? [CT, ...nb.get(CT)] : []);
  out.retakeA = A ? [...nb.get(A)].some(y => ctSide.has(y)) : false;
  out.retakeB = B ? [...nb.get(B)].some(y => ctSide.has(y)) : false;
  out.four = g.nodes.filter(n => n.role === "room" && nb.get(n.id).size >= 4).map(n => n.id);
  // a spawn joined to a site by less than ~2 s of corridor is as good as a door between them
  out.direct = g.edges.filter(e => { const r = [byIdIn(g, e.a).role, byIdIn(g, e.b).role]; return (r.includes("T") || r.includes("CT")) && (r.includes("A") || r.includes("B")) && edgeLen(g, e) < 512; }).length;
  out.chokes = g.edges.filter(e => e.kind === "choke").length;
  out.has = {T, CT, A, B};
  return out;
}
const byIdIn = (g, id) => g.nodes.find(n => n.id === id);
// one penalty number: how far outside the design bands (DESIGN_GUIDE §2/§9)
function penalty(m) {
  const band = (v, lo, hi) => !isFinite(v) ? 30 : v < lo ? lo - v : v > hi ? v - hi : 0;
  return band(m.tA, 14, 26) + band(m.tB, 14, 26) + band(m.tA - m.cA, 3, 99) + band(m.tB - m.cB, 3, 99)
    + band(m.rot, 10, 15) + 3 * band(m.eA, 2, 3) + 3 * band(m.eB, 2, 3) + 4 * m.four.length + 5 * m.direct
    + (m.retakeA ? 0 : 3) + (m.retakeB ? 0 : 3);
}

/* ---------- similarity to reference maps (Weisfeiler-Lehman subtree features, cosine) ---------- */
// skeleton: drop plain dead ends, merge plain corridor chains (degree 2), so a 7-node sketch
// and a 30-room extracted map compare on structure, not on how finely rooms were cut
function skeleton(nodes, edges, special) {
  const nb = new Map(nodes.map(n => [n[0], new Set()]));
  for (const [a, b] of edges) if (nb.has(a) && nb.has(b) && a !== b) { nb.get(a).add(b); nb.get(b).add(a); }
  const sp = new Set(nodes.filter(special).map(n => n[0]));
  let changed = true;
  while (changed) {
    changed = false;
    for (const [k, s] of nb) {
      if (sp.has(k)) continue;
      if (s.size <= 1) { for (const x of s) nb.get(x).delete(k); nb.delete(k); changed = true; }
      else if (s.size === 2) { const [x, y] = [...s]; nb.get(x).delete(k); nb.get(y).delete(k); nb.get(x).add(y); nb.get(y).add(x); nb.delete(k); changed = true; }
    }
  }
  const keep = nodes.filter(n => nb.has(n[0])), out = [];
  for (const [k, s] of nb) for (const x of s) if (k < x) out.push([k, x]);
  return [keep, out];
}
function wl(nodes0, edges0, label, special) {
  const [nodes, edges] = skeleton(nodes0, edges0, special);
  const nb = new Map(nodes.map(n => [n[0], []]));
  for (const [a, b] of edges) { if (nb.has(a) && nb.has(b)) { nb.get(a).push(b); nb.get(b).push(a); } }
  let lab = new Map(nodes.map(n => [n[0], label(n)])); const feat = new Map();
  const add = l => feat.set(l, (feat.get(l) || 0) + 1);
  lab.forEach(add);
  for (let it = 0; it < 2; it++) {
    const nxt = new Map();
    for (const [k, l] of lab) nxt.set(k, l + "(" + nb.get(k).map(x => lab.get(x)).sort().join(",") + ")");
    lab = nxt; lab.forEach(add);
  }
  return feat;
}
const refLabel = n => n[1] === "site" ? (n[2] || "S") : n[1] === "t_spawn" ? "T" : n[1] === "ct_spawn" ? "CT" : "r";
const myLabel = n => n[1] === "room" ? "r" : n[1];
function cosine(a, b) { let d = 0, na = 0, nb = 0; for (const [k, v] of a) { na += v * v; if (b.has(k)) d += v * b.get(k); } for (const v of b.values()) nb += v * v; return d / (Math.sqrt(na * nb) || 1); }
const refSpecial = n => n[1] === "site" || n[1] === "t_spawn" || n[1] === "ct_spawn";
const mySpecial = n => n[1] !== "room";

/* ---------- layout similarity: where CT and the sites sit relative to T, plus the timing profile ---------- */
function refAsG(r) {   // a reference map in the editor's own terms (board units, same timing model)
  const roleOf = n => n[1] === "site" ? (n[2] === "B" ? "B" : "A") : n[1] === "t_spawn" ? "T" : n[1] === "ct_spawn" ? "CT" : "room";
  const used = new Set();
  const nodes = r.nodes.map(n => { let role = roleOf(n); if (role !== "room" && used.has(role)) role = "room"; used.add(role);
    return {id: n[0], role, name: n[0], x: n[4][0] / U, y: -n[4][1] / U, level: Math.max(-1, Math.min(1, n[3]))}; });
  const ids = new Set(nodes.map(n => n.id));
  return {nodes, edges: r.edges.filter(e => ids.has(e[0]) && ids.has(e[1])).map(e => ({a: e[0], b: e[1], kind: e[2] === "drop" ? "drop" : "corridor"}))};
}
function signature(g) {
  const at = r => g.nodes.find(n => n.role === r);
  const T = at("T"), CT = at("CT"), A = at("A"), B = at("B");
  if (!T || !CT || !A || !B) return null;
  // frame: T at the origin, the sites' midpoint straight "up", unit = T -> midpoint
  const mx = (A.x + B.x) / 2 - T.x, my = (A.y + B.y) / 2 - T.y, L = Math.hypot(mx, my) || 1;
  const ux = mx / L, uy = my / L, f = n => [((n.x - T.x) * -uy + (n.y - T.y) * ux) / L, ((n.x - T.x) * ux + (n.y - T.y) * uy) / L];
  const m = metrics(g), t = v => isFinite(v) ? v : 60;
  return {pos: [...f(CT), ...f(A), ...f(B)], time: [t(m.tA), t(m.tB), t(m.cA), t(m.cB), t(m.rot)]};
}
function geoDist(a, b) {
  // A/B letters are guesses on the reference maps: also try the mirror (x flipped, A <-> B)
  const flip = q => [-q[0], q[1], -q[4], q[5], -q[2], q[3]];
  const flipT = q => [q[1], q[0], q[3], q[2], q[4]];
  const d = (p, q, tp, tq) => Math.sqrt(p.reduce((s, v, i) => s + (v - q[i]) ** 2, 0)) + Math.sqrt(tp.reduce((s, v, i) => s + ((v - tq[i]) / 10) ** 2, 0));
  return Math.min(d(a.pos, b.pos, a.time, b.time), d(a.pos, flip(b.pos), a.time, flipT(b.time)));
}
function initRefs(data) {
  REFS = data;
  REF_FEAT = Object.fromEntries(Object.entries(REFS).filter(([k]) => !k.startsWith("own:")).map(([k, r]) => [k, wl(r.nodes, r.edges, refLabel, refSpecial)]));
  REF_SIG = Object.fromEntries(Object.keys(REF_FEAT).map(k => [k, signature(refAsG(REFS[k]))]));
}
function closest(g) {
  if (g.nodes.length < 3) return [];
  const f = wl(g.nodes.map(n => [n.id, n.role]), g.edges.map(e => [e.a, e.b]), myLabel, mySpecial);
  const sig = signature(g);
  return Object.keys(REF_FEAT).map(k => {
    const st = cosine(f, REF_FEAT[k]), geo = !sig ? null : REF_SIG[k] ? Math.exp(-geoDist(sig, REF_SIG[k])) : 0;   // a map without two sites: no layout match
    return [k, geo === null ? st : 0.6 * st + 0.4 * geo, st, geo];   // overall, structure, layout
  }).sort((a, b) => b[1] - a[1]);
}

/* ---------- suggestions: try small edits, keep the ones that improve the score ---------- */
function clone(g) { return JSON.parse(JSON.stringify(g)); }
function candidates(g) {
  const out = [], nb = nbrs(g), sitesOrSpawn = r => ["T", "CT", "A", "B"].includes(r);
  for (let i = 0; i < g.nodes.length; i++) for (let j = i + 1; j < g.nodes.length; j++) {
    const a = g.nodes[i], b = g.nodes[j];
    if (nb.get(a.id).has(b.id)) continue;
    if (sitesOrSpawn(a.role) && sitesOrSpawn(b.role)) continue;
    if (dist(a, b) > 2600) continue;
    const h = clone(g); h.edges.push({a: a.id, b: b.id, kind: "corridor"});
    out.push({key: `add:${a.id}-${b.id}`, text: `Connect ${a.name} ↔ ${b.name}`, g: h});
  }
  for (const e of g.edges) {
    const h = clone(g); h.edges = h.edges.filter(x => !(x.a === e.a && x.b === e.b));
    out.push({key: `rm:${e.a}-${e.b}`, text: `Remove ${byId(e.a).name} ↔ ${byId(e.b).name}`, g: h});
  }
  const m = metrics(g), ct = byId(m.has.CT || ""), tt = byId(m.has.T || ""), sa = byId(m.has.A || ""), sb = byId(m.has.B || "");
  if (tt && sa && sb) for (const f of [0.15, -0.15]) {
    const h = clone(g), c = h.nodes.find(n => n.id === tt.id), mx = (sa.x + sb.x) / 2, my = (sa.y + sb.y) / 2;
    c.x += (mx - c.x) * f; c.y += (my - c.y) * f;
    out.push({key: `mv:T:${f}`, text: `Move T spawn ${f > 0 ? "closer to" : "further from"} the sites`, g: h});
  }
  for (const s of ["A", "B"]) {
    const t = byId(m.has[s] || ""); if (!ct || !t) continue;
    for (const f of [0.2, -0.2]) {
      const h = clone(g), c = h.nodes.find(n => n.id === ct.id);
      c.x += (t.x - c.x) * f; c.y += (t.y - c.y) * f;
      out.push({key: `mv:CT:${s}:${f}`, text: `Move CT spawn ${f > 0 ? "towards" : "away from"} ${s}`, g: h});
    }
  }
  for (const n of g.nodes.filter(n => n.role === "room")) for (const lv of [-1, 1]) {
    if (n.level + lv < -1 || n.level + lv > 1) continue;
    const h = clone(g); h.nodes.find(x => x.id === n.id).level += lv;
    out.push({key: `lv:${n.id}:${lv}`, text: `Put ${n.name} ${lv > 0 ? "one level up" : "one level down"}`, g: h});
  }
  return out;
}
function describe(before, after, simB, simA) {
  const d = [], f = v => isFinite(v) ? v.toFixed(1) : "∞";
  const pairs = [["tA", "T→A", "s"], ["tB", "T→B", "s"], ["rot", "rotation", "s"], ["eA", "entrances A", ""], ["eB", "entrances B", ""]];
  for (const [k, l, u] of pairs) if (Math.abs((after[k] || 0) - (before[k] || 0)) > 0.4 || (isFinite(after[k]) !== isFinite(before[k]))) d.push(`${l} ${f(before[k])}${u} → ${f(after[k])}${u}`);
  const la = before.tA - before.cA, lb = after.tA - after.cA; if (Math.abs(la - lb) > 0.4) d.push(`CT first at A ${f(la)} → ${f(lb)} s`);
  const ma = before.tB - before.cB, mb = after.tB - after.cB; if (Math.abs(ma - mb) > 0.4) d.push(`CT first at B ${f(ma)} → ${f(mb)} s`);
  if (before.four.length !== after.four.length) d.push(`4-way junctions ${before.four.length} → ${after.four.length}`);
  if (before.direct !== after.direct) d.push(`spawn → site doors ${before.direct} → ${after.direct}`);
  if (before.retakeA + before.retakeB !== after.retakeA + after.retakeB) d.push(`CT retake routes ${before.retakeA + before.retakeB} → ${after.retakeA + after.retakeB}`);
  if (simB && simA && Math.abs(simB[1] - simA[1]) > 0.03) d.push(`closest map ${simB[0]} ${(simB[1] * 100).toFixed(0)} % → ${simA[0]} ${(simA[1] * 100).toFixed(0)} %`);
  return d.join(" · ");
}
function suggestions(g) {
  const m0 = metrics(g); if (!m0.has.T || !m0.has.CT || !m0.has.A || !m0.has.B) return [];
  const p0 = penalty(m0), s0 = closest(g)[0], sim0 = s0 ? s0[1] : 0;
  const scored = [];
  for (const c of candidates(g)) {
    if (rejected.has(c.key)) continue;
    const m = metrics(c.g), p = penalty(m), s = closest(c.g)[0];
    // better rules first; when the rules hold, prefer edits that make it less like an existing map
    const gain = (p0 - p) + (p <= p0 + 0.01 && sim0 > 0.8 ? (sim0 - s[1]) * 20 : 0);
    if (gain > 0.3) scored.push({...c, gain, why: describe(m0, m, s0, s)});
  }
  return scored.sort((a, b) => b.gain - a.gain).slice(0, 3);
}

/* ---------- drawing ---------- */
function toBoard(ev) { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); }
function draw() {
  svg.innerHTML = "";
  for (let i = 0; i <= 640; i += 640 / 24) { el("line", {x1: i, y1: 0, x2: i, y2: 640, stroke: "#20232a"}, svg); el("line", {x1: 0, y1: i, x2: 640, y2: i, stroke: "#20232a"}, svg); }
  drawBefore();
  for (const e of G.edges) {
    const a = byId(e.a), b = byId(e.b);
    const line = el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: e.kind === "drop" ? "#ff8a5c" : e.kind === "ladder" ? "#7cc7ff" : "#ddd", "stroke-width": 4, "stroke-dasharray": e.kind === "ladder" ? "4 4" : ""}, svg);
    // a wide invisible line on top: easy to hit; mousedown (the board redraws on its own mousedown)
    const hit = el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "transparent", "stroke-width": 18}, svg);
    hit.style.cursor = tool === "delete" ? "pointer" : "default";
    hit.addEventListener("mousedown", ev => {
      if (tool === "connect") return; ev.stopPropagation();
      if (tool === "delete") { save(); G.edges = G.edges.filter(x => x !== e); if (sel && sel.e === e) sel = null; update(); return; }
      sel = {e}; update();
    });
    if (sel && sel.e === e) { line.setAttribute("stroke", "#fff"); line.setAttribute("stroke-width", 7); }
    hit.addEventListener("mouseenter", () => { if (tool === "delete") line.setAttribute("stroke", "var(--bad)"); });
    hit.addEventListener("mouseleave", () => line.setAttribute("stroke", e.kind === "drop" ? "#ff8a5c" : e.kind === "ladder" ? "#7cc7ff" : "#ddd"));
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    if (e.kind === "choke") el("rect", {x: mx - 6, y: my - 6, width: 12, height: 12, fill: "var(--warn)", transform: `rotate(45 ${mx} ${my})`}, svg);
    if (e.kind === "drop") { const ang = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI; el("path", {d: "M-8 -6 L4 0 L-8 6 Z", fill: "#ff8a5c", transform: `translate(${mx} ${my}) rotate(${ang})`}, svg); }
    const t = el("text", {x: mx + 8, y: my - 6, fill: "#777", "font-size": 10}, svg); t.textContent = (edgeLen(G, e) / SPEED).toFixed(1) + "s";
  }
  for (const n of G.nodes) {
    const g = el("g", {transform: `translate(${n.x} ${n.y})`}, svg);
    const r = n.role === "room" ? 13 : 20;
    el("circle", {r, fill: COLOR[n.role], stroke: pick === n.id || (sel && sel.n === n.id) ? "#fff" : n.level > 0 ? "#bbb" : "none", "stroke-width": 3, "stroke-dasharray": n.level < 0 ? "4 3" : ""}, g);
    if (n.level < 0) el("circle", {r: r + 4, fill: "none", stroke: "#999", "stroke-dasharray": "3 3"}, g);
    if (n.level > 0) el("circle", {r: r + 4, fill: "none", stroke: "#ddd"}, g);
    const t = el("text", {y: n.role === "room" ? 28 : 5, "text-anchor": "middle", fill: n.role === "room" ? "#bbb" : "#111", "font-size": 12, "font-weight": n.role === "room" ? 400 : 700}, g);
    t.textContent = n.role === "room" ? n.name + (n.desc ? " ✎" : "") : n.role;   // spawns/sites: the role in the circle
    if (n.role !== "room" && (n.name !== n.role || n.desc)) {
      const u = el("text", {y: 36, "text-anchor": "middle", fill: "#bbb", "font-size": 11}, g);
      u.textContent = (n.name !== n.role ? n.name : "") + (n.desc ? " ✎" : "");
    }
    g.style.cursor = "pointer";
    if (n.desc) el("title", {}, g).textContent = n.desc;
    g.addEventListener("mousedown", ev => { ev.stopPropagation(); nodeDown(n); });
  }
  drawPreview();
}
let lastDown = {id: null, t: 0};
function rename(n) {   // the id stays, so connections are kept
  const v = prompt("Name", n.name);
  if (v && v.trim() && v.trim() !== n.name) { save(); n.name = v.trim().slice(0, 24); }
  update();
}
function nodeDown(n) {
  // our own double-click: the board redraws between clicks, so the browser never sees one
  const t = performance.now(), dbl = lastDown.id === n.id && t - lastDown.t < 400;
  lastDown = {id: n.id, t};
  if (dbl) { drag = null; pick = null; lastDown = {id: null, t: 0}; setTimeout(() => rename(n), 0); return; }
  if (tool !== "connect" && tool !== "delete") { save(); drag = n; sel = {n: n.id}; inspector(); draw(); return; }   // select + drag
  if (tool === "delete") { save(); if (sel && sel.n === n.id) sel = null; G.nodes = G.nodes.filter(x => x !== n); G.edges = G.edges.filter(e => e.a !== n.id && e.b !== n.id); update(); return; }
  if (tool === "connect") {
    if (!pick) { pick = n.id; draw(); return; }
    if (pick !== n.id && !G.edges.some(e => (e.a === pick && e.b === n.id) || (e.b === pick && e.a === n.id))) { save(); G.edges.push({a: pick, b: n.id, kind: document.getElementById("kind").value}); }
    pick = null; update(); return;
  }
}
svg.addEventListener("mousedown", ev => {
  const p = toBoard(ev);
  if (["T", "CT", "A", "B"].includes(tool)) {
    save(); let n = G.nodes.find(x => x.role === tool);
    if (n) { n.x = p.x; n.y = p.y; } else G.nodes.push({id: freeId(tool.toLowerCase()), role: tool, name: tool, x: p.x, y: p.y, level: 0});
    update();
  } else if (tool === "room") {
    save(); const id = freeId("r"); G.nodes.push({id, role: "room", name: id, x: p.x, y: p.y, level: +document.getElementById("level").value}); update();
  } else { pick = null; sel = null; update(); }
});
svg.addEventListener("mousemove", ev => { if (drag) { const p = toBoard(ev); drag.x = p.x; drag.y = p.y; draw(); } });
window.addEventListener("mouseup", () => { if (drag) { drag = null; update(); } });

/* ---------- suggestion preview: what the edit would change, drawn over the board ---------- */
let preview = null;
function drawPreview() {
  if (!preview) return;
  const h = preview, layer = el("g", {"pointer-events": "none"}, svg);
  const key = e => [e.a, e.b].sort().join("|");
  const before = new Map(G.edges.map(e => [key(e), e])), after = new Map(h.edges.map(e => [key(e), e]));
  const at = (g, id) => g.nodes.find(n => n.id === id);
  for (const [k, e] of after) if (!before.has(k)) {          // added
    const a = at(h, e.a), b = at(h, e.b);
    el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "var(--ok)", "stroke-width": 6, "stroke-dasharray": "10 6"}, layer);
    const t = el("text", {x: (a.x + b.x) / 2 + 8, y: (a.y + b.y) / 2 + 16, fill: "var(--ok)", "font-size": 12, "font-weight": 700}, layer);
    t.textContent = "+ " + (edgeLen(h, e) / SPEED).toFixed(1) + "s";
  }
  for (const [k, e] of before) if (!after.has(k)) {          // removed
    const a = at(G, e.a), b = at(G, e.b), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "var(--bad)", "stroke-width": 7, opacity: 0.85}, layer);
    el("path", {d: `M${mx - 9} ${my - 9}L${mx + 9} ${my + 9}M${mx + 9} ${my - 9}L${mx - 9} ${my + 9}`, stroke: "var(--bad)", "stroke-width": 4}, layer);
  }
  for (const n of h.nodes) {
    const o = at(G, n.id); if (!o) continue;
    if (Math.hypot(n.x - o.x, n.y - o.y) > 1) {              // moved: ghost + arrow
      el("line", {x1: o.x, y1: o.y, x2: n.x, y2: n.y, stroke: "var(--warn)", "stroke-width": 2, "stroke-dasharray": "4 4"}, layer);
      el("circle", {cx: n.x, cy: n.y, r: n.role === "room" ? 13 : 20, fill: COLOR[n.role], opacity: 0.45, stroke: "var(--warn)", "stroke-width": 3}, layer);
      for (const e of h.edges) if (e.a === n.id || e.b === n.id) {   // the moved node's connections, in their new place
        const a = at(h, e.a), b = at(h, e.b);
        el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "var(--warn)", "stroke-width": 2, opacity: 0.6}, layer);
      }
    }
    if (n.level !== o.level) {                               // level change
      el("circle", {cx: o.x, cy: o.y, r: 26, fill: "none", stroke: "var(--warn)", "stroke-width": 4, class: "pulse"}, layer);
      const t = el("text", {x: o.x, y: o.y - 32, "text-anchor": "middle", fill: "var(--warn)", "font-size": 12, "font-weight": 700}, layer);
      t.textContent = `level ${o.level} → ${n.level}`;
    }
  }
}
/* ---------- side pane ---------- */
function inspector() {
  const box = document.getElementById("insp"), f = (label, html) => `<label class="row"><span>${label}</span>${html}</label>`;
  const opt = (v, cur, txt) => `<option value="${v}"${String(v) === String(cur) ? " selected" : ""}>${txt}</option>`;
  const q = v => String(v || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  const n = sel && sel.n ? byId(sel.n) : null, e = sel && sel.e && G.edges.includes(sel.e) ? sel.e : null;
  if (!n && !e) { box.innerHTML = `<p class="hint">Click a node or a connection to edit it (Select tool).</p>`; return; }
  if (n) {
    box.innerHTML = f("Name", `<input id="i-name" value="${q(n.name)}" maxlength="24" style="width:160px">`) +
      f("Role", `<select id="i-role">${[["T", "T spawn"], ["CT", "CT spawn"], ["A", "Site A"], ["B", "Site B"], ["room", "Room"]].map(([v, t]) => opt(v, n.role, t)).join("")}</select>`) +
      f("Level", `<select id="i-level">${[[1, "upper (+1)"], [0, "ground (0)"], [-1, "below (−1)"]].map(([v, t]) => opt(v, n.level, t)).join("")}</select>`) +
      f("Size", `<select id="i-size">${["S", "M", "L", "XL"].map(v => opt(v, n.size || "M", v)).join("")}</select>`) +
      f("Outdoor", `<input type="checkbox" id="i-out"${n.outdoor ? " checked" : ""}>`) +
      `<div style="margin-top:6px">Description</div><textarea id="i-desc" rows="5" style="width:100%" placeholder="What should this place be like? e.g. B: the satellite in a clean-room lab, CT holds from a raised control room, close fights around the racks">${q(n.desc)}</textarea>` +
      `<p class="hint">${G.edges.filter(x => x.a === n.id || x.b === n.id).length} connections. Size, outdoor and the description go with the graph to the layout step; they don't change the checks.</p>`;
    const set = (k, v) => { save(); n[k] = v; update(); };
    document.getElementById("i-name").onchange = ev => ev.target.value.trim() && set("name", ev.target.value.trim());
    document.getElementById("i-role").onchange = ev => {   // spawns and sites are unique: the old holder becomes a room
      save(); const r = ev.target.value;
      if (r !== "room") for (const o of G.nodes) if (o !== n && o.role === r) { o.role = "room"; if (o.name === r) o.name = o.id; }
      if (n.name === n.role) n.name = r === "room" ? n.id : r;
      n.role = r; update();
    };
    document.getElementById("i-level").onchange = ev => set("level", +ev.target.value);
    document.getElementById("i-size").onchange = ev => set("size", ev.target.value);
    document.getElementById("i-out").onchange = ev => set("outdoor", ev.target.checked);
    document.getElementById("i-desc").onchange = ev => set("desc", ev.target.value.trim());
  } else {
    const a = byId(e.a), b = byId(e.b), l0 = e.len; delete e.len; const auto = edgeLen(G, e); if (l0) e.len = l0;
    box.innerHTML = `<p style="margin:0 0 6px"><b>${q(a.name)}</b> ${e.kind === "drop" ? "→" : "↔"} <b>${q(b.name)}</b></p>` +
      f("Type", `<select id="i-kind">${[["corridor", "corridor"], ["choke", "door / chokepoint"], ["drop", "drop (one-way)"], ["ladder", "ladder / stairs (climb ×2)"]].map(([v, t]) => opt(v, e.kind, t)).join("")}</select>`) +
      f("Width", `<select id="i-w">${[["narrow", "narrow (< 128)"], ["normal", "normal (128–192)"], ["wide", "wide (> 192)"]].map(([v, t]) => opt(v, e.width || "normal", t)).join("")}</select>`) +
      f("Length (units)", `<input id="i-len" type="number" min="64" step="16" value="${e.len || ""}" placeholder="${Math.round(auto)} auto" style="width:110px">`) +
      `<div style="margin-top:6px">Description</div><textarea id="i-desc" rows="3" style="width:100%" placeholder="e.g. a narrow tunnel with a bend, smoke-able">${q(e.desc)}</textarea>` +
      `<p class="hint">Time ${(edgeLen(G, e) / SPEED).toFixed(1)} s. Empty length = straight distance × 1.3. Width and description go to the layout step.</p>` +
      `<button id="i-flip">Swap ends${e.kind === "drop" ? " (reverse the drop)" : ""}</button>`;
    const set = (k, v) => { save(); if (v === undefined || v === "") delete e[k]; else e[k] = v; update(); };
    document.getElementById("i-kind").onchange = ev => set("kind", ev.target.value);
    document.getElementById("i-w").onchange = ev => set("width", ev.target.value);
    document.getElementById("i-len").onchange = ev => set("len", ev.target.value ? Math.max(64, +ev.target.value) : "");
    document.getElementById("i-desc").onchange = ev => set("desc", ev.target.value.trim());
    document.getElementById("i-flip").onclick = () => { save(); [e.a, e.b] = [e.b, e.a]; update(); };
  }
}
function update() {
  draw(); inspector(); persist();
  const m = metrics(G), f = v => isFinite(v) ? v.toFixed(1) + " s" : "—";
  // trend since the last edit: ▲/▼ = value up/down; green = closer to its band, red = further away
  const off = (v, lo, hi) => !isFinite(v) ? 1e9 : v < lo ? lo - v : v > hi ? v - hi : 0;
  const now = {tA: m.tA, tB: m.tB, lA: m.tA - m.cA, lB: m.tB - m.cB, rot: m.rot, eA: m.eA, eB: m.eB,
               re: (m.retakeA ? 1 : 0) + (m.retakeB ? 1 : 0), four: m.four.length, direct: m.direct, chokes: m.chokes, pen: penalty(m)};
  // prevM = the state before the last real change (stays until the next one)
  if (JSON.stringify(now) !== JSON.stringify(lastM)) { prevM = lastM; lastM = now; }
  const trend = (k, lo, hi) => {
    if (!prevM || !(k in prevM)) return "";
    const a = prevM[k], b = now[k];
    if (a === b || (isFinite(a) && isFinite(b) && Math.abs(a - b) < 0.05)) return "";
    const up = !isFinite(a) ? false : !isFinite(b) ? true : b > a;
    const better = off(b, lo, hi) < off(a, lo, hi), worse = off(b, lo, hi) > off(a, lo, hi);
    return ` <span class="${better ? "ok" : worse ? "bad" : "v"}" title="was ${isFinite(a) ? +a.toFixed(1) : "—"}">${up ? "▲" : "▼"}</span>`;
  };
  const row = (ok, label, v, band, t = "") => `<div class="row"><span class="${ok === null ? "" : ok ? "ok" : "warn"}">${ok === null ? "·" : ok ? "✓" : "!"} ${label}</span><span class="v">${v}${t} <small>${band}</small></span></div>`;
  const inb = (v, lo, hi) => isFinite(v) ? v >= lo && v <= hi : null;
  const has = m.has.T && m.has.CT && m.has.A && m.has.B;
  document.getElementById("checks").innerHTML = !has ? `<p class="hint">Place T, CT, A and B to start.</p>` :
    row(now.pen < 0.5, "Total distance from the bands", now.pen.toFixed(1), "0 = all ok", trend("pen", 0, 0)) +
    row(inb(m.tA, 14, 26), "T → A", f(m.tA), "14–26", trend("tA", 14, 26)) + row(inb(m.tB, 14, 26), "T → B", f(m.tB), "14–26", trend("tB", 14, 26)) +
    row(inb(now.lA, 3, 999), "CT first at A", f(now.lA), "≥ 3", trend("lA", 3, 1e9)) + row(inb(now.lB, 3, 999), "CT first at B", f(now.lB), "≥ 3", trend("lB", 3, 1e9)) +
    row(inb(m.rot, 10, 15), "Rotation A ↔ B", f(m.rot), "10–15", trend("rot", 10, 15)) +
    row(m.eA >= 2 && m.eA <= 3, "Entrances A", m.eA, "2–3", trend("eA", 2, 3)) + row(m.eB >= 2 && m.eB <= 3, "Entrances B", m.eB, "2–3", trend("eB", 2, 3)) +
    row(m.retakeA && m.retakeB, "CT retake route to both", (m.retakeA ? "A" : "–") + " " + (m.retakeB ? "B" : "–"), "", trend("re", 2, 2)) +
    row(m.four.length === 0, "No 4-way junctions", m.four.join(", ") || "none", "", trend("four", 0, 0)) +
    row(m.direct === 0, "No spawn → site door", m.direct, "", trend("direct", 0, 0)) +
    row(m.chokes >= 2, "Chokepoints", m.chokes, "≥ 1 per lane", trend("chokes", 2, 1e9));

  const c = closest(G).slice(0, 3);
  const pc = v => v === null || v === undefined ? "—" : (v * 100).toFixed(0) + " %";
  document.getElementById("refs").innerHTML = !c.length ? `<p class="hint">Add a few nodes.</p>` : c.map(([k, s, st, geo], i) =>
    `<div class="row"><span class="${i === 0 && s > 0.85 ? "bad" : ""}">${k} <small class="v">tier ${REFS[k].tier}</small></span><span class="v">${pc(s)} alike</span></div>` +
    `<div class="row hint" style="padding-left:10px"><span>structure ${pc(st)} · layout ${pc(geo)}</span></div>`).join("") +
    `<p class="hint">Structure = which rooms connect (roles, junctions). Layout = where CT and the sites sit relative to T, and the times. Overall = 60/40.</p>` +
    (c[0] && c[0][1] > 0.85 ? `<p class="bad">Very close to ${c[0][0]} — is that intended?</p>` : "");
  drawMini(c[0] && c[0][0]);
  const sg = suggestions(G);
  document.getElementById("sugs").innerHTML = !has ? `<p class="hint">Suggestions appear once spawns and sites are placed.</p>` : !sg.length ? `<p class="hint">No small edit improves the score right now.</p>` :
    sg.map((s, i) => `<div class="card sug"><b>${s.text}</b><p>${s.why || ""}</p><div class="btns"><button data-acc="${i}">Accept</button><button data-rej="${i}">Reject</button></div></div>`).join("");
  document.querySelectorAll("[data-acc]").forEach(b => b.onclick = () => { const s = sg[+b.dataset.acc]; save(); G = s.g; G.log = [...(LOG), {key: s.key, action: "accepted", time: new Date().toISOString()}]; LOG = G.log; preview = null; update(); });
  document.querySelectorAll("#sugs .sug").forEach((c, i) => {
    c.onmouseenter = () => { preview = sg[i].g; draw(); };
    c.onmouseleave = () => { preview = null; draw(); };
  });
  document.querySelectorAll("[data-rej]").forEach(b => b.onclick = () => { const s = sg[+b.dataset.rej]; rejected.add(s.key); LOG.push({key: s.key, action: "rejected", time: new Date().toISOString()}); preview = null; update(); });
}
function drawMini(name) {
  const m = document.getElementById("mini"); m.innerHTML = ""; if (!name) return;
  const r = REFS[name], xs = r.nodes.map(n => n[4][0]), ys = r.nodes.map(n => n[4][1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s = Math.min(280 / (x1 - x0 || 1), 130 / (y1 - y0 || 1)), P = new Map(r.nodes.map(n => [n[0], [10 + (n[4][0] - x0) * s, 140 - (n[4][1] - y0) * s]]));
  for (const [a, b] of r.edges) { const p = P.get(a), q = P.get(b); if (p && q) el("line", {x1: p[0], y1: p[1], x2: q[0], y2: q[1], stroke: "#666", "stroke-width": 1.5}, m); }
  for (const n of r.nodes) { const p = P.get(n[0]); const c = n[1] === "site" ? (n[2] === "A" ? "var(--a)" : "var(--b)") : n[1] === "t_spawn" ? "var(--t)" : n[1] === "ct_spawn" ? "var(--ct)" : "#888"; el("circle", {cx: p[0], cy: p[1], r: n[1] === "room" || n[1] === "corridor" ? 3 : 6, fill: c}, m); }
  const t = el("text", {x: 8, y: 14, fill: "#aaa", "font-size": 11}, m); t.textContent = name + " (extracted from its BSP)";
}
/* ---------- templates ---------- */
function initTemplates() {
  const sel = document.getElementById("tpl"), groups = [["own", "Own maps"], ["A", "Official (tier A)"], ["B", "Community (tier B)"]];
  sel.innerHTML += groups.map(([t, l]) => `<optgroup label="${l}">` + Object.keys(REFS).filter(k => REFS[k].tier === t).map(k => `<option value="${k}">${k.replace("own:", "")}</option>`).join("") + "</optgroup>").join("");
  const load = () => {
    const k = sel.value; save(); rejected.clear();
    if (!k) { G = {nodes: [], edges: []}; update(); return; }
    const r = REFS[k], special = n => n[1] !== "room" && n[1] !== "corridor" && n[1] !== "mid";
    let nodes = r.nodes, edges = r.edges.map(e => [e[0], e[1]]);
    // simplify, but keep the rooms right next to spawns and sites (approaches and chokepoints)
    const near = new Set(r.nodes.filter(special).map(n => n[0]));
    for (const [a, b] of r.edges) { if (near.has(a) || near.has(b)) { near.add(a); near.add(b); } }
    const keep = new Set([...near].filter(id => r.nodes.some(n => n[0] === id && special(n)) || r.edges.some(([a, b]) => (a === id || b === id) && r.nodes.some(n => (n[0] === (a === id ? b : a)) && special(n)))));
    if (document.getElementById("simple").checked) [nodes, edges] = skeleton(r.nodes, r.edges.map(e => [e[0], e[1]]), n => keep.has(n[0]));
    const kindOf = new Map(r.edges.map(e => [e[0] + "|" + e[1], e[2]]));
    const chokes = new Set((r.choke_edges || []).flatMap(([a, b]) => [a + "|" + b, b + "|" + a]));
    const xs = nodes.map(n => n[4][0]), ys = nodes.map(n => n[4][1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    const fit = Math.min(1, 5600 / (span || 1));   // keep the real scale unless it does not fit the board
    const roleOf = n => n[1] === "site" ? (n[2] === "B" ? "B" : "A") : n[1] === "t_spawn" ? "T" : n[1] === "ct_spawn" ? "CT" : "room";
    const used = new Set();
    G = {nodes: nodes.map(n => {
      let role = roleOf(n); if (role !== "room" && used.has(role)) role = "room"; used.add(role);
      return {id: role === "room" ? n[0] : role.toLowerCase(), src: n[0], role, name: role === "room" ? n[0] : role,
              x: 320 + (n[4][0] - cx) * fit / U, y: 320 - (n[4][1] - cy) * fit / U, level: Math.max(-1, Math.min(1, n[3]))};
    }), edges: []};
    const idOf = new Map(G.nodes.map(n => [n.src, n.id]));
    for (const [a, b] of edges) {
      const kd = kindOf.get(a + "|" + b) || kindOf.get(b + "|" + a) || "door";
      const kind = chokes.has(a + "|" + b) ? "choke" : kd === "drop" ? "drop" : kd === "ladder" || kd === "hatch" ? "ladder" : "corridor";
      if (idOf.has(a) && idOf.has(b)) G.edges.push(kind === "drop" && !kindOf.has(a + "|" + b) ? {a: idOf.get(b), b: idOf.get(a), kind} : {a: idOf.get(a), b: idOf.get(b), kind});
    }
    seq = G.nodes.length + 1;
    document.getElementById("scale").textContent = fit < 1 ? `Template scaled to ${(fit * 100).toFixed(0)} % to fit: times are shorter than in the real map.` : "";
    update();
  };
  sel.onchange = load; document.getElementById("simple").onchange = () => { if (sel.value) load(); };
}
document.querySelectorAll("[data-tool]").forEach(b => b.onclick = () => { tool = b.dataset.tool; pick = null; document.querySelectorAll("[data-tool]").forEach(x => x.classList.toggle("on", x === b)); draw(); });
document.querySelector("[data-tool=select]").classList.add("on");
document.getElementById("ed-undo").onclick = () => { if (hist.length) { G = JSON.parse(hist.pop()); update(); } };
document.getElementById("ed-clear").onclick = () => { save(); G = {nodes: [], edges: []}; update(); };
document.getElementById("ed-export").onclick = () => {
  const out = {version: 1, source: "editor", nodes: G.nodes.map(n => ({id: n.id, role: {T: "t_spawn", CT: "ct_spawn", A: "site", B: "site"}[n.role] || "room", site: ["A", "B"].includes(n.role) ? n.role : undefined, level: n.level, name: n.name, size: n.size, outdoor: n.outdoor || undefined, description: n.desc || undefined})),
    edges: G.edges.map(e => ({a: e.a, b: e.b, kind: e.kind === "choke" ? "door" : e.kind, choke: e.kind === "choke" || undefined, width: e.width, length: e.len, description: e.desc || undefined})),
    pos: Object.fromEntries(G.nodes.map(n => [n.id, [Math.round((n.x - 320) * U), Math.round((320 - n.y) * U)]]))};
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], {type: "application/json"})); a.download = "graph.json"; a.click();
};

/* ---------- the live API: load, autosave, approve, send a change ---------- */
const API = "http://localhost:8090/api";
const [MODE, MAP] = (decodeURIComponent(location.hash.slice(1)).match(/^(new|change)\/([A-Za-z0-9_-]+)$/) || [null, "", ""]).slice(1);
let LOG = [], BEFORE = null, BEFORE_API = null, FROZEN = false, savedJson = "", saveTimer = null;
const world = n => [Math.round((n.x - 320) * U), Math.round((320 - n.y) * U)];
function toApi(g) {
  return {version: 1, map: MAP || "", nodes: g.nodes.map(n => {
    const o = {id: n.id, name: n.name, role: n.role, level: n.level, size: n.size || "M", outdoor: !!n.outdoor, desc: n.desc || "", pos: world(n)};
    if (n.rect) o.rect = n.rect;
    return o;
  }), edges: g.edges.map(e => {
    const o = {a: e.a, b: e.b, kind: e.kind || "corridor", width: e.width || "normal", len: e.len || null, desc: e.desc || ""};
    if (e.via_area) o.via_area = e.via_area;
    if (e.doors) o.doors = e.doors;
    return o;
  }), suggestions: LOG};
}
function fromApi(g) {
  return {nodes: g.nodes.map(n => ({...n, x: 320 + n.pos[0] / U, y: 320 - n.pos[1] / U})), edges: g.edges.map(e => ({...e}))};
}
const status = t => { document.getElementById("ed-status").textContent = t; };
const complete = () => ["T", "CT", "A", "B"].every(r => G.nodes.some(n => n.role === r));
function persist() {   // new-map mode: autosave the draft (debounced), once it is a valid graph
  if (MODE !== "new") return;
  const json = JSON.stringify(toApi(G));
  if (json === savedJson) return;
  if (!complete()) { status("Not saved yet: place T, CT, A and B"); return; }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => put(false), 1000);
}
async function put(approve) {
  const graph = toApi(G), m = metrics(G);
  if (approve) graph.estimate = {tA: m.tA, tB: m.tB, cA: m.cA, cB: m.cB, rot: m.rot};
  try {
    const r = await fetch(`${API}/maps/${MAP}/graph`, {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({graph, approve})});
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.status);
    savedJson = JSON.stringify(toApi(G));
    status(approve ? `Approved ${new Date().toLocaleTimeString()}: Claude builds it with ./mf fromgraph MAP=${MAP}` : `Draft saved ${new Date().toLocaleTimeString()}`);
  } catch (err) { status(`Not saved: ${err.message} (is the live container running? docker compose up -d live)`); }
}
async function sendChange() {
  try {
    const r = await fetch(`${API}/maps/${MAP}/changes`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({before: BEFORE_API, after: toApi(G)})});
    const w = await r.json();
    if (!r.ok) throw new Error(w.error || r.status);
    status(w.ops.length ? `Wish #${w.id} saved (${w.ops.length} changes${w.status === "needs_human" ? ", waits for you: the layout is locked" : ""}): input to the next iteration.` : `Wish #${w.id} saved (names and descriptions only).`);
  } catch (err) { status(`Not sent: ${err.message} (is the live container running?)`); }
}
function drawBefore() {   // change mode: the map as it is, faint, under the edit
  if (!BEFORE) return;
  const layer = el("g", {"pointer-events": "none", opacity: 0.35}, svg), at = id => BEFORE.nodes.find(n => n.id === id);
  for (const e of BEFORE.edges) { const a = at(e.a), b = at(e.b); if (a && b) el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: "#9ab", "stroke-width": 2, "stroke-dasharray": "6 5"}, layer); }
  for (const n of BEFORE.nodes) el("circle", {cx: n.x, cy: n.y, r: n.role === "room" ? 9 : 14, fill: "none", stroke: "#9ab", "stroke-width": 2}, layer);
}
async function start() {
  try { initRefs(await (await fetch("refgraphs.json")).json()); } catch { initRefs({}); }
  initTemplates();
  const bar = document.getElementById("ed-modebar");
  if (MODE === "new") {
    bar.innerHTML = `<b>New map: ${MAP}</b> <button id="ed-approve">Approve graph</button>`;
    document.getElementById("ed-approve").onclick = () => complete() ? put(true) : status("Place T, CT, A and B first");
    const r = await fetch(`${API}/maps/${MAP}/graph`).catch(() => null);
    if (r && r.ok) { const g = await r.json(); G = fromApi(g); LOG = g.suggestions || []; savedJson = JSON.stringify(toApi(G)); status(`Loaded (${g.status})`); }
    else status(r ? "New graph: start from a template or place T, CT, A and B" : "The live container is not running: docker compose up -d live");
  } else if (MODE === "change") {
    bar.innerHTML = `<b>Change: ${MAP}</b> <button id="ed-send">Send as change</button> <a href="maps/${MAP}/index.html">back to the map</a>`;
    document.getElementById("ed-send").onclick = sendChange;
    const r = await fetch(`${API}/maps/${MAP}/topology`).catch(() => null);
    if (r && r.ok) {
      const t = await r.json(); BEFORE_API = t.graph; BEFORE = fromApi(t.graph); G = fromApi(t.graph); FROZEN = t.frozen;
      if (FROZEN) document.getElementById("ed-banner").outerHTML = `<div class="banner">The layout is locked (Gate B): structural changes are sent as a wish that waits for you to lift the lock.</div>`;
      status("Edit the graph; the faint lines are the map as it is now");
    } else status(r ? `Could not load the map (${r.status})` : "The live container is not running: docker compose up -d live");
    document.getElementById("tpl").disabled = true;
  } else bar.innerHTML = `<span class="hint">Scratch board: open it from a map's page (+ Add change) or the new-map guide to save.</span>`;
  seq = G.nodes.length + 1;
  update();
}
addEventListener("hashchange", () => location.reload());   // MODE/MAP are read once at load
start();
