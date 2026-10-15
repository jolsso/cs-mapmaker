// Style reviews and galleries on a map page (mapforge/style/publish.py).
// - Every `.style-review[data-base]` shows that review's views with their notes (base/*.json),
//   and polls while its progress.json says "running" (the current build's section).
// - A click on a view (or on any `a[data-gallery]` image) opens the lightbox over the page:
//   arrows cycle, Esc or a click beside the image closes it; style views get a minimap that shows
//   where the camera stands and where it looks.
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SEV = { critical: "bad", medium: "warn", cosmetic: "muted", ok: "ok" };

  // ---------------------------------------------------------------- lightbox (one per page)
  const box = document.createElement("div");
  box.className = "lightbox";
  box.hidden = true;
  box.innerHTML = `<button class="lb-nav prev" aria-label="previous">‹</button><figure>` +
    `<div class="lb-view"><img class="lb-img" alt=""><div class="lb-mini" hidden><img alt="minimap">` +
    `<svg viewBox="0 0 512 512"></svg></div></div>` +
    `<figcaption></figcaption></figure><button class="lb-nav next" aria-label="next">›</button>`;
  document.body.appendChild(box);
  const lbImg = box.querySelector(".lb-img"), lbCap = box.querySelector("figcaption");
  const mini = box.querySelector(".lb-mini"), miniImg = mini.querySelector("img"), miniSvg = mini.querySelector("svg");
  let items = [], at = -1, owner = null;

  // items: [{src, caption (html), cam: {eye, target, fov}, map: {url, world_rect, size}}]
  function open(list, k, who) {
    items = list;
    owner = who || null;
    show(k);
  }
  function show(k) {
    if (!items.length) return;
    at = (k + items.length) % items.length;
    const it = items[at];
    lbImg.src = it.src;
    lbCap.innerHTML = `<span class="muted small">${at + 1} / ${items.length} · ← → · Esc</span>` + (it.caption || "");
    place(it);
    box.hidden = false;
    document.body.classList.add("lb-open");
  }
  function hide() {
    box.hidden = true;
    at = -1;
    owner = null;
    document.body.classList.remove("lb-open");
  }
  function place(it) {
    const m = it.map, i = it.cam;
    if (!m || !i || !i.eye) return (mini.hidden = true);
    const [x0, y0, x1, y1] = m.world_rect, [W, H] = m.size;
    if (miniImg.getAttribute("src") !== m.url) miniImg.src = m.url;
    mini.style.aspectRatio = `${W} / ${H}`;
    miniSvg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const fx = (x) => ((x - x0) / (x1 - x0)) * W, fy = (y) => ((y1 - y) / (y1 - y0)) * H;
    const ex = fx(i.eye[0]), ey = fy(i.eye[1]);
    const a = Math.atan2(-(i.target[1] - i.eye[1]), i.target[0] - i.eye[0]); // north up
    const half = ((i.fov || 70) / 2) * (Math.PI / 180), r = 0.13 * W;
    const p = (t) => `${ex + r * Math.cos(t)},${ey + r * Math.sin(t)}`;
    miniSvg.innerHTML = `<path d="M${ex},${ey} L${p(a - half)} A${r},${r} 0 0 1 ${p(a + half)} Z" class="cone"/>` +
      `<line x1="${ex}" y1="${ey}" x2="${ex + r * Math.cos(a)}" y2="${ey + r * Math.sin(a)}" class="dir"/>` +
      `<circle cx="${ex}" cy="${ey}" r="${0.015 * W}" class="eye"/>`;
    mini.hidden = false;
  }
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

  // ---------------------------------------------------------------- plain galleries
  // <a href="img.png" data-gallery="v018" data-caption="...">: all links of one gallery cycle.
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-gallery]");
    if (!a) return;
    ev.preventDefault();
    const group = [...document.querySelectorAll(`a[data-gallery="${CSS.escape(a.dataset.gallery)}"]`)];
    open(group.map((g) => ({ src: g.getAttribute("href"), caption: `<p><b>${esc(g.dataset.caption || "")}</b></p>` })), group.indexOf(a));
  });

  // ---------------------------------------------------------------- style reviews
  function review(root) {
    const base = root.dataset.base;
    const bar = root.querySelector(".style-progress"), sum = root.querySelector(".style-summary"), grid = root.querySelector(".style-grid");
    const get = (f) => fetch(`${base}${f}?t=${Date.now()}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    let map = null, order = [], timer = null;
    const info = {}, cards = {};
    get("minimap.json").then((m) => (map = m ? { ...m, url: `${base}minimap.jpg` } : null));

    const progress = (p) => {
      if (!p) return "";
      const pct = p.total ? Math.round((100 * p.done) / p.total) : 100;
      const mins = Math.max(0, Math.round(((p.updated || p.started) - p.started) / 60));
      const state = { running: `analysing sheet ${p.done + 1} of ${p.total}`, done: `done: ${p.total} sheets`, failed: `failed: ${esc(p.error)}` }[p.state] || p.state;
      return `<div class="sprog ${p.state}"><div class="sbar"><i style="width:${pct}%"></i></div>` +
        `<span>${esc(p.executor)} · ${esc(p.model || "")} · ${state} · ${p.views} views · ${mins} min</span></div>`;
    };
    const verdict = (s) => {
      if (!s) return "<p class='muted small'>Not scored yet.</p>";
      const n = (v) => s.findings.filter((f) => f.severity === v).length;
      const zones = (s.zones || []).map((z) => `<span class="chip">${esc(z.zone)} ${z.score}/5</span>`).join(" ");
      return `<p class="small"><b class="${s.passed ? "ok" : "bad"}">${s.passed ? "PASS" : "FAIL"}</b> (${esc(s.executor)}) · ` +
        `${n("critical")} critical · ${n("medium")} medium · ${n("cosmetic")} cosmetic · ${s.reviewed} of ${s.images} views reviewed ${zones}</p>` +
        `<p class="muted small">${esc(s.summary)}</p>`;
    };
    const lbItems = () => order.map((f) => ({ src: `${base}${f.replace(".png", "_full.jpg")}`, caption: cards[f], cam: info[f], map }));

    function render(index, notes, style) {
      const byImg = {};
      (notes || []).forEach((n) => ((byImg[n.image] = byImg[n.image] || []).push(n)));
      ((style && style.findings) || []).forEach((f) => {
        if (f.source === "local" && notes && notes.length) return; // already shown as a note
        (byImg[f.image] = byImg[f.image] || []).push({ flag: f.severity, note: f.what, fix: f.fix, source: f.source });
      });
      const zones = {};
      index.images.forEach((i) => ((zones[i.zone || "other"] = zones[i.zone || "other"] || []).push(i)));
      order = Object.keys(zones).sort().flatMap((z) => zones[z].map((i) => i.file));
      index.images.forEach((i) => (info[i.file] = i));
      grid.innerHTML = Object.keys(zones).sort().map((z) =>
        `<h3 class="szone">Zone ${esc(z)}</h3><div class="scards">` + zones[z].map((i) => {
          const list = (byImg[i.file] || []).map((n) =>
            `<li class="${SEV[n.flag] || ""}"><b>${esc(n.flag)}</b>${n.zone_match ? ` · ${n.zone_match}/5` : ""} ${esc(n.note)}` +
            `${n.fix && n.fix !== "-" ? `<br><span class="muted">fix: ${esc(n.fix)}</span>` : ""}` +
            `<span class="muted small"> (${esc(n.source)})</span></li>`).join("");
          const pending = `<li class="muted">${notes && notes.length ? "not judged in this run" : style ? "no findings" : "waiting…"}</li>`;
          cards[i.file] = `<p><b>${esc(i.subject)}</b> <span class="muted small">${esc(i.kind)} · zone ${esc(i.zone || "-")} · ` +
            `${esc(i.purpose || "")}</span></p><ul class="snotes">${list || pending}</ul>`;
          return `<figure class="scard"><a href="#" data-lb="${esc(i.file)}">` +
            `<img loading="lazy" src="${base}${esc(i.file.replace(".png", ".jpg"))}" alt="${esc(i.subject)}"></a>` +
            `<figcaption><b>${esc(i.subject)}</b> <span class="muted small">${esc(i.kind)} · luma ${i.mean_luma}</span>` +
            `<ul class="snotes">${list || pending}</ul></figcaption></figure>`;
        }).join("") + "</div>").join("");
    }
    grid.addEventListener("click", (ev) => {
      const a = ev.target.closest("a[data-lb]");
      if (!a) return;
      ev.preventDefault();
      open(lbItems(), order.indexOf(a.dataset.lb), root);
    });

    async function tick() {
      const [index, notes, prog] = await Promise.all([get("index.json"), get("notes.json"), get("progress.json")]);
      if (!index) return;
      const running = prog && prog.state === "running";
      const style = running ? null : await get("style.json"); // scored only after a run
      bar.innerHTML = progress(prog);
      sum.innerHTML = running ? "" : verdict(style);
      render(index, notes, style);
      if (owner === root && at >= 0) { items = lbItems(); show(at); } // new notes in an open lightbox
      clearTimeout(timer);
      if (running) timer = setTimeout(tick, 3000);
    }
    tick();
  }
  document.querySelectorAll(".style-review[data-base]").forEach(review);
})();
