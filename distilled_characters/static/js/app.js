/* ── App Router & Shell ──────────────────────────────────────────── */
const App = {
  _currentPage: null,

  init() {
    this._setupRouting();
    this._handleRoute();
  },

  _setupRouting() {
    window.addEventListener('hashchange', () => this._handleRoute());
    document.querySelectorAll('.nav-item').forEach(el => {
      el.addEventListener('click', () => setTimeout(() => this._updateNav(), 50));
    });
  },

  _handleRoute() {
    const hash = location.hash || '#/';
    const main = document.getElementById('main-content');
    this._updateNav();
    main.innerHTML = '';

    try {
      const match = this._matchRoute(hash);
      if (match.page === 'home') CharacterList.render(main);
      else if (match.page === 'character_detail') CharacterDetail.render(main, match.params.id);
      else if (match.page === 'settings') Settings.render(main);
      else if (match.page === 'distillation_result') ResultViewer.render(main, match.params.id);
      else main.innerHTML = '<div class="empty-state"><div class="empty-state-icon">?</div><div class="empty-state-title">页面不存在</div></div>';
    } catch (e) {
      console.error('Route error:', e);
      main.innerHTML = `<div class="empty-state"><div class="empty-state-title">加载错误</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },

  _matchRoute(hash) {
    hash = hash.replace('#', '') || '/';
    const charMatch = hash.match(/^\/characters\/([^/]+)$/);
    if (charMatch) return { page: 'character_detail', params: { id: charMatch[1] } };
    const distMatch = hash.match(/^\/distillations\/([^/]+)$/);
    if (distMatch) return { page: 'distillation_result', params: { id: distMatch[1] } };
    if (hash === '/settings') return { page: 'settings' };
    return { page: 'home' };
  },

  _updateNav() {
    const hash = location.hash || '#/';
    document.querySelectorAll('.nav-item').forEach(el => {
      el.classList.toggle('active', hash.startsWith(el.dataset.route));
    });
  },

  navigate(hash) { location.hash = hash; },

  // ── Modal ────────────────────────────────────────────────────
  openModal(title, bodyHtml) {
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-close').onclick = () => this.closeModal();
    document.getElementById('modal-overlay').onclick = (e) => {
      if (e.target === document.getElementById('modal-overlay')) this.closeModal();
    };
  },
  closeModal() { document.getElementById('modal-overlay').classList.add('hidden'); },

  // ── Toast ────────────────────────────────────────────────────
  showToast(msg, type = 'info', duration = 3000) {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), duration);
  },

  // ── Helpers ──────────────────────────────────────────────────
  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  formatDate(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    return d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  },

  statusBadge(status) {
    const map = {
      created: '待采集', materials_ready: '可蒸馏', distilling: '蒸馏中',
      completed: '已完成', failed: '失败', in_progress: '运行中', pending: '等待中',
      expired: '已失效',
    };
    return `<span class="char-card-status status-${status}"></span>${map[status] || status}`;
  },

  confidenceBadge(level) {
    const cls = level === 'S' ? 'badge-s' : level === 'A' ? 'badge-a' : level === 'B' ? 'badge-b' : 'badge-c';
    return `<span class="badge ${cls}">${level}</span>`;
  },

  sourceTypeLabel(type) {
    const map = {
      systematic_output: '系统著作', improv_expression: '即兴表达', decision_behavior: '决策行为',
      fragment_expression: '碎片表达', third_party: '他者视角', timeline: '时间线',
    };
    return map[type] || type || '未分类';
  },

  truncate(str, len = 200) {
    if (!str) return '';
    return str.length > len ? str.slice(0, len) + '...' : str;
  },
};
