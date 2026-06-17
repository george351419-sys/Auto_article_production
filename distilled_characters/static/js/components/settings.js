/* Settings Component — 只读概览。
 * LLM 配置统一收口到 orchestrator 的「账号管理」（写 .env + shared_config.json）。
 * 本页只展示当前生效的后端，不再提供增删改。
 */
const Settings = {
  async render(container) {
    container.innerHTML = `
      <div class="page-header"><div><div class="page-title">LLM 后端（只读）</div>
        <div class="page-subtitle">配置已统一到编排器的「账号管理」</div>
      </div></div>
      <div id="settings-content" class="loading-center"><div class="spinner"></div></div>
    `;
    try {
      const backends = await API.get('/config/llm/backends');
      const content = document.getElementById('settings-content');
      if (!content) return;

      const rows = (backends || []).map(b => {
        const src = b._source === 'shared_config'
          ? '<span class="badge badge-s">账号管理</span>'
          : '<span class="badge badge-b">本地配置</span>';
        const def = b.is_default ? '<span class="badge badge-a" style="margin-left:6px;">默认</span>' : '';
        return `<div class="backend-row">
          <div class="backend-row-info">
            <div class="flex-center gap-2"><strong>${App.escapeHtml(b.name || '')}</strong>${src}${def}</div>
            <div class="text-xs text-muted">${App.escapeHtml(b.model || '')} · ${App.escapeHtml(b.base_url || '')} · ${App.escapeHtml(b.api_key || '无 Key')}</div>
          </div>
        </div>`;
      }).join('');

      content.innerHTML = `
        <div class="settings-section">
          <div class="settings-section-title">当前生效的 LLM 后端</div>
          ${rows || '<div class="empty-state"><div class="empty-state-icon">🔑</div><div class="empty-state-title">尚未配置任何后端</div><div class="empty-state-desc">请到编排器「账号管理」填入 DeepSeek 或 Qwen 的 API Key</div></div>'}
        </div>
        <div class="settings-section" style="margin-top:24px;">
          <div class="settings-section-title">如何修改</div>
          <ol style="line-height:1.8;font-size:13px;color:var(--text);">
            <li>打开编排器：<a href="http://127.0.0.1:8800/#accounts" target="_blank">http://127.0.0.1:8800/#accounts</a></li>
            <li>在「模型 API Key (.env)」处填入 DeepSeek / Qwen 的 Key 并保存</li>
            <li>本服务会自动读取最新值，无需重启</li>
          </ol>
        </div>
      `;
    } catch (e) {
      const content = document.getElementById('settings-content');
      if (content) content.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-title">加载失败</div><div class="empty-state-desc">${App.escapeHtml(e.message)}</div></div>`;
    }
  },
};
