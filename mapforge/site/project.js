// MapForge: close ("afslut") or reopen a map under Input. The state lives in
// maps/<map>/project.json through the live container's API (/api/project/<map>); a closed map
// takes no new wishes (the drawing tool in #annotate is disabled) and the loop does not run on it.
// PROJ = {map}.
"use strict";
(() => {
  const root = document.getElementById("project");
  if (!root) return;
  const API = `http://localhost:8090/api/project/${encodeURIComponent(PROJ.map)}`;
  const toggle = root.querySelector(".projtoggle"), note = root.querySelector(".projnote");
  const msg = root.querySelector(".projmsg"), draw = document.getElementById("annotate");
  const OPEN_NOTE = note.textContent;
  let closed = false;

  function apply(st) {
    closed = st.state === "closed";
    toggle.disabled = false;
    toggle.textContent = closed ? "↺ Genåbn bane" : "✓ Afslut bane";
    toggle.classList.toggle("primary", closed);
    note.textContent = closed
      ? `Banen er afsluttet${st.changed ? ` (${st.changed})` : ""}: ingen nye ønsker, og loopet kører ikke. Genåbn den for at arbejde videre.`
      : OPEN_NOTE;
    if (draw) {
      draw.classList.toggle("closed", closed);
      draw.querySelectorAll("[data-tool], textarea, .annsave, .anncancel").forEach(el => { el.disabled = closed; });
    }
  }

  async function load() {
    try {
      const r = await fetch(API);
      if (r.ok) apply(await r.json());
    } catch {
      msg.innerHTML = "API'et kører ikke: <code>docker compose up -d live</code>";
    }
  }

  toggle.addEventListener("click", async () => {
    const next = closed ? "open" : "closed";
    if (next === "closed" && !confirm(`Afslut ${PROJ.map}? Tegning slås fra, og loopet kører ikke, før du genåbner banen.`)) return;
    try {
      const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ state: next }) });
      const body = await r.json();
      if (!r.ok) { msg.textContent = body.error || "kunne ikke ændre banens tilstand"; return; }
      apply(body);
      msg.textContent = next === "closed" ? "Banen er afsluttet." : "Banen er genåbnet.";
    } catch {
      msg.innerHTML = "API'et kører ikke: <code>docker compose up -d live</code>";
    }
  });
  load();
})();
