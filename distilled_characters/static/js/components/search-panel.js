/* ── Search Panel Component — multi-channel ──────────────────────── */
const SearchPanel = {
  form(character) {
    const channels = [
      { key: 'all', label: '全部渠道', desc: '维基+Open Library图书+DuckDuckGo+Bing，并行搜索覆盖面最广' },
      { key: 'wikipedia', label: 'Wikipedia (英文)', desc: '权威百科，免费API，结构化知识，适合获取人物履历和背景' },
      { key: 'wikipedia_zh', label: '中文维基百科', desc: '中文百科，适合华人相关的资料搜索' },
      { key: 'open_library', label: 'Open Library 图书', desc: '全球最大开源书库，3000万+图书，免费无限制API' },
      { key: 'duckduckgo', label: 'DuckDuckGo', desc: '隐私搜索引擎，适合网页/新闻/访谈搜索' },
      { key: 'bing', label: 'Bing 搜索', desc: '微软Bing公共搜索，适合中英文网页搜索' },
    ];

    return `
      <div>
        <div class="form-group">
          <label class="form-label">搜索关键词</label>
          <input type="text" class="form-input" id="research-query"
            value="${App.escapeHtml(character?.name || '')}" placeholder="输入搜索关键词...">
          <div class="text-xs text-muted mt-1">
            建议搜索组合：{姓名} biography/演讲/访谈/著作/观点/思想 等
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">搜索渠道</label>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;" id="channel-grid">
            ${channels.map((ch, i) => `
              <label class="channel-card ${i === 0 ? 'channel-active' : ''}" data-channel="${ch.key}"
                     onclick="SearchPanel._selectChannel('${ch.key}')">
                <input type="radio" name="channel" value="${ch.key}" ${i === 0 ? 'checked' : ''} style="display:none;">
                <div class="channel-card-title">${ch.label}</div>
                <div class="channel-card-desc">${ch.desc}</div>
              </label>
            `).join('')}
          </div>
        </div>

        <button class="btn btn-primary" onclick="SearchPanel.search()" style="width:100%;">开始调研</button>
        <div id="search-results" class="mt-3"></div>
      </div>
    `;
  },

  _selectChannel(key) {
    document.querySelectorAll('.channel-card').forEach(card => {
      card.classList.toggle('channel-active', card.dataset.channel === key);
      const radio = card.querySelector('input[type="radio"]');
      if (radio) radio.checked = card.dataset.channel === key;
    });
  },

  async search() {
    const query = document.getElementById('research-query')?.value || '';
    const checkedRadio = document.querySelector('input[name="channel"]:checked');
    const channel = checkedRadio?.value || 'all';
    const charId = CharacterDetail._charId;
    const resultsDiv = document.getElementById('search-results');

    const channelLabels = {
      all: '全部渠道', wikipedia: 'Wikipedia', wikipedia_zh: '中文维基',
      open_library: 'Open Library', duckduckgo: 'DuckDuckGo', bing: 'Bing',
      searxng: 'SearXNG',
    };
    resultsDiv.innerHTML = `<div class="loading-center"><div class="spinner"></div> 正在通过 <strong>${channelLabels[channel] || channel}</strong> 搜索...</div>`;

    try {
      const res = await fetch(`/api/characters/${charId}/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query_override: query, max_results: 10, channel }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      if (data.materials_added > 0) {
        App.showToast(`从 ${channelLabels[channel]} 导入 ${data.materials_added} 条素材`, 'success');
        CharacterDetail._loadMaterials();
        App.closeModal();
      } else {
        resultsDiv.innerHTML = `
          <div class="empty-state" style="padding:32px 20px;">
            <div class="empty-state-title">未找到相关内容</div>
            <div class="empty-state-desc">建议：尝试更具体的中英文关键词，或切换到「全部渠道」并行搜索</div>
          </div>`;
      }
    } catch (e) {
      resultsDiv.innerHTML = `<div class="empty-state"><div class="empty-state-title">搜索失败</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },
};
