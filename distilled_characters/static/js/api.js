/* ── API Client ─────────────────────────────────────────────────── */
const API = {
  base: '/api',

  async get(path) {
    const res = await fetch(`${this.base}${path}`);
    if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
    return res.json();
  },

  async post(path, body = {}) {
    const res = await fetch(`${this.base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  },

  async put(path, body = {}) {
    const res = await fetch(`${this.base}${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`);
    return res.json();
  },

  async patch(path, body = {}) {
    const res = await fetch(`${this.base}${path}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  },

  async del(path) {
    const res = await fetch(`${this.base}${path}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`DELETE ${path}: ${res.status}`);
    return res.json();
  },

  // ── Character ─────────────────────────────────────────────
  characters: {
    list(q = '') { return API.get(`/characters?q=${encodeURIComponent(q)}`); },
    get(id) { return API.get(`/characters/${id}`); },
    create(data) { return API.post('/characters', data); },
    update(id, data) { return API.put(`/characters/${id}`, data); },
    del(id) { return API.del(`/characters/${id}`); },
  },

  // ── Materials ─────────────────────────────────────────────
  materials: {
    list(charId, sourceType = '', confidence = '') {
      let q = '';
      if (sourceType) q += `&source_type=${sourceType}`;
      if (confidence) q += `&confidence=${confidence}`;
      return API.get(`/characters/${charId}/materials?${q}`);
    },
    get(id) { return API.get(`/materials/${id}`); },
    create(charId, data) { return API.post(`/characters/${charId}/materials`, data); },
    update(id, data) { return API.put(`/materials/${id}`, data); },
    del(id) { return API.del(`/materials/${id}`); },
  },

  // ── Distillation ──────────────────────────────────────────
  distillation: {
    start(charId) { return API.post(`/characters/${charId}/distill`); },
    list(charId) { return API.get(`/characters/${charId}/distillations`); },
    get(id) { return API.get(`/distillations/${id}`); },
    layer(id, name) { return API.get(`/distillations/${id}/layer/${name}`); },
    exportJson(id) { return API.get(`/distillations/${id}/export/json`); },
    async exportMarkdown(id) {
      const res = await fetch(`${API.base}/distillations/${id}/export/markdown`);
      if (!res.ok) throw new Error(`GET /distillations/${id}/export/markdown: ${res.status}`);
      return res.text();
    },
    cancelOrDelete(id) { return API.del(`/distillations/${id}`); },
    updateStatus(id, status) { return API.put(`/distillations/${id}/status`, { status }); },
    cleanupExpired(charId) { return API.del(`/characters/${charId}/distillations/expired`); },
    updateLayers(id, layers) { return API.put(`/distillations/${id}/layers`, { layers }); },
    updateLayer(id, layerName, data) { return API.patch(`/distillations/${id}/layers/${layerName}`, data); },
  },

  // ── Pipeline ──────────────────────────────────────────────
  pipeline: {
    steps() { return API.get('/pipeline/steps'); },
    run(stepName, context) { return API.post('/pipeline/run', { step_name: stepName, context }); },
  },

  // ── Modules ───────────────────────────────────────────────
  modules: {
    list() { return API.get('/modules'); },
    get(name) { return API.get(`/modules/${name}`); },
    run(name, context) { return API.post(`/modules/${name}/run`, context); },
  },

  // ── Search ────────────────────────────────────────────────
  research(charId, query = '', maxResults = 10) {
    return API.post(`/characters/${charId}/research`, { query_override: query, max_results: maxResults });
  },

  // ── Config ────────────────────────────────────────────────
  config: {
    get() { return API.get('/config'); },
    update(data) { return API.put('/config', data); },
    llmBackends() { return API.get('/config/llm/backends'); },
    testLlm(data) { return API.post('/config/llm/test', data); },
    llmTypes() { return API.get('/config/llm/types'); },
  },
};
