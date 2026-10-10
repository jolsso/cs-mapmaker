// MapForge live page: Server-Sent Events from the live collector (mapforge.live.collector) drawn
// on the maps' top-down renders. MAPS (map -> {img, rect, size}) is injected by the site builder.
"use strict";
const COLLECTOR = "http://localhost:8090/events";
const imgs = {};
const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
const cards = {};

function img(map) {
  if (!imgs[map] && MAPS[map]) { imgs[map] = new Image(); imgs[map].src = MAPS[map].img; }
  return imgs[map];
}

function px(map, x, y, w, h) {
  const [x0, y0, x1, y1] = MAPS[map].rect;
  return [(x - x0) / (x1 - x0) * w, (y1 - y) / (y1 - y0) * h];
}

function card(run) {
  let c = cards[run.key];
  if (c) return c;
  const el = document.createElement("article");
  el.className = "livecard";
  el.innerHTML = `<header><b class="run"></b><span class="muted small meta"></span></header>
    <div class="score"><span class="t"></span><div class="bar"><i></i></div><span class="ct"></span></div>
    <canvas></canvas><div class="strip"></div><ul class="feed small"></ul>`;
  c = cards[run.key] = { el, canvas: el.querySelector("canvas") };
  return c;
}

function draw(c, run) {
  const m = MAPS[run.map];
  c.el.querySelector(".run").textContent = `${run.map} · ${run.run}`;
  const state = run.done ? "færdig" : run.stale ? `ingen data i ${run.age_s} s` : (run.live ? "runde i gang" : "freezetime / mellem runder");
  c.el.querySelector(".meta").textContent = `runde ${run.round} · ${run.t.toFixed(0)} s · ${state}`;
  c.el.classList.toggle("off", run.done || run.stale);
  const T = run.score.T, CT = run.score.CT, n = Math.max(T + CT, 1);
  c.el.querySelector(".score .t").textContent = `T ${T}`;
  c.el.querySelector(".score .ct").textContent = `${CT} CT`;
  c.el.querySelector(".score .bar i").style.width = `${(T / n) * 100}%`;
  c.el.querySelector(".strip").innerHTML = run.rounds.slice(-40).map(r =>
    `<i class="${r.winner === "T" ? "t" : r.winner === "CT" ? "ct" : ""}" title="runde ${esc(r.round)}: ${esc(r.winner)} (${esc(r.reason)}${r.site ? ", site " + esc(r.site) : ""})"></i>`).join("");
  const kills = run.kills.filter(k => k.round === run.round);
  c.el.querySelector(".feed").innerHTML = run.kills.slice(-4).reverse().map(k =>
    `<li><span class="${k.killer === "T" ? "tt" : "ctt"}">${esc(k.killer || "?")}</span> → <span class="${k.victim === "T" ? "tt" : "ctt"}">${esc(k.victim)}</span> <span class="muted">${esc(k.weapon)} · runde ${esc(k.round)}</span></li>`).join("");
  const cv = c.canvas, ctx = cv.getContext("2d");
  if (!m) { cv.width = 10; cv.height = 10; return; }
  const w = cv.clientWidth || 360, h = Math.round(w * m.size[1] / m.size[0]);
  if (cv.width !== w) { cv.width = w; cv.height = h; }
  const im = img(run.map);
  ctx.fillStyle = "#07090b"; ctx.fillRect(0, 0, w, h);
  if (im.complete && im.naturalWidth) ctx.drawImage(im, 0, 0, w, h);
  for (const k of kills) {
    const [x, y] = px(run.map, k.x, k.y, w, h);
    ctx.strokeStyle = "#ef6a55"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4); ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4); ctx.stroke();
  }
  for (const p of run.players) {
    const [x, y] = px(run.map, p.x, p.y, w, h);
    ctx.fillStyle = !p.alive ? "rgba(140,150,160,.55)" : p.team === "T" ? "#e8792f" : "#4c8fe0";
    ctx.beginPath(); ctx.arc(x, y, p.alive ? 5 : 3.5, 0, Math.PI * 2); ctx.fill();
    if (p.alive) {
      const a = -p.yaw * Math.PI / 180;
      ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + Math.cos(a) * 11, y + Math.sin(a) * 11); ctx.stroke();
      ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.stroke();
    }
  }
}

function render(state) {
  const status = document.getElementById("status");
  const runs = state.runs;
  const active = runs.filter(r => !r.done && !r.stale);
  status.innerHTML = runs.length
    ? `<span class="chip ok">forbundet</span> ${active.length} kørende server(e) · ${runs.length - active.length} afsluttede`
    : `<span class="chip ok">forbundet</span> ingen simuleringer kører lige nu – start fx <code>./mf simulate MAP=…</code> eller loopet`;
  // per-map totals over all runs (live + recently finished)
  const byMap = {};
  for (const r of runs) {
    const t = byMap[r.map] ||= { T: 0, CT: 0, A: 0, B: 0, runs: 0 };
    t.T += r.score.T; t.CT += r.score.CT; t.runs += 1;
    for (const x of r.rounds) if (x.site) t[x.site] = (t[x.site] || 0) + 1;
  }
  document.getElementById("totals").innerHTML = Object.entries(byMap).map(([map, t]) => {
    const n = t.T + t.CT, plants = (t.A || 0) + (t.B || 0);
    return `<div class="kpi"><b>${n ? Math.round(100 * t.T / n) : "–"}%</b><span>${esc(map)}: T-winrate over ${n} runder (${t.runs} servere)</span></div>
      <div class="kpi"><b>${plants ? Math.round(100 * (t.A || 0) / plants) : "–"}%</b><span>${esc(map)}: plants på A (${plants})</span></div>`;
  }).join("");
  const box = document.getElementById("runs");
  for (const r of runs) {
    const c = card(r);
    if (c.el.parentNode !== box) box.appendChild(c.el);
    draw(c, r);
  }
  for (const key of Object.keys(cards)) {
    if (!runs.find(r => r.key === key)) { cards[key].el.remove(); delete cards[key]; }
  }
}

function connect() {
  const es = new EventSource(COLLECTOR);
  es.onmessage = ev => render(JSON.parse(ev.data));
  es.onerror = () => {
    document.getElementById("status").innerHTML =
      `<span class="chip bad">ingen forbindelse</span> live-collectoren kører ikke: <code>docker compose up -d live</code> (prøver igen …)`;
  };
}
connect();
