/** api.js — API layer for topic selection system */
const API = {
  BASE: '',

  async _fetch(url, options = {}) {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  // Topics
  async createTopic(data) {
    return this._fetch('/api/topics', { method: 'POST', body: JSON.stringify(data) });
  },
  async listTopics(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this._fetch(`/api/topics${qs ? '?' + qs : ''}`);
  },
  async getTopic(id) {
    return this._fetch(`/api/topics/${id}`);
  },
  async deleteTopic(id) {
    return this._fetch(`/api/topics/${id}`, { method: 'DELETE' });
  },

  // Scoring
  async scoreTopic(id, weightMode = 'new_account', platform = 'wechat', positioning = 'business_tech') {
    return this._fetch(`/api/topics/${id}/score`, {
      method: 'POST',
      body: JSON.stringify({ weight_mode: weightMode, platform, positioning, use_llm: false }),
    });
  },

  // Matching
  async matchTopic(id, useLlm = true) {
    return this._fetch(`/api/topics/${id}/match`, {
      method: 'POST',
      body: JSON.stringify({ use_llm: useLlm }),
    });
  },

  // Review
  async reviewTopic(id, action, note = '') {
    return this._fetch(`/api/topics/${id}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, note }),
    });
  },

  // Pipeline (one-click)
  async runPipeline(data) {
    return this._fetch('/api/pipeline/run', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // Celebrities
  async listCelebrities() {
    return this._fetch('/api/celebrities');
  },

  // Config
  async getWeights() {
    return this._fetch('/api/config/weights');
  },
  async updateWeights(data) {
    return this._fetch('/api/config/weights', { method: 'PUT', body: JSON.stringify(data) });
  },

  // Collection
  async triggerCollection() {
    return this._fetch('/api/collect/trigger', { method: 'POST' });
  },
  async getCollectStatus() {
    return this._fetch('/api/collect/status');
  },
  async importURL(data) {
    return this._fetch('/api/collect/import-url', { method: 'POST', body: JSON.stringify(data) });
  },
  async getCollectLogs(limit = 20) {
    return this._fetch(`/api/collect/logs?limit=${limit}`);
  },
};
