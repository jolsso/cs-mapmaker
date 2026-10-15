// Style review section on a map page (mapforge/style/publish.py): every view with its notes,
// and a progress bar that refreshes while an analysis runs (polls style/*.json).
(function () {
  const grid = document.getElementById("style-grid");
  if (!grid) return;
  const bar = document.getElementById("style-progress");
  const sum = document.getElementById("style-summary");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const get = (f) => fetch(`style/${f}?t=${Date.now()}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const SEV = { critical: "bad", medium: "warn", cosmetic: "muted", ok: "ok" };
  let timer = null;

  function progress(p) {
    if (!p) return "";
    const pct = p.total ? Math.round((100 * p.done) / p.total) : 100;
    const mins = Math.max(0, Math.round(((p.updated || p.started) - p.started) / 60));
    const state = { running: `analysing sheet ${p.done + 1} of ${p.total}`, done: `done: ${p.total} sheets`, failed: `failed: ${esc(p.error)}` }[p.state] || p.state;
    return `<div class="sprog ${p.state}"><div class="sbar"><i style="width:${pct}%"></i></div>` +
      `<span>${esc(p.executor)} · ${esc(p.model || "")} · ${state} · ${p.views} views · ${mins} min</span></div>`;
  }

  function verdict(s) {
    if (!s) return "";
    const n = (v) => s.findings.filter((f) => f.severity === v).length;
    const zones = (s.zones || []).map((z) => `<span class="chip">${esc(z.zone)} ${z.score}/5</span>`).join(" ");
    return `<p class="small"><b class="${s.passed ? "ok" : "bad"}">${s.passed ? "PASS" : "FAIL"}</b> (${esc(s.executor)}) · ` +
      `${n("critical")} critical · ${n("medium")} medium · ${n("cosmetic")} cosmetic · ${s.reviewed} of ${s.images} views reviewed ${zones}</p>` +
      `<p class="muted small">${esc(s.summary)}</p>`;
  }

  function render(index, notes, style) {
    const byImg = {};
    (notes || []).forEach((n) => ((byImg[n.image] = byImg[n.image] || []).push({ src: "note", ...n })));
    ((style && style.findings) || []).forEach((f) => {
      if (f.source === "local") return; // already shown as a note
      (byImg[f.image] = byImg[f.image] || []).push({ src: "finding", flag: f.severity, note: f.what, fix: f.fix, source: f.source });
    });
    const zones = {};
    index.images.forEach((i) => ((zones[i.zone || "other"] = zones[i.zone || "other"] || []).push(i)));
    shown = Object.keys(zones).sort().flatMap((z) => zones[z].map((i) => i.file));
    index.images.forEach((i) => (info[i.file] = i));
    grid.innerHTML = Object.keys(zones).sort().map((z) =>
      `<h3 class="szone">Zone ${esc(z)}</h3><div class="scards">` + zones[z].map((i) => {
        const items = (byImg[i.file] || []).map((n) =>
          `<li class="${SEV[n.flag] || ""}"><b>${esc(n.flag)}</b>${n.zone_match ? ` · ${n.zone_match}/5` : ""} ${esc(n.note)}` +
          `${n.fix && n.fix !== "-" ? `<br><span class="muted">fix: ${esc(n.fix)}</span>` : ""}` +
          `<span class="muted small"> (${esc(n.source)})</span></li>`).join("");
        const pending = !byImg[i.file] ? `<li class="muted">${notes && notes.length ? "not judged in this run" : "waiting…"}</li>` : "";
        cards[i.file] = `<p><b>${esc(i.subject)}</b> <span class="muted small">${esc(i.kind)} · zone ${esc(i.zone || "-")} · ` +
          `${esc(i.purpose || "")}</span></p><ul class="snotes">${items || pending}</ul>`;
        return `<figure class="scard"><a href="#" data-lb="${esc(i.file)}">` +
          `<img loading="lazy" src="style/${esc(i.file.replace(".png", ".jpg"))}" alt="${esc(i.subject)}"></a>` +
          `<figcaption><b>${esc(i.subject)}</b> <span class="muted small">${esc(i.kind)} · luma ${i.mean_luma}</span>` +
          `<ul class="snotes">${items || pending}</ul></figcaption></figure>`;
      }).join("") + "</div>").join("");
  }

  // Lightbox: a click on a view shows it large over the page; arrows cycle, Esc or a click
  // beside the image closes it.
  let shown = [], at = -1, cards = {};
  const box = document.createElement("div");
  box.className = "lightbox";
  box.hidden = true;
  box.innerHTML = `<button class="lb-nav prev" aria-label="previous">‹</button><figure>` +
    `<div class="lb-view"><img class="lb-img" alt=""><div class="lb-mini" hidden><img alt="minimap">` +
    `<svg viewBox="0 0 512 512"></svg></div></div>` +
    `<figcaption></figcaption></figure><button class="lb-nav next" aria-label="next">›</button>`;
  document.body.appendChild(box);
  const lbImg = box.querySelector(".lb-img"), lbCap = box.querySelector("figcaption");
  const mini = box.querySelector(".lb-mini"), miniSvg = mini.querySelector("svg");
  let map = null, info = {};
  get("minimap.json").then((m) => {
    if (!m) return;
    map = m;
    mini.querySelector("img").src = `style/minimap.jpg?t=${Date.now()}`;
    mini.style.aspectRatio = `${m.size[0]} / ${m.size[1]}`;
    miniSvg.setAttribute("viewBox", `0 0 ${m.size[0]} ${m.size[1]}`);
  });

  // The camera on the minimap: a dot at the eye and a view cone towards the target (north up).
  function place(i) {
    if (!map || !i || !i.eye) return (mini.hidden = true);
    const [x0, y0, x1, y1] = map.world_rect;
    const [W, H] = map.size;
    const fx = (x) => ((x - x0) / (x1 - x0)) * W, fy = (y) => ((y1 - y) / (y1 - y0)) * H;
    const ex = fx(i.eye[0]), ey = fy(i.eye[1]);
    const a = Math.atan2(-(i.target[1] - i.eye[1]), i.target[0] - i.eye[0]); // screen angle
    const half = ((i.fov || 70) / 2) * (Math.PI / 180), r = 0.13 * W;
    const p = (t) => `${ex + r * Math.cos(t)},${ey + r * Math.sin(t)}`;
    miniSvg.innerHTML = `<path d="M${ex},${ey} L${p(a - half)} A${r},${r} 0 0 1 ${p(a + half)} Z" class="cone"/>` +
      `<line x1="${ex}" y1="${ey}" x2="${ex + r * Math.cos(a)}" y2="${ey + r * Math.sin(a)}" class="dir"/>` +
      `<circle cx="${ex}" cy="${ey}" r="${0.015 * W}" class="eye"/>`;
    mini.hidden = false;
  }

  function show(k) {
    if (!shown.length) return;
    at = (k + shown.length) % shown.length;
    const f = shown[at];
    lbImg.src = `style/${f.replace(".png", "_full.jpg")}`;
    place(info[f]);
    lbCap.innerHTML = `<span class="muted small">${at + 1} / ${shown.length} · ← → · Esc</span>` + (cards[f] || "");
    box.hidden = false;
    document.body.classList.add("lb-open");
  }
  function hide() {
    box.hidden = true;
    at = -1;
    document.body.classList.remove("lb-open");
  }
  grid.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-lb]");
    if (!a) return;
    ev.preventDefault();
    show(shown.indexOf(a.dataset.lb));
  });
  box.addEventListener("click", (ev) => {
    if (ev.target.closest(".prev")) return show(at - 1);
    if (ev.target.closest(".next")) return show(at + 1);
    if (!ev.target.closest(".lb-view, figcaption")) hide(); // a click beside the image
  });
  document.addEventListener("keydown", (ev) => {
    if (box.hidden) return;
    if (ev.key === "ArrowRight") show(at + 1);
    else if (ev.key === "ArrowLeft") show(at - 1);
    else if (ev.key === "Escape") hide();
    else return;
    ev.preventDefault();
  });

  async function tick() {
    const [index, notes, prog] = await Promise.all([get("index.json"), get("notes.json"), get("progress.json")]);
    if (!index) return;
    const running = prog && prog.state === "running";
    const style = running ? null : await get("style.json"); // scored only after a run
    bar.innerHTML = progress(prog);
    sum.innerHTML = prog && prog.state === "running" ? "" : verdict(style);
    render(index, prog && prog.state === "running" ? notes : notes || [], style);
    if (at >= 0) show(at);
    clearTimeout(timer);
    if (prog && prog.state === "running") timer = setTimeout(tick, 3000);
  }
  tick();
})();
