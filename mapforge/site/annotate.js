// MapForge annotations: draw wishes on the map's top-down (point / area / freehand line + text).
// Saved through the local API in the live container (mapforge.live.collector ->
// maps/<map>/annotations.json); the loop's Decide step reads them first. ANN = {map, img, rect, size}.
"use strict";
(() => {
  const API = `http://localhost:8090/api/annotations/${encodeURIComponent(ANN.map)}`;
  const root = document.getElementById("annotate");
  if (!root) return;
  const cv = root.querySelector("canvas"), ctx = cv.getContext("2d");
  const textEl = root.querySelector("textarea"), msg = root.querySelector(".annmsg");
  const list = root.querySelector(".annlist");
  const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
  let tool = "point", items = [], draft = null, drawing = false;
  const img = new Image();
  img.onload = () => { resize(); };
  img.src = ANN.img;

  const [x0, y0, x1, y1] = ANN.rect;
  const toWorld = (px, py) => [x0 + px / cv.width * (x1 - x0), y1 - py / cv.height * (y1 - y0)];
  const toPx = (x, y) => [(x - x0) / (x1 - x0) * cv.width, (y1 - y) / (y1 - y0) * cv.height];
  const COLORS = { open: "#f2a93b", done: "#5cc28a", needs_human: "#ef6a55", rejected: "#8d969f" };

  function resize() {
    const w = cv.clientWidth || 600;
    cv.width = w; cv.height = Math.round(w * ANN.size[1] / ANN.size[0]);
    draw();
  }
  window.addEventListener("resize", resize);

  function shape(a, color, label) {
    const pts = a.points.map(p => toPx(p[0], p[1]));
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 3;
    if (!pts.length) return;
    if (a.kind === "point") {
      const [x, y] = pts[0];
      ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.globalAlpha = .35; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke();
    } else if (a.kind === "rect" && pts.length >= 2) {
      const [[ax, ay], [bx, by]] = pts;
      ctx.globalAlpha = .18; ctx.fillRect(ax, ay, bx - ax, by - ay); ctx.globalAlpha = 1;
      ctx.setLineDash([8, 5]); ctx.strokeRect(ax, ay, bx - ax, by - ay); ctx.setLineDash([]);
    } else if (pts.length >= 2) {
      ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
      for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
      ctx.stroke();
    }
    if (label) {
      const [x, y] = pts[0];
      ctx.font = "bold 13px Bahnschrift, Segoe UI, sans-serif";
      ctx.fillStyle = "#000"; ctx.fillRect(x + 8, y - 22, ctx.measureText(label).width + 8, 18);
      ctx.fillStyle = color; ctx.fillText(label, x + 12, y - 8);
    }
  }

  function draw() {
    ctx.clearRect(0, 0, cv.width, cv.height);
    if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, cv.width, cv.height);
    for (const a of items) shape(a, COLORS[a.status] || "#fff", `#${a.id}`);
    if (draft) shape(draft, "#ffffff", "ny");
  }

  function pos(ev) {
    const r = cv.getBoundingClientRect();
    return [(ev.clientX - r.left) * cv.width / r.width, (ev.clientY - r.top) * cv.height / r.height];
  }

  cv.addEventListener("pointerdown", ev => {
    if (tool === "note") return;
    const [px, py] = pos(ev), w = toWorld(px, py);
    drawing = true; cv.setPointerCapture(ev.pointerId);
    draft = { kind: tool, points: tool === "rect" ? [w, w] : [w] };
    draw();
  });
  cv.addEventListener("pointermove", ev => {
    if (!drawing || !draft) return;
    const w = toWorld(...pos(ev));
    if (draft.kind === "rect") draft.points[1] = w;
    else if (draft.kind === "path") {
      const last = draft.points[draft.points.length - 1];
      if (Math.hypot(w[0] - last[0], w[1] - last[1]) > 24) draft.points.push(w);
    } else draft.points = [w];
    draw();
  });
  cv.addEventListener("pointerup", () => { drawing = false; textEl.focus(); });

  root.querySelectorAll("[data-tool]").forEach(b => b.addEventListener("click", () => {
    tool = b.dataset.tool; draft = tool === "note" ? { kind: "note", points: [] } : null; draw();
    if (tool === "note") textEl.focus();
    root.querySelectorAll("[data-tool]").forEach(x => x.classList.toggle("on", x === b));
  }));

  async function load() {
    try {
      const r = await fetch(API);
      items = r.ok ? await r.json() : [];
      msg.textContent = "";
    } catch {
      msg.innerHTML = "API'et kører ikke: <code>docker compose up -d live</code>";
    }
    renderList(); draw();
  }

  function renderList() {
    const label = { open: "åben", done: "udført", needs_human: "kræver dig", rejected: "afvist" };
    const kind = { point: "punkt", rect: "område", path: "streg", note: "tekst" };
    list.innerHTML = items.length ? items.slice().reverse().map(a =>
      `<li class="st-${esc(a.status)}"><b>#${a.id}</b> <span class="chip">${kind[a.kind] || ""}</span>
       <span class="chip ${a.status === "done" ? "ok" : a.status === "needs_human" ? "bad" : "run"}">${label[a.status] || esc(a.status)}</span>
       <span>${esc(a.text)}</span>${a.resolution ? `<div class="muted small">${esc(a.resolution)}</div>` : ""}
       <button data-del="${a.id}" title="slet">✕</button></li>`).join("") : "<li class='muted'>Ingen annotationer endnu.</li>";
    list.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => {
      await fetch(`${API}/${b.dataset.del}`, { method: "DELETE" });
      load();
    }));
  }

  root.querySelector(".annsave").addEventListener("click", async () => {
    if (!draft) { msg.textContent = "Tegn først på kortet – eller vælg \"Kun tekst\"."; return; }
    const text = textEl.value.trim();
    if (!text) { msg.textContent = "Skriv hvad du gerne vil have gjort."; textEl.focus(); return; }
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ ...draft, text }) });
      const body = await r.json();
      if (!r.ok) { msg.textContent = body.error || "kunne ikke gemme"; return; }
      draft = null; textEl.value = ""; msg.textContent = `Gemt som #${body.id} – loopets næste Decide tager den med.`;
      load();
    } catch {
      msg.innerHTML = "API'et kører ikke: <code>docker compose up -d live</code>";
    }
  });
  root.querySelector(".anncancel").addEventListener("click", () => { draft = null; textEl.value = ""; draw(); });
  load();
  setInterval(load, 15000);  // statuses change when the loop applies a plan
})();
