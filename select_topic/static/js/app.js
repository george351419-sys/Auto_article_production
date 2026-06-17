/** app.js — Main application controller */
const App = {
  state: {
    topics: [],
    selectedId: null,
    filterStatus: '',
    filterGrade: '',
    filterSourceType: '',
    searchText: '',
  },

  async init() {
    this.bindEvents();
    await this.loadTopics();
    await this.refreshCollectStatus();
    // Auto-select first topic
    if (this.state.topics.length > 0) {
      this.selectTopic(this.state.topics[0].id);
    }
  },

  bindEvents() {
    document.getElementById('btnImport').addEventListener('click', () => this.openImportModal());
    document.getElementById('btnRefresh').addEventListener('click', () => this.loadTopics());
    document.getElementById('btnAutoCollect').addEventListener('click', () => this.triggerCollection());
    document.getElementById('searchInput').addEventListener('input', (e) => {
      this.state.searchText = e.target.value;
      this.loadTopics();
    });
    document.getElementById('filterStatus').addEventListener('change', (e) => {
      this.state.filterStatus = e.target.value;
      this.loadTopics();
    });
    document.getElementById('filterGrade').addEventListener('change', (e) => {
      this.state.filterGrade = e.target.value;
      this.loadTopics();
    });
    document.getElementById('filterSourceType').addEventListener('change', (e) => {
      this.state.filterSourceType = e.target.value;
      this.loadTopics();
    });
  },

  // ── Data loading ───────────────────────────────────────────────────
  async loadTopics() {
    const params = { limit: 100 };
    if (this.state.filterStatus) params.status = this.state.filterStatus;
    if (this.state.filterGrade) params.grade = this.state.filterGrade;
    if (this.state.filterSourceType) params.source_type = this.state.filterSourceType;
    if (this.state.searchText) params.search = this.state.searchText;

    try {
      this.state.topics = await API.listTopics(params);
      this.renderTopicList();
    } catch (e) {
      console.error('Load topics failed:', e);
    }
  },

  async selectTopic(id) {
    this.state.selectedId = id;
    try {
      const topic = await API.getTopic(id);
      this.renderTopicDetail(topic);
      this.renderTopicList(); // refresh selection highlight
    } catch (e) {
      console.error('Get topic failed:', e);
    }
  },

  // ── Topic actions ──────────────────────────────────────────────────
  async scoreTopic(id) {
    const positioning = document.getElementById('globalPositioning')?.value || 'business_tech';
    const weightMode = document.getElementById('globalWeightMode')?.value || 'new_account';
    const platform = document.getElementById('globalPlatform')?.value || 'wechat';
    try {
      this.showLoading('打分中...');
      await API.scoreTopic(id, weightMode, platform, positioning);
      await this.selectTopic(id);
      await this.loadTopics();
      this.hideLoading();
    } catch (e) {
      this.hideLoading();
      alert('打分失败: ' + e.message);
    }
  },

  async matchTopic(id) {
    try {
      this.showLoading('匹配中...');
      await API.matchTopic(id, true);
      await this.selectTopic(id);
      await this.loadTopics();
      this.hideLoading();
    } catch (e) {
      this.hideLoading();
      alert('匹配失败: ' + e.message);
    }
  },

  async scoreAndMatch(id) {
    const positioning = document.getElementById('globalPositioning')?.value || 'business_tech';
    const weightMode = document.getElementById('globalWeightMode')?.value || 'new_account';
    const platform = document.getElementById('globalPlatform')?.value || 'wechat';
    try {
      this.showLoading('打分中...');
      await API.scoreTopic(id, weightMode, platform, positioning);
      this.showLoading('匹配中...');
      await API.matchTopic(id, true);
      await this.selectTopic(id);
      await this.loadTopics();
      this.hideLoading();
    } catch (e) {
      this.hideLoading();
      alert('处理失败: ' + e.message);
    }
  },

  async reviewTopic(id, action) {
    const note = action === 'discard' ? prompt('淘汰原因（可选）：') : '';
    try {
      await API.reviewTopic(id, action, note || '');
      await this.selectTopic(id);
      await this.loadTopics();
    } catch (e) {
      alert('操作失败: ' + e.message);
    }
  },

  async resetTopic(id) {
    // Create a new topic with same content to reset state
    try {
      const topic = await API.getTopic(id);
      const newTopic = await API.createTopic({
        title: topic.title,
        source_url: topic.source_url || '',
        raw_content: topic.raw_content || '',
      });
      await this.loadTopics();
      this.selectTopic(newTopic.id);
    } catch (e) {
      alert('重置失败: ' + e.message);
    }
  },

  // ── Import modal ───────────────────────────────────────────────────
  openImportModal() {
    if (document.getElementById('importModal')) return;
    const div = document.createElement('div');
    div.innerHTML = renderImportModal();
    document.body.appendChild(div.firstElementChild);
    document.getElementById('importTitle')?.focus();
    // Bind tab switching
    const tabs = document.querySelectorAll('.modal-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const tabName = tab.dataset.tab;
        document.querySelectorAll('.modal-tab-panel').forEach(p => p.style.display = 'none');
        document.getElementById(`tab-${tabName}`).style.display = '';
        if (tabName === 'url') document.getElementById('importUrlInput')?.focus();
        else document.getElementById('importTitle')?.focus();
      });
    });
    // Bind URL import button
    document.getElementById('btnUrlImport')?.addEventListener('click', () => this.importFromURL());
  },

  closeImportModal() {
    document.getElementById('importModal')?.remove();
  },

  async importAndPipeline() {
    const title = document.getElementById('importTitle').value.trim();
    const sourceUrl = document.getElementById('importUrl').value.trim();
    const content = document.getElementById('importContent').value.trim();
    const positioning = document.getElementById('importPositioning')?.value || 'business_tech';
    const platform = document.getElementById('importPlatform').value;
    const weightMode = document.getElementById('importWeightMode').value;

    if (!title) { alert('请输入话题标题'); return; }

    try {
      this.showLoading('导入并处理中...');
      const result = await API.runPipeline({
        title, source_url: sourceUrl, raw_content: content,
        platform, weight_mode: weightMode, positioning,
      });
      this.closeImportModal();
      await this.loadTopics();
      if (result.status === 'filtered') {
        alert(`话题被过滤：${result.filter_reason}\n标题：${result.title || ''}`);
        this.hideLoading();
        return;
      }
      this.selectTopic(result.topic_id);
      this.hideLoading();
    } catch (e) {
      this.hideLoading();
      alert('导入失败: ' + e.message);
    }
  },

  // ── URL Import ──────────────────────────────────────────────────────
  async importFromURL() {
    const url = document.getElementById('importUrlInput').value.trim();
    const positioning = document.getElementById('importPositioningUrl')?.value || 'business_tech';
    const platform = document.getElementById('importPlatform')?.value || 'wechat';
    const weightMode = document.getElementById('importWeightMode')?.value || 'new_account';

    if (!url) { alert('请输入链接地址'); return; }

    try {
      this.showLoading('正在从链接提取话题...');
      const result = await API.importURL({ url, weight_mode: weightMode, platform, positioning });
      this.closeImportModal();
      this.hideLoading();

      if (result.status === 'filtered') {
        alert(`话题被过滤：${result.filter_reason}\n标题：${result.title || ''}`);
        return;
      }
      await this.loadTopics();
      if (result.topic_id) this.selectTopic(result.topic_id);
    } catch (e) {
      this.hideLoading();
      alert('链接导入失败: ' + e.message);
    }
  },

  // ── Auto collection ─────────────────────────────────────────────────
  async triggerCollection() {
    const btn = document.getElementById('btnAutoCollect');
    btn.disabled = true;
    btn.textContent = '采集中...';
    this.showLoading('正在采集全网热点，预计需要 30-40 秒...');
    // Count existing auto topics before triggering
    const beforeCount = (await API.listTopics({ source_type: 'auto', limit: 200 })).length;
    try {
      const result = await API.triggerCollection();
      this.hideLoading();
      if (result.status === 'already_running') {
        alert('采集任务正在进行中，请稍后再试');
      } else if (result.status === 'completed') {
        await this.loadTopics();
        await this.refreshCollectStatus();
        const afterCount = this.state.topics.filter(t => t.source_type === 'auto').length;
        const newCount = afterCount - beforeCount;
        if (newCount === 0) {
          alert('本轮采集未发现 80 分以上的选题，暂无可入库选题。');
        } else if (this.state.topics.length > 0 && !this.state.selectedId) {
          this.selectTopic(this.state.topics[0].id);
        }
      } else {
        alert('采集失败: ' + (result.error || '未知错误'));
      }
    } catch (e) {
      this.hideLoading();
      alert('采集触发失败: ' + e.message);
    }
    btn.disabled = false;
    btn.textContent = '\u{1F4E1} 采集热点';
  },

  async refreshCollectStatus() {
    try {
      const s = await API.getCollectStatus();
      const el = document.getElementById('collectStatus');
      if (!el) return;
      if (s.running) {
        el.textContent = '采集中...';
        el.className = 'collect-status running';
      } else if (s.last_run) {
        el.textContent = `上次: ${fmtTime(s.last_run)}`;
        el.className = 'collect-status';
      } else {
        el.textContent = '';
      }
    } catch (e) { /* ignore */ }
  },

  // ── Rendering ──────────────────────────────────────────────────────
  renderTopicList() {
    const el = document.getElementById('topicList');
    const topics = this.state.topics;
    if (!topics.length) {
      el.innerHTML = `<div class="empty-state">
        <div class="empty-icon">📋</div>
        <p>暂无选题</p>
        <p class="empty-hint">点击「手动导入」添加第一条选题</p>
      </div>`;
      return;
    }
    el.innerHTML = topics.map(t => renderTopicItem(t, this.state.selectedId)).join('');
    // Bind click events
    el.querySelectorAll('.topic-item').forEach(item => {
      item.addEventListener('click', () => this.selectTopic(item.dataset.id));
    });
  },

  renderTopicDetail(topic) {
    document.getElementById('detailPanel').innerHTML = renderDetail(topic);
  },

  showLoading(msg) {
    let el = document.getElementById('globalLoading');
    if (!el) {
      el = document.createElement('div');
      el.id = 'globalLoading';
      el.className = 'loading-overlay';
      document.body.appendChild(el);
    }
    el.innerHTML = `<div class="loading-spinner"></div><p>${msg}</p>`;
    el.style.display = 'flex';
  },

  hideLoading() {
    const el = document.getElementById('globalLoading');
    if (el) el.style.display = 'none';
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
