// MapForge: start a new map from the dashboard (new.html, phase 8a guide). Steps 1-3 (mode,
// brief v2, images) go through the live container's API (POST /api/maps -> brief.json, POST
// /api/maps/<name>/images); step 4 loads the annotation tool (annotate.js) on a blank grid;
// step 5 shows the Interpreter's intent.json ("how I understood you") to correct and confirm.
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
    // closed / reopened since the site was built ("Afslut bane" under Input)
    fetch(API.replace("/api/maps", "/api/project")).then(r => r.ok ? r.json() : {}).then(states => {
      for (const card of cards.querySelectorAll(".pcard[data-map]")) {
        const st = states[card.dataset.map];
        if (st) card.classList.toggle("closed", st.state === "closed");
      }
    }).catch(() => {});
  }

  const form = document.getElementById("newmap");
  if (!form) return;
  const msg = form.querySelector(".annmsg");
  const C = NEW.choices || {};
  const lines = v => String(v || "").split("\n").map(s => s.trim()).filter(Boolean);

  // step 3: chosen images get a tag, a licence and a note before upload
  const imgList = form.querySelector(".imglist");
  const opt = (m, sel) => Object.entries(m).map(([k, v]) => `<option value="${k}"${k === sel ? " selected" : ""}>${esc(v)}</option>`).join("");
  form.images?.addEventListener("change", () => {
    imgList.innerHTML = "";
    for (const f of form.images.files) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${esc(f.name)} <span class="muted small">${Math.round(f.size / 1024)} kB</span></span>
        <select class="tag">${opt(C.tag || {}, "mood")}</select><select class="lic">${opt(C.license || {}, "inspiration")}</select>
        <input class="note" maxlength="300" placeholder="note (valgfri)">`;
      li.file = f;
      imgList.appendChild(li);
    }
  });

  function briefFromForm() {
    const v = n => (form[n]?.value || "").trim();
    const b = { name: v("name"), description: v("description"), mode: form.mode.value };
    for (const k of ["concept", "archetype", "size", "pace", "levels", "inside", "density", "site_cover", "mid", "theme"]) if (v(k)) b[k] = v(k);
    if (form.stacked_sites.checked) b.stacked_sites = true;
    const sl = {};
    if (v("sight_long")) sl.long = v("sight_long");
    if (v("sight_cqb")) sl.cqb = v("sight_cqb");
    if (Object.keys(sl).length) b.sightlines = sl;
    const sites = {};
    if (v("site_a")) sites.A = v("site_a");
    if (v("site_b")) sites.B = v("site_b");
    if (Object.keys(sites).length) b.sites = sites;
    const lm = lines(v("landmarks")).map(l => {
      const [name, ...rest] = l.split(/\s+[–-]\s+/);
      const note = rest.join(" - ");
      const space = /\bstor\b/i.test(note) ? "large" : /\blille\b/i.test(note) ? "small" : "medium";
      return { name: name.trim(), note, space };
    });
    if (lm.length) b.landmarks = lm;
    if (lines(v("must_have")).length) b.must_have = lines(v("must_have"));
    if (lines(v("no_go")).length) b.no_go = lines(v("no_go"));
    return b;
  }

  const b64 = f => new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",")[1]);
    r.onerror = fail;
    r.readAsDataURL(f);
  });

  async function uploadImages(name) {
    for (const li of imgList.querySelectorAll("li")) {
      msg.textContent = `uploader ${li.file.name} …`;
      const r = await fetch(`${API}/${encodeURIComponent(name)}/images`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: li.file.name, data: await b64(li.file), tag: li.querySelector(".tag").value,
                               license: li.querySelector(".lic").value, note: li.querySelector(".note").value }) });
      if (!r.ok) throw new Error(`${li.file.name}: ${(await r.json()).error || r.status}`);
    }
  }

  function openDrawing(name) {
    form.hidden = true;
    for (const id of ["annotate", "intent"]) {
      const sec = document.getElementById(id);
      sec.hidden = false;
      sec.querySelectorAll(".mapname").forEach(el => (el.textContent = name));
    }
    document.getElementById("done").href = `maps/${encodeURIComponent(name)}/index.html`;
    window.ANN = { map: name, img: NEW.img, rect: NEW.rect, size: NEW.size };
    const s = document.createElement("script");
    s.src = NEW.annotate;
    document.body.appendChild(s);
    watchIntent(name);
  }

  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    const b = briefFromForm();
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
      const body = await r.json();
      if (!r.ok) { msg.textContent = body.error || "kunne ikke oprette mappet"; return; }
      await uploadImages(b.name);
      history.replaceState(null, "", `#${encodeURIComponent(b.name)}`);
      openDrawing(b.name);
    } catch (e) {
      msg.innerHTML = e instanceof TypeError ? "API'et kører ikke: <code>docker compose up -d live</code>" : esc(e.message);
    }
  });

  // step 5: "how I understood you" - the Interpreter's intent.json, read / correct / confirm
  const label = (k, v) => (C[k] && C[k][v]) || v;
  function renderIntent(it) {
    const li = (t, v) => `<li><b>${t}:</b> ${v}</li>`;
    const sp = it.space || {}, ps = it.playstyle || {}, sl = ps.sightlines || {}, tg = it.targets || {};
    const mh = (it.must_have || []).map(m => `<li class="${m.status === "rejected" ? "bad" : "ok"}">${esc(m.item)} – <span class="muted">${m.status === "rejected" ? "afvist" : "med"}: ${esc(m.how)}</span></li>`).join("");
    const as = (it.assumptions || []).map(a => `<li><b>${esc(a.field)}</b> = ${esc(a.value)} <span class="muted">– ${esc(a.why)}</span></li>`).join("");
    const lm = (it.landmarks || []).map(l => `<li>${esc(l.name)} <span class="muted">(${esc(l.where)}, ${esc(l.space)}) – ${esc(l.purpose)}</span></li>`).join("");
    const qs = (it.open_questions || []).map(q => `<li>${esc(q)}</li>`).join("");
    const meta = it.meta || {};
    return `<p class="lead">${esc(it.summary)}</p>
      <p class="muted small">${meta.confirmed ? "✔ bekræftet" : "venter på din bekræftelse"} · ${esc(meta.by || "")} ${esc(meta.time || "")}</p>
      <div class="grid2"><div><h3>Mappet</h3><ul>
        ${li("Idé", esc(it.concept))}${li("Arketype", esc(label("archetype", it.archetype)))}${li("Størrelse", esc(label("size", it.size)))}
        ${li("Tempo", esc(label("pace", it.pace)))}${li("Niveauer", esc(label("levels", sp.levels)))}${li("Inde/ude", esc(label("inside", sp.inside)))}
        ${li("Trangt/åbent", esc(label("density", sp.density)))}${li("Stablede sites", sp.stacked_sites ? "ja" : "nej")}
        ${li("Sigtelinjer", `lange: ${esc(label("amount", sl.long))}, nærkamp: ${esc(label("amount", sl.cqb))}`)}${li("Sites", esc(label("site_cover", ps.site_cover)))}
        ${li("Site A", `${esc(it.sites?.A?.character)} <span class="muted">(${esc(it.sites?.A?.entrances)} indgange${it.sites?.A?.vertical ? ", vertikal" : ""})</span>`)}
        ${li("Site B", `${esc(it.sites?.B?.character)} <span class="muted">(${esc(it.sites?.B?.entrances)} indgange${it.sites?.B?.vertical ? ", vertikal" : ""})</span>`)}
        ${li("Mid", esc(it.mid))}
        ${li("Mål", `T → site ${esc(tg.t_to_site_s?.[0])}–${esc(tg.t_to_site_s?.[1])} s, CT før T ≥ ${esc(tg.ct_lead_s)} s, længste sigtelinje ${esc(tg.longest_sightline)} units`)}
      </ul></div><div><h3>Identitet</h3><ul>${li("Tema", esc(it.theme?.setting))}${li("Palet", esc((it.theme?.palette || []).join(", ")))}
        ${li("Materialer", esc((it.theme?.materials || []).join(", ")))}</ul>
        <h3>Landmærker</h3><ul>${lm || "<li class='muted'>ingen</li>"}</ul></div></div>
      <h3>Skal have</h3><ul>${mh || "<li class='muted'>intet i briefen</li>"}</ul>
      <h3>Det har jeg valgt for dig</h3><ul>${as || "<li class='muted'>intet</li>"}</ul>
      ${qs ? `<h3>Spørgsmål til dig</h3><ul>${qs}</ul>` : ""}`;
  }

  function watchIntent(name) {
    const sec = document.getElementById("intent");
    const body = sec.querySelector(".intentbody"), edit = sec.querySelector(".intentedit");
    const btns = sec.querySelector(".intentbtns"), imsg = sec.querySelector(".intentmsg");
    let shown = "";
    async function poll() {
      try {
        const r = await fetch(`${API}/${encodeURIComponent(name)}`);
        const d = r.ok ? await r.json() : {};
        if (d.intent && JSON.stringify(d.intent) !== shown) {
          shown = JSON.stringify(d.intent);
          body.innerHTML = renderIntent(d.intent);
          const { meta, ...plain } = d.intent;
          edit.querySelector("textarea").value = JSON.stringify(plain, null, 2);
          edit.hidden = btns.hidden = false;
        }
      } catch { /* API down: try again */ }
      setTimeout(poll, 5000);
    }
    async function put(confirm) {
      let intent;
      try { intent = JSON.parse(edit.querySelector("textarea").value); } catch (e) { imsg.textContent = `JSON-fejl: ${e.message}`; return; }
      const r = await fetch(`${API}/${encodeURIComponent(name)}/intent`, { method: "PUT", headers: { "Content-Type": "application/json" },
                                                                           body: JSON.stringify({ intent, confirm }) });
      const d = await r.json();
      imsg.textContent = r.ok ? (confirm ? "Bekræftet – Claude går videre med skitsen." : "Gemt.") : (d.error || "kunne ikke gemme");
      if (r.ok) { shown = JSON.stringify(d); body.innerHTML = renderIntent(d); }
    }
    sec.querySelector(".intentsave").onclick = () => put(false);
    sec.querySelector(".intentok").onclick = () => put(true);
    poll();
  }

  // new.html#<name>: continue on an existing brief (drawing + understanding)
  const existing = decodeURIComponent(location.hash.slice(1));
  if (existing) openDrawing(existing);
})();
