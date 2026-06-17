/* ── Character Detail Component ─────────────────────────────────── */
const CharacterDetail = {
  _charId: null,
  _char: null,
  _activeTab: 'materials',

  async render(container, id) {
    this._charId = id;
    try {
      this._char = await API.characters.get(id);
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-title">人物不存在</div></div>`;
      return;
    }

    const c = this._char;
    container.innerHTML = `
      <div class="detail-page">
      <div class="page-header">
        <div>
          <a href="#/" style="display:inline-flex;align-items:center;gap:4px;font-size:13px;color:var(--text-secondary);margin-bottom:8px;">← 人物列表</a>
          <div class="page-title">${App.escapeHtml(c.name)}</div>
          <div class="page-subtitle">${App.escapeHtml(c.description || '暂无简介')}</div>
        </div>
        <div class="flex-center gap-2">
          <button class="btn btn-secondary btn-sm" onclick="CharacterDetail.editModal()">编辑信息</button>
          <button class="btn btn-primary" onclick="CharacterDetail.startDistillation()">开始蒸馏</button>
        </div>
      </div>

      <div class="tabs">
        <button class="tab ${this._activeTab === 'materials' ? 'active' : ''}" data-tab="materials">素材管理</button>
        <button class="tab ${this._activeTab === 'distillations' ? 'active' : ''}" data-tab="distillations">蒸馏历史</button>
        <button class="tab ${this._activeTab === 'results' ? 'active' : ''}" data-tab="results">结果查看</button>
      </div>
      <div id="tab-content"></div>
      </div>
    `;

    container.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        this._activeTab = tab.dataset.tab;
        this.render(container, id);
      });
    });
    await this._renderTab(this._activeTab);
  },

  async _renderTab(tab) {
    const content = document.getElementById('tab-content');
    if (!content) return;

    if (tab === 'materials') {
      content.innerHTML = `
        <div id="mat-toolbar" style="display:flex;justify-content:space-between;margin-bottom:0;flex-wrap:wrap;gap:8px;align-items:center;padding:12px 0;">
          <div class="flex-center gap-2" style="flex-wrap:wrap;">
            <select id="mat-filter-type" class="form-input" style="width:auto;" onchange="CharacterDetail._filterMaterials()">
              <option value="">全部类型</option>
              <option value="systematic_output">系统著作</option>
              <option value="improv_expression">即兴表达</option>
              <option value="decision_behavior">决策行为</option>
              <option value="fragment_expression">碎片表达</option>
              <option value="third_party">他者视角</option>
              <option value="timeline">时间线</option>
            </select>
            <select id="mat-filter-confidence" class="form-input" style="width:auto;" onchange="CharacterDetail._filterMaterials()">
              <option value="">全部级别</option>
              <option value="S">S 级</option>
              <option value="A">A 级</option>
              <option value="B">B 级</option>
              <option value="C">C 级</option>
            </select>
          </div>
          <div class="flex-center gap-2">
            <button class="btn btn-secondary btn-sm" onclick="CharacterDetail.showSearchPanel()">网络调研</button>
            <button class="btn btn-primary btn-sm" onclick="CharacterDetail.showUploadModal()">添加素材</button>
          </div>
        </div>
        <div id="mat-batch-bar" class="hidden" style="background:var(--accent-light);border:1px solid var(--accent);border-radius:var(--radius-sm);padding:8px 14px;margin-bottom:0;display:none;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
          <span class="text-sm" id="mat-batch-count">已选 0 条</span>
          <div class="flex-center gap-2">
            <button class="btn btn-danger btn-xs" onclick="CharacterDetail._batchDelete()">删除所选</button>
            <button class="btn btn-secondary btn-xs" onclick="CharacterDetail._clearSelection()">取消选择</button>
          </div>
        </div>
        <div id="materials-list" class="materials-scrollable"></div>
      `;
      await this._loadMaterials();
    } else if (tab === 'distillations') {
      content.innerHTML = '<div id="distillations-list" class="loading-center"><div class="spinner"></div> 加载中...</div>';
      await this._loadDistillations();
    } else if (tab === 'results') {
      content.innerHTML = '<div id="results-container" class="loading-center"><div class="spinner"></div> 加载中...</div>';
      await this._loadLatestResult();
    }
  },

  _selectedMats: new Set(),

  async _loadMaterials() {
    const container = document.getElementById('materials-list');
    if (!container) return;
    const sourceType = document.getElementById('mat-filter-type')?.value || '';
    const confidence = document.getElementById('mat-filter-confidence')?.value || '';

    try {
      const materials = await API.materials.list(this._charId, sourceType, confidence);
      if (!materials.length) {
        container.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-title">还没有素材</div>
            <div class="empty-state-desc">添加人物相关的文章、访谈、语录等素材，或使用网络调研自动收集</div>
          </div>`;
        return;
      }

      const allSelected = materials.every(m => this._selectedMats.has(m.id));
      const someSelected = materials.some(m => this._selectedMats.has(m.id));
      const selCount = materials.filter(m => this._selectedMats.has(m.id)).length;

      container.innerHTML = `
        <div class="flex-center gap-2" style="margin-bottom:6px;font-size:13px;color:var(--text-muted);">
          <label class="flex-center gap-1" style="cursor:pointer;">
            <input type="checkbox" id="mat-select-all" ${allSelected ? 'checked' : ''} onchange="CharacterDetail._toggleSelectAll()">
            全选
          </label>
          <span>| 共 ${materials.length} 条素材${selCount > 0 ? ` · 已选 ${selCount} 条` : ''}</span>
          ${!sourceType && !confidence ? `
            <span>| 按类型：${['systematic_output','improv_expression','decision_behavior','fragment_expression','third_party','timeline'].map(t => {
              const cnt = materials.filter(m => m.source_type === t).length;
              return cnt > 0 ? `<a href="javascript:void(0)" onclick="CharacterDetail._filterByType('${t}')" style="margin-left:4px;">${App.sourceTypeLabel(t)}(${cnt})</a>` : '';
            }).join('')}</span>
          ` : ''}
        </div>` +
        materials.map(m => `
        <div class="material-item">
          <div class="material-header">
            <div class="flex-center gap-2" style="flex:1;min-width:0;" onclick="CharacterDetail._toggleMaterial('${m.id}')">
              <input type="checkbox" class="mat-checkbox" data-mat-id="${m.id}" ${this._selectedMats.has(m.id) ? 'checked' : ''} onclick="event.stopPropagation(); CharacterDetail._onCheckbox('${m.id}', this.checked)" style="flex-shrink:0;">
              <span style="font-size:11px;color:var(--text-muted);flex-shrink:0;">${App.sourceTypeLabel(m.source_type)}</span>
              <span class="material-title">${App.escapeHtml(m.title || '未命名素材')}</span>
              ${m.confidence ? App.confidenceBadge(m.confidence) : ''}
            </div>
            <div class="material-meta">
              <span class="text-xs text-muted">${m.word_count || 0} 字</span>
              <button class="btn-icon" onclick="event.stopPropagation(); CharacterDetail._deleteMaterial('${m.id}')" title="删除">×</button>
            </div>
          </div>
          <div class="material-body hidden" id="mat-body-${m.id}">${App.escapeHtml(m.raw_content || '')}</div>
        </div>
      `).join('');

      // Update batch bar
      this._updateBatchBar();
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-title">加载失败</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },

  _filterByType(type) {
    document.getElementById('mat-filter-type').value = type;
    this._filterMaterials();
  },

  _onCheckbox(matId, checked) {
    if (checked) this._selectedMats.add(matId);
    else this._selectedMats.delete(matId);
    this._updateBatchBar();
  },

  _toggleSelectAll() {
    const checked = document.getElementById('mat-select-all')?.checked;
    document.querySelectorAll('.mat-checkbox').forEach(cb => {
      cb.checked = checked;
      if (checked) this._selectedMats.add(cb.dataset.matId);
      else this._selectedMats.delete(cb.dataset.matId);
    });
    this._updateBatchBar();
  },

  _updateBatchBar() {
    const bar = document.getElementById('mat-batch-bar');
    const countEl = document.getElementById('mat-batch-count');
    if (!bar || !countEl) return;
    const count = this._selectedMats.size;
    if (count > 0) {
      bar.style.display = 'flex';
      countEl.textContent = `已选 ${count} 条`;
    } else {
      bar.style.display = 'none';
    }
  },

  _clearSelection() {
    this._selectedMats.clear();
    this._loadMaterials();
  },

  async _batchDelete() {
    const count = this._selectedMats.size;
    if (count === 0) return;
    if (!confirm(`确定删除所选 ${count} 条素材吗？此操作不可撤销。`)) return;
    let done = 0, failed = 0;
    for (const id of this._selectedMats) {
      try { await API.materials.del(id); done++; }
      catch (e) { failed++; }
    }
    this._selectedMats.clear();
    App.showToast(`已删除 ${done} 条${failed > 0 ? `，${failed} 条失败` : ''}`, failed > 0 ? 'error' : 'success');
    await this._loadMaterials();
  },

  _toggleMaterial(id) {
    const body = document.getElementById(`mat-body-${id}`);
    if (body) body.classList.toggle('hidden');
  },

  async _deleteMaterial(id) {
    if (!confirm('删除这条素材？')) return;
    try { await API.materials.del(id); App.showToast('已删除', 'info'); await this._loadMaterials(); }
    catch (e) { App.showToast(`删除失败: ${e.message}`, 'error'); }
  },

  _filterMaterials() { this._loadMaterials(); },

  // ── Distillations tab ──────────────────────────────────────────

  async _loadDistillations() {
    const container = document.getElementById('distillations-list');
    if (!container) return;
    try {
      const dists = await API.distillation.list(this._charId);
      if (!dists.length) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📜</div><div class="empty-state-title">没有蒸馏记录</div><div class="empty-state-desc">添加素材后点击「开始蒸馏」</div></div>`;
        return;
      }

      const expiredCount = dists.filter(d => d.status === 'expired').length;

      let html = '';
      if (expiredCount > 0) {
        html += `<div class="flex-center gap-2 mb-3" style="justify-content:flex-end;">
          <span class="text-xs text-muted">${expiredCount} 条失效记录</span>
          <button class="btn btn-danger btn-xs" onclick="CharacterDetail._cleanupExpired()">清理失效记录</button>
        </div>`;
      }

      html += dists.map(d => {
        const completed = d.status === 'completed';
        const failed = d.status === 'failed';
        const running = d.status === 'in_progress';
        const expired = d.status === 'expired';
        const stepResults = d.step_results || {};
        const rowClass = expired ? ' distillation-expired' : '';
        return `
        <div class="dist-run-card${rowClass}">
          <div class="dist-run-header">
            <div>
              <strong>蒸馏 #${d.version || '?'}</strong>
              <span class="text-xs text-muted"> · ${d.pipeline_version || 'v1'}</span>
              ${expired ? '<span class="badge" style="background:var(--bg-secondary);color:var(--text-muted);margin-left:6px;">已失效</span>' : ''}
            </div>
            <span class="dist-run-status ${d.status}">${running ? '运行中' : completed ? '已完成' : failed ? '失败' : expired ? '已失效' : d.status}</span>
          </div>
          <div class="text-xs text-muted">${(d.source_material_ids || []).length} 条素材 · ${App.formatDate(d.created_at)}</div>
          ${completed ? `<button class="btn btn-secondary btn-sm mt-2" onclick="CharacterDetail._showResult('${d.id}')">查看结果 →</button>` : ''}
          ${failed ? `<div class="text-xs mt-2" style="color:var(--danger);">${App.escapeHtml(d.error_message || '未知错误')}</div>` : ''}
          ${running ? `
            <div class="mt-2" id="live-steps-${d.id}">
              ${Object.keys(stepResults).length > 0 ? DistillationRun.renderProgress(d.id, stepResults) : '<div class="spinner" style="width:14px;height:14px;display:inline-block;margin-right:8px;"></div>蒸馏进行中...'}
            </div>
            <button class="btn btn-danger btn-xs mt-2" onclick="CharacterDetail._cancelDistillation('${d.id}')">取消蒸馏</button>
          ` : ''}
          ${(completed || failed) ? `<button class="btn btn-xs btn-secondary mt-2" style="margin-left:8px;" onclick="CharacterDetail._deleteDistillation('${d.id}')">删除记录</button>` : ''}
          ${expired ? `
            <button class="btn btn-xs btn-secondary mt-2" style="margin-left:8px;" onclick="CharacterDetail._restoreDistillation('${d.id}')">恢复生效</button>
            <button class="btn btn-xs btn-danger mt-2" style="margin-left:8px;" onclick="CharacterDetail._deleteDistillation('${d.id}')">删除</button>
          ` : ''}
          ${completed ? `<button class="btn btn-xs btn-secondary mt-2" style="margin-left:4px;color:var(--text-muted);" onclick="CharacterDetail._expireDistillation('${d.id}')">设为失效</button>` : ''}
          ${failed ? `<button class="btn btn-xs btn-secondary mt-2" style="margin-left:4px;color:var(--text-muted);" onclick="CharacterDetail._expireDistillation('${d.id}')">设为失效</button>` : ''}
        </div>`;
      }).join('');
      container.innerHTML = html;
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-title">加载失败</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },

  // ── Results tab ────────────────────────────────────────────────

  _buildResultVersionOptions(completed, selectedId) {
    return completed.map((d, i) => {
      const isExpired = d.status === 'expired';
      const style = isExpired ? ' style="color:var(--text-muted);"' : '';
      return `<option value="${d.id}" ${d.id === selectedId ? 'selected' : ''}${style}>#${d.version || i + 1} · ${App.formatDate(d.created_at)}${isExpired ? ' (已失效)' : ''}</option>`;
    }).join('');
  },

  _renderResultsShell(selOpts) {
    return `
        <div class="results-toolbar">
          <label class="results-version-picker">
            <span class="results-version-label">结果版本</span>
            <select class="form-input results-version-select" id="result-version-select" onchange="CharacterDetail._selectResultVersion()">${selOpts}</select>
          </label>
        </div>
        <div class="results-body">
          <div id="inline-result"></div>
        </div>`;
  },

  // ── Navigate to results tab for a specific distillation ─────────
  _showResult(distillationId) {
    this._activeTab = 'results';
    const main = document.getElementById('main-content');
    this.render(main, this._charId).then(() => {
      setTimeout(() => this._loadLatestResult(distillationId), 100);
    });
  },

  async _loadLatestResult(distillationId) {
    const container = document.getElementById('results-container');
    if (!container) return;
    try {
      const dists = await API.distillation.list(this._charId);
      const completed = dists.filter(d => d.status === 'completed' || d.status === 'expired');
      const activeCompleted = dists.filter(d => d.status === 'completed');
      if (!activeCompleted.length) {
        container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📊</div><div class="empty-state-title">暂无结果</div><div class="empty-state-desc">运行一次蒸馏后再来查看</div></div>`;
        return;
      }

      // If a specific distillation is requested, show that one; otherwise show latest
      let target = activeCompleted[0];
      if (distillationId) {
        target = activeCompleted.find(d => d.id === distillationId) || activeCompleted[0];
      }

      const selOpts = this._buildResultVersionOptions(completed, target.id);
      container.className = 'results-view';
      container.innerHTML = this._renderResultsShell(selOpts);
      ResultViewer.renderInline(document.getElementById('inline-result'), target);
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-title">加载失败</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },

  async _selectResultVersion() {
    const select = document.getElementById('result-version-select');
    if (!select) return;
    const distId = select.value;
    const container = document.getElementById('results-container');
    if (!container) return;
    try {
      const d = await API.distillation.get(distId);
      const completed = (await API.distillation.list(this._charId))
        .filter(d2 => d2.status === 'completed' || d2.status === 'expired');
      const selOpts = this._buildResultVersionOptions(completed, distId);
      container.className = 'results-view';
      container.innerHTML = this._renderResultsShell(selOpts);
      ResultViewer.renderInline(document.getElementById('inline-result'), d);
    } catch (e) {
      App.showToast(`加载结果失败: ${e.message}`, 'error');
    }
  },

  // ── Actions ────────────────────────────────────────────────────

  showUploadModal() { App.openModal('添加素材', MaterialUpload.form()); },

  showSearchPanel() { App.openModal('网络调研', SearchPanel.form(this._char)); },

  editModal() {
    const c = this._char;
    App.openModal('编辑人物信息', `
      <form onsubmit="CharacterDetail._updateChar(event)">
        <div class="form-group"><label class="form-label">姓名</label>
          <input type="text" class="form-input" name="name" value="${App.escapeHtml(c.name||'')}" required></div>
        <div class="form-group"><label class="form-label">简介</label>
          <textarea class="form-textarea" name="description">${App.escapeHtml(c.description||'')}</textarea></div>
        <button type="submit" class="btn btn-primary">保存</button>
      </form>`);
  },

  async _updateChar(event) {
    event.preventDefault();
    const form = event.target;
    try {
      await API.characters.update(this._charId, { name: form.name.value.trim(), description: form.description.value.trim() });
      App.closeModal(); App.showToast('已更新', 'success');
      this.render(document.getElementById('main-content'), this._charId);
    } catch (e) { App.showToast(`更新失败: ${e.message}`, 'error'); }
  },

  async startDistillation() {
    const mats = await API.materials.list(this._charId);
    if (!mats.length) { App.showToast('请先添加素材', 'error'); return; }
    try {
      const res = await API.distillation.start(this._charId);
      App.showToast(`蒸馏已启动`, 'success');
      DistillationRun.connect(res.distillation_id, () => {
        const main = document.getElementById('main-content');
        CharacterDetail.render(main, this._charId);
      });
      this._activeTab = 'distillations';
      this.render(document.getElementById('main-content'), this._charId);
    } catch (e) { App.showToast(`启动失败: ${e.message}`, 'error'); }
  },

  async _cancelDistillation(distId) {
    if (!confirm('确定取消这个正在进行的蒸馏吗？')) return;
    try {
      await API.distillation.cancelOrDelete(distId);
      App.showToast('已取消并删除', 'success');
      await this._loadDistillations();
    } catch (e) { App.showToast(`取消失败: ${e.message}`, 'error'); }
  },

  async _deleteDistillation(distId) {
    if (!confirm('确定删除这条蒸馏记录吗？此操作不可撤销。')) return;
    try {
      await API.distillation.cancelOrDelete(distId);
      App.showToast('已删除', 'info');
      await this._loadDistillations();
    } catch (e) { App.showToast(`删除失败: ${e.message}`, 'error'); }
  },

  async _expireDistillation(distId) {
    try {
      await API.distillation.updateStatus(distId, 'expired');
      App.showToast('已设为失效', 'info');
      await this._loadDistillations();
    } catch (e) { App.showToast(`操作失败: ${e.message}`, 'error'); }
  },

  async _restoreDistillation(distId) {
    try {
      await API.distillation.updateStatus(distId, 'completed');
      App.showToast('已恢复生效', 'success');
      await this._loadDistillations();
    } catch (e) { App.showToast(`操作失败: ${e.message}`, 'error'); }
  },

  async _cleanupExpired() {
    if (!confirm('确定永久删除所有失效记录吗？此操作不可撤销。')) return;
    try {
      const res = await API.distillation.cleanupExpired(this._charId);
      App.showToast(`已清理 ${res.deleted} 条失效记录`, 'success');
      await this._loadDistillations();
    } catch (e) { App.showToast(`清理失败: ${e.message}`, 'error'); }
  },
};
