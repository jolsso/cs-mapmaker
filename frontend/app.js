(() => {
  const apiBase = ''; // same origin

  const $ = (id) => document.getElementById(id);
  const out = (el, data) => (el.textContent = JSON.stringify(data, null, 2));

  let state = {
    intent: null,
    layout: null,
    geometry: null,
    export: null,
  };

  const fetchJSON = async (path, body) => {
    const res = await fetch(apiBase + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${path} ${res.status}`);
    return res.json();
  };

  const drawGeometry = (geometry) => {
    const canvas = $('geomCanvas');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!geometry || !geometry.polygons) return;

    // Find bounds
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    for (const poly of geometry.polygons) {
      for (const [x, y] of poly.points) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }

    const pad = 20;
    const w = canvas.width - pad * 2;
    const h = canvas.height - pad * 2;
    const dx = maxX - minX || 1;
    const dy = maxY - minY || 1;
    const scale = Math.min(w / dx, h / dy);

    ctx.save();
    ctx.translate(pad, canvas.height - pad);
    ctx.scale(1, -1); // y-up to y-down
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#6ae3ff';
    ctx.fillStyle = 'rgba(106,227,255,0.12)';

    for (const poly of geometry.polygons) {
      ctx.beginPath();
      poly.points.forEach(([x, y], i) => {
        const sx = (x - minX) * scale;
        const sy = (y - minY) * scale;
        if (i === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  };

  $('btnConcept').addEventListener('click', async () => {
    try {
      const prompt = $('prompt').value.trim();
      const data = await fetchJSON('/concepts', { prompt });
      state.intent = data;
      out($('outConcept'), data);
    } catch (e) {
      out($('outConcept'), { error: String(e) });
    }
  });

  $('btnLayout').addEventListener('click', async () => {
    try {
      if (!state.intent) throw new Error('Run Concept first');
      const data = await fetchJSON('/layouts', state.intent);
      state.layout = data;
      out($('outLayout'), data);
    } catch (e) {
      out($('outLayout'), { error: String(e) });
    }
  });

  $('btnGeometry').addEventListener('click', async () => {
    try {
      if (!state.layout) throw new Error('Run Layout first');
      const data = await fetchJSON('/geometry', state.layout);
      state.geometry = data;
      out($('outGeometry'), data);
      drawGeometry(data);
    } catch (e) {
      out($('outGeometry'), { error: String(e) });
    }
  });

  $('btnExport').addEventListener('click', async () => {
    try {
      if (!state.geometry) throw new Error('Run Geometry first');
      const data = await fetchJSON('/maps', state.geometry);
      state.export = data;
      out($('outExport'), data);
    } catch (e) {
      out($('outExport'), { error: String(e) });
    }
  });

  $('btnAll').addEventListener('click', async () => {
    $('outConcept').textContent = 'Running...';
    $('outLayout').textContent = '';
    $('outGeometry').textContent = '';
    $('outExport').textContent = '';
    try {
      const prompt = $('prompt').value.trim();
      state.intent = await fetchJSON('/concepts', { prompt });
      out($('outConcept'), state.intent);
      state.layout = await fetchJSON('/layouts', state.intent);
      out($('outLayout'), state.layout);
      state.geometry = await fetchJSON('/geometry', state.layout);
      out($('outGeometry'), state.geometry);
      drawGeometry(state.geometry);
      state.export = await fetchJSON('/maps', state.geometry);
      out($('outExport'), state.export);
    } catch (e) {
      out($('outExport'), { error: String(e) });
    }
  });

  $('btnEdit').addEventListener('click', async () => {
    try {
      const prompt = $('editPrompt').value.trim();
      const data = await fetchJSON('/edits', { prompt });
      out($('outEdit'), data);
    } catch (e) {
      out($('outEdit'), { error: String(e) });
    }
  });
})();

