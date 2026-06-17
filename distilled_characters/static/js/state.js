/* ── Simple Reactive State Store ────────────────────────────────── */
const State = {
  _data: {},
  _listeners: {},

  get(key) {
    return this._data[key];
  },

  set(key, value) {
    this._data[key] = value;
    (this._listeners[key] || []).forEach(fn => fn(value));
  },

  on(key, fn) {
    if (!this._listeners[key]) this._listeners[key] = [];
    this._listeners[key].push(fn);
  },

  off(key, fn) {
    if (!this._listeners[key]) return;
    this._listeners[key] = this._listeners[key].filter(f => f !== fn);
  },
};
