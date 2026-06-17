/* ── Character List Component ───────────────────────────────────── */
const CharacterList = {
  async render(container) {
    container.innerHTML = `
      <div class="page-header">
        <div>
          <div class="page-title">人物列表</div>
          <div class="page-subtitle">管理和蒸馏你的思想人物</div>
        </div>
        <button class="btn btn-primary" onclick="CharacterList.showCreate()">+ 添加人物</button>
      </div>
      <div class="search-bar">
        <input type="text" class="search-input" id="char-search" placeholder="搜索人物姓名或描述..." oninput="CharacterList.onSearch()">
      </div>
      <div id="char-grid" class="card-grid"></div>
    `;

    await this.load('');
  },

  async load(query) {
    const grid = document.getElementById('char-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="loading-center"><div class="spinner"></div>加载中...</div>';

    try {
      const chars = await API.characters.list(query);
      if (!chars.length) {
        grid.innerHTML = `
          <div class="empty-state" style="grid-column: 1/-1;">
            <div class="empty-state-icon">🏮</div>
            <div class="empty-state-title">还没有蒸馏人物</div>
            <div class="empty-state-desc">添加一个你感兴趣的人物，开始蒸馏TA的思维模型吧</div>
            <button class="btn btn-primary mt-3" onclick="CharacterList.showCreate()">+ 添加第一个人物</button>
          </div>`;
        return;
      }

      grid.innerHTML = chars.map(c => {
        const isExpired = c.status === 'expired';
        const rowClass = isExpired ? ' char-card-expired' : '';
        return `
        <div class="card char-card${rowClass}" id="char-card-${c.id}">
          <div class="char-card-header">
            <div class="char-card-name" onclick="App.navigate('/characters/${c.id}')" style="cursor:pointer;" title="查看详情">${App.escapeHtml(c.name)}</div>
            <div class="flex-center gap-1">
              ${isExpired ? '<span class="badge" style="background:var(--bg-secondary);color:var(--text-muted);">已失效</span>' : ''}
            </div>
          </div>
          <div class="char-card-desc">${App.escapeHtml(c.description || '暂无描述')}</div>
          <div class="char-card-meta">
            <span>${App.statusBadge(c.status)}</span>
            <span>📄 ${c.material_count || 0} 条素材</span>
            <span>🕐 ${App.formatDate(c.updated_at)}</span>
          </div>
          <div class="char-card-actions" style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">
            <button class="btn btn-secondary btn-xs" onclick="event.stopPropagation(); App.navigate('/characters/${c.id}')">查看</button>
            ${isExpired
              ? `<button class="btn btn-xs btn-secondary" onclick="event.stopPropagation(); CharacterList._restoreChar('${c.id}')">恢复生效</button>`
              : `<button class="btn btn-xs btn-secondary" onclick="event.stopPropagation(); CharacterList._expireChar('${c.id}')">设为失效</button>`}
            <button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); CharacterList.exportCharacter('${c.id}', '${App.escapeHtml(c.name).replace(/'/g, "\\'")}')">导出</button>
            <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); CharacterList._deleteChar('${c.id}', '${App.escapeHtml(c.name).replace(/'/g, "\\'")}')">删除</button>
          </div>
        </div>`;
      }).join('');
    } catch (e) {
      grid.innerHTML = `<div class="empty-state" style="grid-column: 1/-1;"><div class="empty-state-title">加载失败</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },

  onSearch() {
    const q = document.getElementById('char-search')?.value || '';
    this.load(q);
  },

  showCreate() {
    App.openModal('添加人物', `
      <form onsubmit="CharacterList.create(event)" id="char-create-form">
        <div class="form-group">
          <label class="form-label">姓名 *</label>
          <input type="text" class="form-input" name="name" required placeholder="人物姓名">
        </div>
        <div class="form-group">
          <label class="form-label">别名</label>
          <input type="text" class="form-input" name="aliases" placeholder="逗号分隔">
        </div>
        <div class="form-group">
          <label class="form-label">领域</label>
          <input type="text" class="form-input" name="fields" placeholder="如：科技、哲学、商业，逗号分隔">
        </div>
        <div class="form-group">
          <label class="form-label">简介</label>
          <textarea class="form-textarea" name="description" placeholder="简短描述这个人物..."></textarea>
        </div>
        <button type="submit" class="btn btn-primary">确认添加</button>
      </form>
    `);
  },

  async create(event) {
    event.preventDefault();
    const form = document.getElementById('char-create-form');
    const data = {
      name: form.name.value.trim(),
      aliases: form.aliases.value.split(',').map(s => s.trim()).filter(Boolean),
      fields: form.fields.value.split(',').map(s => s.trim()).filter(Boolean),
      description: form.description.value.trim(),
    };
    try {
      await API.characters.create(data);
      App.closeModal();
      App.showToast('人物创建成功', 'success');
      await CharacterList.load(document.getElementById('char-search')?.value || '');
    } catch (e) {
      App.showToast(`创建失败: ${e.message}`, 'error');
    }
  },

  async _expireChar(id) {
    try {
      await API.characters.update(id, { status: 'expired' });
      App.showToast('已设为失效', 'info');
      await this.load(document.getElementById('char-search')?.value || '');
    } catch (e) { App.showToast(`操作失败: ${e.message}`, 'error'); }
  },

  async _restoreChar(id) {
    try {
      await API.characters.update(id, { status: 'materials_ready' });
      App.showToast('已恢复生效', 'success');
      await this.load(document.getElementById('char-search')?.value || '');
    } catch (e) { App.showToast(`操作失败: ${e.message}`, 'error'); }
  },

  async _deleteChar(id, name) {
    if (!confirm(`确定永久删除「${name}」及其所有素材和蒸馏记录吗？此操作不可撤销。`)) return;
    try {
      await API.characters.del(id);
      App.showToast(`已删除「${name}」`, 'success');
      await this.load(document.getElementById('char-search')?.value || '');
    } catch (e) { App.showToast(`删除失败: ${e.message}`, 'error'); }
  },

  // ── Export Character Distillation ─────────────────────────────
  async exportCharacter(charId, charName) {
    try {
      const dists = await API.distillation.list(charId);
      const completed = dists.filter(d => d.status === 'completed');
      if (!completed.length) {
        App.showToast(`「${charName}」暂无完成的蒸馏成果，请先运行蒸馏`, 'error');
        return;
      }

      completed.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
      const latest = completed[0];
      this._showExportModal(latest, charName);
    } catch (e) {
      App.showToast(`导出失败: ${e.message}`, 'error');
    }
  },

  _showExportModal(distillation, charName) {
    const distId = distillation.id;
    const version = distillation.version || 1;
    const dateStr = App.formatDate(distillation.created_at);

    App.openModal(`导出蒸馏成果 · ${App.escapeHtml(charName)}`, `
      <div style="margin-bottom:16px;">
        <div class="text-sm text-muted">蒸馏版本 #${version} &middot; ${dateStr}</div>
        <div class="text-sm text-muted" style="margin-top:4px;">
          素材来源: ${(distillation.source_material_ids || []).length} 条
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:10px;">
        <button class="btn btn-primary" style="justify-content:center;padding:12px;font-size:15px;" onclick="CharacterList._downloadJson('${distId}', '${App.escapeHtml(charName)}')">
          <span style="margin-right:8px;">📋</span> 导出 JSON 格式
          <span class="text-xs" style="margin-left:8px;opacity:0.7;">&mdash; 完整结构化数据，适合程序复用</span>
        </button>
        <button class="btn btn-secondary" style="justify-content:center;padding:12px;font-size:15px;" onclick="CharacterList._downloadMarkdown('${distId}', '${App.escapeHtml(charName)}')">
          <span style="margin-right:8px;">📝</span> 导出 Markdown 格式
          <span class="text-xs" style="margin-left:8px;opacity:0.7;">&mdash; 可读文档，适合阅读和分享</span>
        </button>
      </div>

      <div style="margin-top:16px;padding:10px;background:var(--bg-secondary);border-radius:6px;font-size:12px;color:var(--text-muted);">
        <strong>导出内容包含：</strong>
        <ul style="margin:6px 0 0 16px;padding:0;line-height:1.8;">
          <li>表达DNA（语言调性、句式节奏、修辞习惯）</li>
          <li>思维工具（分析框架、推理范式、归因逻辑）</li>
          <li>决策规则（优先级、取舍原则、启发式）</li>
          <li>世界观（注意力焦点、底层假设、价值排序）</li>
          <li>边界演化（反模式、能力边界、认知演化）</li>
          <li>选题方向（置信排序的话题推荐）</li>
        </ul>
      </div>
    `);
  },

  async _downloadJson(distId, charName) {
    try {
      const data = await API.distillation.exportJson(distId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${charName.replace(/\s+/g, '')}-蒸馏成果.json`; a.click();
      URL.revokeObjectURL(url);
      App.closeModal();
      App.showToast(`「${charName}」JSON 已下载`, 'success');
    } catch (e) {
      App.showToast(`下载失败: ${e.message}`, 'error');
    }
  },

  async _downloadMarkdown(distId, charName) {
    try {
      const md = await API.distillation.exportMarkdown(distId);
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${charName.replace(/\s+/g, '')}-蒸馏成果.md`; a.click();
      URL.revokeObjectURL(url);
      App.closeModal();
      App.showToast(`「${charName}」Markdown 已下载`, 'success');
    } catch (e) {
      App.showToast(`下载失败: ${e.message}`, 'error');
    }
  },
};
