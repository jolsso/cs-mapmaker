// MapForge: start a new map from the dashboard (new.html). Step 1 creates the project through
// the live container's API (POST /api/maps -> maps/<name>/brief.json); step 2 loads the
// annotation tool (annotate.js) on a blank grid, so the human can sketch what they imagine.
// NEW = {img, rect, size} (the blank grid). The front page lists briefs not yet in the static site.
"use strict";
(() => {
  const API = "http://localhost:8090/api/maps";
  const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));

  // Front page: cards for briefs made since the site was built.
  const cards = document.querySelector("[data-own-maps]");
  if (cards) {
    const known = new Set(JSON.parse(cards.dataset.ownMaps || "[]"));
    fetch(API).then(r => r.ok ? r.json() : []).then(briefs => {
      for (const b of briefs) {
        if (known.has(b.name)) continue;
        const a = document.createElement("a");
        a.className = "pcard";
        a.href = `new.html#${encodeURIComponent(b.name)}`;
        a.innerHTML = `<div class='img brief'><span class='chip run badge'>ny brief</span></div><div class='body'>
          <div class='name'>${esc(b.name)}</div><p class='muted small'>${esc(b.description).slice(0, 180)}</p>
          <p class='nowline small'>▸ venter på layout (Claude laver det ud fra beskrivelsen og dine tegninger)</p></div>`;
        cards.querySelector(".newcard")?.after(a);
      }
    }).catch(() => {});
  }

  const form = document.getElementById("newmap");
  if (!form) return;
  const msg = form.querySelector(".annmsg");

  function openDrawing(name) {
    form.hidden = true;
    const sec = document.getElementById("annotate");
    sec.hidden = false;
    sec.querySelector(".mapname").textContent = name;
    document.getElementById("done").href = `maps/${encodeURIComponent(name)}/index.html`;
    window.ANN = { map: name, img: NEW.img, rect: NEW.rect, size: NEW.size };
    const s = document.createElement("script");
    s.src = NEW.annotate;
    document.body.appendChild(s);
  }

  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const name = form.name.value.trim(), description = form.description.value.trim();
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ name, description }) });
      const body = await r.json();
      if (!r.ok) { msg.textContent = body.error || "kunne ikke oprette mappet"; return; }
      history.replaceState(null, "", `#${encodeURIComponent(name)}`);
      openDrawing(name);
    } catch {
      msg.innerHTML = "API'et kører ikke: <code>docker compose up -d live</code>";
    }
  });

  // new.html#<name>: continue drawing on an existing brief
  const existing = decodeURIComponent(location.hash.slice(1));
  if (existing) openDrawing(existing);
})();
