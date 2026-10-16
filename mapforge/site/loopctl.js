// MapForge: the loop's controls on a map page - "Skip the current iteration" (POST
// /api/loop/<map>/skip; the loop goes to Decide at its next step or simulation batch) and a
// live line with the loop's step (GET /api/loop/<map>, every 10 s).
"use strict";
(() => {
  const API = "http://localhost:8090/api/loop";
  for (const btn of document.querySelectorAll("[data-skip]")) {
    const map = btn.dataset.skip, msg = btn.parentElement.querySelector(".skipmsg");
    const show = st => {
      if (!st) return;
      btn.disabled = st.status !== "running" || !!st.skip;
      msg.textContent = st.skip ? `Skip requested ${st.skip.time}: the loop goes to Decide at its next step or batch.`
        : st.status === "running" ? `Now: iteration ${st.iteration}, ${st.step}` : `The loop is ${st.status || "not started"}.`;
    };
    const poll = async () => {
      try { show(await (await fetch(`${API}/${encodeURIComponent(map)}`)).json()); }
      catch { msg.innerHTML = "The live API is not running: <code>docker compose up -d live</code>"; }
    };
    btn.addEventListener("click", async () => {
      if (!confirm("Skip the current iteration? The simulation stops after the batch that is running, and Decide gets your open wishes without a new measurement.")) return;
      try {
        const r = await fetch(`${API}/${encodeURIComponent(map)}/skip`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({reason: "skipped from the map page"})});
        const body = await r.json();
        if (!r.ok) { msg.textContent = body.error || "could not skip"; return; }
        poll();
      } catch { msg.innerHTML = "The live API is not running: <code>docker compose up -d live</code>"; }
    });
    poll(); setInterval(poll, 10000);
  }
})();
