/* ── Result Viewer Component ────────────────────────────────────── */
const ResultViewer = {
  _distillationId: null,

  async render(container, distillationId) {
    this._distillationId = distillationId;
    try {
      const d = await API.distillation.get(distillationId);
      container.innerHTML = `
        <div class="page-header">
          <div>
            <a href="#/" class="text-sm text-muted" style="display:inline-flex;align-items:center;gap:4px;margin-bottom:8px;">← 返回人物列表</a>
            <div class="page-title">${App.escapeHtml(d.character_name || '蒸馏结果')}</div>
            <div class="page-subtitle">${App.formatDate(d.created_at)} · 版本 ${d.version || 1}</div>
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn btn-secondary btn-sm" onclick="ResultViewer.exportMarkdown('${distillationId}')">导出 Markdown</button>
            <button class="btn btn-secondary btn-sm" onclick="ResultViewer.exportJson('${distillationId}')">导出 JSON</button>
          </div>
        </div>
        <div class="result-tabs-bar">
          <div id="result-tabs" class="tabs tabs--layers">
            <button class="tab active" data-layer="expression_dna">表达DNA</button>
            <button class="tab" data-layer="thinking_tools">思维工具</button>
            <button class="tab" data-layer="decision_rules">决策规则</button>
            <button class="tab" data-layer="worldview">世界观</button>
            <button class="tab" data-layer="boundaries_evolution">边界演化</button>
            <button class="tab" data-layer="suggested_topics">选题方向</button>
          </div>
        </div>
        <div id="result-layer-content"></div>
      `;
      this._setupTabs(container, d.layers || {}, distillationId);
      this._renderLayer('expression_dna', d.layers || {}, distillationId);
      if (d.verification) this._renderVerification(d.verification);
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-title">加载失败</div><div class="empty-state-desc">${e.message}</div></div>`;
    }
  },

  renderInline(container, d) {
    this._distillationId = d.id;
    const layers = d.layers || {};
    container.innerHTML = `
      <div class="result-tabs-bar">
        <div id="result-tabs" class="tabs tabs--layers">
          <button class="tab active" data-layer="expression_dna">表达DNA</button>
          <button class="tab" data-layer="thinking_tools">思维工具</button>
          <button class="tab" data-layer="decision_rules">决策规则</button>
          <button class="tab" data-layer="worldview">世界观</button>
          <button class="tab" data-layer="boundaries_evolution">边界演化</button>
          <button class="tab" data-layer="suggested_topics">选题方向</button>
        </div>
      </div>
      <div id="result-layer-content"></div>
    `;
    this._setupTabs(container, layers, d.id);
    this._renderLayer('expression_dna', layers, d.id);
    if (d.verification) this._renderVerification(d.verification);
  },

  _setupTabs(container, layers, distillationId) {
    container.querySelectorAll('#result-tabs .tab').forEach(tab => {
      tab.addEventListener('click', () => {
        container.querySelectorAll('#result-tabs .tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        this._renderLayer(tab.dataset.layer, layers, distillationId);
      });
    });
  },

  _renderLayer(name, layers, distillationId) {
    const content = document.getElementById('result-layer-content');
    if (!content) return;
    const data = layers[name] || {};
    const isEmpty = !data || (typeof data === 'object' && Object.keys(data).length === 0);

    if (isEmpty) {
      content.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📭</div><div class="empty-state-title">暂无数据</div><div class="empty-state-desc">该层未被成功蒸馏，可能需要更多素材或检查模型配置</div></div>`;
      return;
    }

    const renderers = {
      expression_dna: this._renderExpressionDNA.bind(this),
      thinking_tools: this._renderThinkingTools.bind(this),
      decision_rules: this._renderDecisionRules.bind(this),
      worldview: this._renderWorldview.bind(this),
      boundaries_evolution: this._renderBoundaries.bind(this),
      suggested_topics: this._renderSuggestedTopics.bind(this),
    };
    content.innerHTML = (renderers[name] || (() => `<pre>${JSON.stringify(data, null, 2)}</pre>`))(data);

    // Add edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'btn btn-secondary btn-sm';
    editBtn.style.cssText = 'margin-top:12px;';
    editBtn.textContent = '✏️ 编辑当前层';
    editBtn.onclick = () => this._openLayerEditor(name, data, distillationId);
    content.appendChild(editBtn);
  },

  // ── Layer renderers ────────────────────────────────────────────

  _renderExpressionDNA(d) {
    const lang = d.language_tone ? `
      <div class="result-section"><div class="result-section-title">语言调性</div>
        <div class="result-item"><div class="result-item-desc">${App.escapeHtml(d.language_tone)}</div></div>
      </div>` : '';

    const rhythm = d.sentence_rhythm ? `
      <div class="result-section"><div class="result-section-title">句式节奏</div>
        <div class="result-item"><div class="result-item-desc">${App.escapeHtml(d.sentence_rhythm)}</div></div>
      </div>` : '';

    const arg = d.argumentation_style ? `
      <div class="result-section"><div class="result-section-title">论证风格</div>
        <div class="result-item"><div class="result-item-desc">${App.escapeHtml(d.argumentation_style)}</div></div>
      </div>` : '';

    const habits = (d.rhetorical_habits || []).length ? `
      <div class="result-section"><div class="result-section-title">修辞习惯</div>
        ${(d.rhetorical_habits || []).map(h => `
          <div class="result-item">
            <div class="result-item-title">${App.escapeHtml(h.pattern || (typeof h === 'string' ? h : '未命名'))}</div>
            ${h.description ? `<div class="result-item-desc">${App.escapeHtml(h.description)}</div>` : ''}
            ${(h.examples || []).length ? `<div class="result-item-meta">示例：${h.examples.map(e => `「${App.escapeHtml(e)}」`).join('、')}</div>` : ''}
          </div>`).join('')}
      </div>` : '';

    const phrases = (d.catchphrases || []).length ? `
      <div class="result-section"><div class="result-section-title">口头禅 / 高频短语</div>
        ${(d.catchphrases || []).map(p => `
          <div class="result-item">
            <div class="flex-center" style="justify-content:space-between;">
              <div class="result-item-title">「${App.escapeHtml(p.phrase || p)}」</div>
              ${p.frequency ? `<span class="badge badge-a">×${p.frequency}</span>` : ''}
            </div>
            ${p.context ? `<div class="result-item-desc">${App.escapeHtml(p.context)}</div>` : ''}
          </div>`).join('')}
      </div>` : '';

    const words = (d.high_frequency_vocabulary || d.high_freq_words || []).length ? `
      <div class="result-section"><div class="result-section-title">高频词汇</div>
        <div class="mt-2">${(d.high_frequency_vocabulary || d.high_freq_words || []).map(w =>
          `<span class="badge badge-b" style="margin:3px;">${App.escapeHtml(w.word || w)} ${w.count ? `×${w.count}` : ''}</span>`
        ).join(' ')}</div>
      </div>` : '';

    return `<div class="result-layer">${lang}${rhythm}${arg}${habits}${phrases}${words}</div>`;
  },

  _renderThinkingTools(d) {
    const frameworks = (d.analysis_frameworks || []).length ? `
      <div class="result-section"><div class="result-section-title">分析框架</div>
        <div class="framework-grid">${(d.analysis_frameworks || []).map(f => `
          <div class="framework-card">
            <h4>${App.escapeHtml(f.name || '未命名框架')}</h4>
            <div class="text-sm text-muted">${App.escapeHtml(f.description || '')}</div>
            ${(f.dimensions || []).length ? `<div class="dims">${f.dimensions.map(dim => `<span class="dim-tag">${App.escapeHtml(dim)}</span>`).join('')}</div>` : ''}
          </div>`).join('')}</div>
      </div>` : '';

    const attr = d.attribution_logic || {};
    const attrSection = attr.direction || attr.layers ? `
      <div class="result-section"><div class="result-section-title">归因逻辑</div>
        <div class="result-item">
          <div class="flex flex-wrap gap-3">
            ${attr.direction ? `<div><span class="text-xs text-muted">方向</span> <span>${App.escapeHtml(attr.direction)}</span></div>` : ''}
            ${attr.layers ? `<div><span class="text-xs text-muted">层次</span> <span>${App.escapeHtml(attr.layers)}</span></div>` : ''}
            ${attr.time_perspective ? `<div><span class="text-xs text-muted">时间视角</span> <span>${App.escapeHtml(attr.time_perspective)}</span></div>` : ''}
          </div>
        </div>
      </div>` : '';

    const paradigms = (d.reasoning_paradigms || []).length ? `
      <div class="result-section"><div class="result-section-title">推理范式</div>
        <div class="mt-2">${d.reasoning_paradigms.map(p => `<span class="badge badge-a" style="margin:3px;">${App.escapeHtml(p)}</span>`).join(' ')}</div>
      </div>` : '';

    const theories = (d.common_theories || []).length ? `
      <div class="result-section"><div class="result-section-title">常用理论/概念</div>
        <div class="mt-2">${d.common_theories.map(t => `<span class="badge badge-b" style="margin:3px;">${App.escapeHtml(t)}</span>`).join(' ')}</div>
      </div>` : '';

    return `<div class="result-layer">${frameworks}${attrSection}${paradigms}${theories}</div>`;
  },

  _renderDecisionRules(d) {
    const priority = (d.priority_rules || []).length ? `
      <div class="result-section"><div class="result-section-title">优先级规则</div>
        ${(d.priority_rules || []).map(r => `
          <div class="result-item">
            <div class="result-item-title">${App.escapeHtml(r.rule || r)}</div>
            ${r.explanation ? `<div class="result-item-desc">${App.escapeHtml(r.explanation)}</div>` : ''}
          </div>`).join('')}
      </div>` : '';

    const tradeoffs = (d.tradeoff_principles || []).length ? `
      <div class="result-section"><div class="result-section-title">取舍原则</div>
        ${(d.tradeoff_principles || []).map(t => `
          <div class="result-item"><div class="result-item-desc">${App.escapeHtml(t.principle || t)}${t.explanation ? ` — ${App.escapeHtml(t.explanation)}` : ''}</div></div>
        `).join('')}
      </div>` : '';

    const risk = d.risk_tolerance ? `
      <div class="result-section"><div class="result-section-title">风险容忍度</div>
        <div class="result-item"><div class="result-item-desc">${App.escapeHtml(d.risk_tolerance)}</div></div>
      </div>` : '';

    const thresholds = (d.evaluation_thresholds || []).length ? `
      <div class="result-section"><div class="result-section-title">评估阈值</div>
        ${(d.evaluation_thresholds || []).map(t => `
          <div class="result-item">
            <div class="flex-center gap-2">
              <span class="badge badge-s">${App.escapeHtml(t.threshold || t.criterion)}</span>
              <span>${App.escapeHtml(t.context || '')}</span>
            </div>
          </div>`).join('')}
      </div>` : '';

    const heuristics = (d.heuristics || []).length ? `
      <div class="result-section"><div class="result-section-title">决策启发式</div>
        ${(d.heuristics || []).map(h => `
          <div class="result-item">
            <div class="result-item-title">${App.escapeHtml(h.name || h)}</div>
            <div class="result-item-desc">${App.escapeHtml(h.description || '')}</div>
            ${h.when_to_use ? `<div class="result-item-meta">✅ ${App.escapeHtml(h.when_to_use)}</div>` : ''}
            ${h.when_it_fails ? `<div class="result-item-meta" style="color:var(--danger);">⚠️ ${App.escapeHtml(h.when_it_fails)}</div>` : ''}
          </div>`).join('')}
      </div>` : '';

    return `<div class="result-layer">${priority}${tradeoffs}${risk}${thresholds}${heuristics}</div>`;
  },

  _renderWorldview(d) {
    const attention = d.attention_focus ? `
      <div class="result-section"><div class="result-section-title">注意力焦点</div>
        <div class="result-item"><div class="result-item-desc">${App.escapeHtml(d.attention_focus)}</div></div>
      </div>` : '';

    const assumptions = d.fundamental_assumptions || {};
    const hasAssumptions = assumptions.human_nature || assumptions.world_nature || assumptions.time_orientation;
    const assumptionsSection = hasAssumptions ? `
      <div class="result-section"><div class="result-section-title">底层假设</div>
        <div class="framework-grid">
          ${assumptions.human_nature ? `<div class="framework-card"><h4>人性假设</h4><div class="text-sm text-muted">${App.escapeHtml(assumptions.human_nature)}</div></div>` : ''}
          ${assumptions.world_nature ? `<div class="framework-card"><h4>世界假设</h4><div class="text-sm text-muted">${App.escapeHtml(assumptions.world_nature)}</div></div>` : ''}
          ${assumptions.time_orientation ? `<div class="framework-card"><h4>时间观</h4><div class="text-sm text-muted">${App.escapeHtml(assumptions.time_orientation)}</div></div>` : ''}
        </div>
      </div>` : '';

    const values = d.value_hierarchy || [];
    const valueColors = ['#bf5e3b', '#b56f1a', '#3a6b8c', '#24814d', '#6b4e8d', '#b56576', '#4a7c59'];
    const valuesSection = values.length ? `
      <div class="result-section"><div class="result-section-title">价值排序</div>
        <div class="value-bar-container">${values.map((v, i) => `<div class="value-bar-item" style="width:${100/values.length}%;background:${valueColors[i%valueColors.length]};"></div>`).join('')}</div>
        <div class="value-bar-legend">${values.map((v, i) => `<div class="value-legend-item"><span class="value-legend-dot" style="background:${valueColors[i%valueColors.length]};"></span>${i+1}. ${App.escapeHtml(v)}</div>`).join('')}</div>
      </div>` : '';

    const perspective = d.unique_perspective ? `
      <div class="result-section"><div class="result-section-title">独特视角</div>
        <div class="result-item"><div class="result-item-desc">${App.escapeHtml(d.unique_perspective)}</div></div>
      </div>` : '';

    const blindspots = (d.cognitive_blind_spots || []).length ? `
      <div class="result-section"><div class="result-section-title">认知盲区</div>
        ${d.cognitive_blind_spots.map(b => `<div class="result-item"><div class="result-item-desc">${App.escapeHtml(b)}</div></div>`).join('')}
      </div>` : '';

    return `<div class="result-layer">${attention}${assumptionsSection}${valuesSection}${perspective}${blindspots}</div>`;
  },

  _renderBoundaries(d) {
    const antiPatterns = (d.anti_patterns || []).length ? `
      <div class="result-section"><div class="result-section-title">反模式</div>
        ${(d.anti_patterns || []).map(a => `
          <div class="result-item">
            <div class="result-item-title">${App.escapeHtml(a.pattern || a)}</div>
            ${a.explanation ? `<div class="result-item-desc">${App.escapeHtml(a.explanation)}</div>` : ''}
          </div>`).join('')}
      </div>` : '';

    const redLines = (d.value_red_lines || []).length ? `
      <div class="result-section"><div class="result-section-title">价值观底线</div>
        ${(d.value_red_lines || []).map(l => `<div class="result-item"><div class="result-item-desc">${App.escapeHtml(l)}</div></div>`).join('')}
      </div>` : '';

    const boundaries = (d.capability_boundaries || []).length ? `
      <div class="result-section"><div class="result-section-title">能力边界</div>
        ${(d.capability_boundaries || []).map(b => `<div class="result-item"><div class="result-item-desc">${App.escapeHtml(b)}</div></div>`).join('')}
      </div>` : '';

    const taboos = (d.expression_taboos || []).length ? `
      <div class="result-section"><div class="result-section-title">表达禁忌</div>
        ${(d.expression_taboos || []).map(t => `<div class="result-item"><div class="result-item-desc">${App.escapeHtml(t)}</div></div>`).join('')}
      </div>` : '';

    const evolution = (d.cognitive_evolution || []).length ? `
      <div class="result-section"><div class="result-section-title">认知演化</div>
        <div class="evolution-timeline">
          ${(d.cognitive_evolution || []).map(p => `
            <div class="evolution-phase">
              <div class="evolution-phase-period">${App.escapeHtml(p.time_period || '')}</div>
              <div class="evolution-phase-name">${App.escapeHtml(p.phase)}</div>
              ${(p.key_views || []).length ? `<div class="text-sm text-muted">${p.key_views.map(v => App.escapeHtml(v)).join(' · ')}</div>` : ''}
              ${(p.trigger_events || []).length ? `<div class="text-xs mt-1" style="color:var(--accent);">触发：${p.trigger_events.map(e => App.escapeHtml(e)).join('、')}</div>` : ''}
            </div>`).join('')}
        </div>
      </div>` : '';

    return `<div class="result-layer">${antiPatterns}${redLines}${boundaries}${taboos}${evolution}</div>`;
  },

  _renderSuggestedTopics(d) {
    const topics = d || [];
    if (!Array.isArray(topics) || !topics.length) {
      return `<div class="result-layer"><div class="result-section"><div class="result-section-title">推荐话题</div><div class="text-muted">暂无话题推荐</div></div></div>`;
    }

    const sorted = [...topics].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));

    const labelColor = (c) => {
      if (c >= 0.85) return 'var(--success)';
      if (c >= 0.7) return 'var(--accent)';
      return 'var(--warning)';
    };

    const label = (c) => {
      if (c >= 0.85) return '高置信';
      if (c >= 0.7) return '中置信';
      return '较低';
    };

    const topicsHtml = sorted.map((t, i) => `
      <div class="result-item" style="border-left:3px solid ${labelColor(t.confidence || 0)};padding-left:12px;">
        <div class="flex-center" style="justify-content:space-between;margin-bottom:4px;">
          <div class="result-item-title" style="font-size:15px;">${App.escapeHtml(t.topic || '未命名')}</div>
          <div class="flex-center gap-2">
            <span class="badge" style="background:${labelColor(t.confidence || 0)};color:#fff;font-size:11px;">${label(t.confidence || 0)} · ${Math.round((t.confidence || 0) * 100)}%</span>
          </div>
        </div>
        ${t.description ? `<div class="result-item-desc">${App.escapeHtml(t.description)}</div>` : ''}
        <div class="confidence-bar" style="margin:6px 0;background:var(--bg-secondary);border-radius:4px;height:4px;overflow:hidden;">
          <div style="height:100%;width:${Math.round((t.confidence || 0) * 100)}%;background:${labelColor(t.confidence || 0)};border-radius:4px;"></div>
        </div>
        ${t.rationale ? `<div class="text-xs text-muted" style="margin-top:4px;">依据：${App.escapeHtml(t.rationale)}</div>` : ''}
        ${(t.keywords || []).length ? `<div class="mt-2">${t.keywords.map(k => `<span class="badge badge-b" style="margin:2px;">${App.escapeHtml(k)}</span>`).join(' ')}</div>` : ''}
      </div>
    `).join('');

    return `<div class="result-layer">
      <div class="result-section"><div class="result-section-title">推荐话题 (${topics.length})</div></div>
      ${topicsHtml}
    </div>`;
  },

  // ── Layer Editor ──────────────────────────────────────────────

  _openLayerEditor(layerName, currentData, distillationId) {
    const labelMap = {
      expression_dna: '表达DNA',
      thinking_tools: '思维工具',
      decision_rules: '决策规则',
      worldview: '世界观',
      boundaries_evolution: '边界演化',
      suggested_topics: '选题方向',
    };
    const label = labelMap[layerName] || layerName;
    const jsonStr = JSON.stringify(currentData, null, 2);

    App.openModal(`编辑：${label}`,
      `<form onsubmit="ResultViewer._saveLayerEdit(event, '${layerName}', '${distillationId}')">
        <div class="form-group">
          <textarea class="form-textarea" id="layer-edit-textarea" style="min-height:400px;font-family:'SF Mono',monospace;font-size:13px;" required>${App.escapeHtml(jsonStr)}</textarea>
        </div>
        <div class="text-xs text-muted mb-3">直接编辑 JSON，保存后立即生效。</div>
        <div class="flex-center gap-2">
          <button type="submit" class="btn btn-primary">保存</button>
          <button type="button" class="btn btn-secondary" onclick="App.closeModal()">取消</button>
        </div>
      </form>`
    );
  },

  _saveLayerEdit(event, layerName, distillationId) {
    event.preventDefault();
    const textarea = document.getElementById('layer-edit-textarea');
    if (!textarea) return;
    let data;
    try {
      data = JSON.parse(textarea.value);
    } catch (e) {
      App.showToast(`JSON 格式错误: ${e.message}`, 'error');
      return;
    }
    if (typeof data !== 'object' || data === null) {
      App.showToast('内容必须是 JSON 对象或数组', 'error');
      return;
    }
    API.distillation.updateLayer(distillationId, layerName, data)
      .then(() => {
        App.closeModal();
        App.showToast('已保存', 'success');
        // Re-render current layer by re-fetching distillation
        API.distillation.get(distillationId).then(d => {
          const layers = d.layers || {};
          this._renderLayer(layerName, layers, distillationId);
        });
      })
      .catch(e => App.showToast(`保存失败: ${e.message}`, 'error'));
  },

  // ── Verification ──────────────────────────────────────────────

  _renderVerification(v) {
    const content = document.getElementById('result-layer-content');
    if (!content) return;
    const cc = v.cross_consistency || {};
    const bt = v.back_testing || {};
    const bc = v.boundary_compliance || {};

    const html = `
      <div class="result-layer mt-4">
        <div class="result-layer-header">验证报告</div>
        <div class="card-grid">
          <div class="framework-card">
            <h4>交叉一致性</h4>
            <div style="font-size:18px;margin:8px 0;">${cc.passed ? '✅ 通过' : '❌ 未通过'}</div>
            <div class="text-sm text-muted">覆盖率 ${Math.round((cc.coverage_rate || 0) * 100)}%</div>
            ${(cc.issues || []).map(i => `<div class="text-xs mt-1" style="color:var(--danger);">${App.escapeHtml(i)}</div>`).join('')}
          </div>
          <div class="framework-card">
            <h4>已知回测</h4>
            <div style="font-size:18px;margin:8px 0;">${bt.passed ? '✅ 通过' : '❌ 未通过'}</div>
            <div class="text-sm text-muted">匹配率 ${Math.round((bt.match_rate || 0) * 100)}%</div>
            ${(bt.issues || []).map(i => `<div class="text-xs mt-1 text-muted">${App.escapeHtml(i)}</div>`).join('')}
          </div>
          <div class="framework-card">
            <h4>边界合规</h4>
            <div style="font-size:18px;margin:8px 0;">${bc.passed ? '✅ 通过' : '❌ 未通过'}</div>
            ${(bc.issues || []).map(i => `<div class="text-xs mt-1" style="color:var(--danger);">${App.escapeHtml(i)}</div>`).join('')}
          </div>
        </div>
      </div>`;
    content.insertAdjacentHTML('beforeend', html);
  },

  exportJson(distillationId) {
    API.distillation.exportJson(distillationId).then(data => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `distillation-${distillationId.slice(0, 8)}.json`; a.click();
      URL.revokeObjectURL(url);
      App.showToast('JSON 已下载', 'success');
    }).catch(e => App.showToast(`导出失败: ${e.message}`, 'error'));
  },

  exportMarkdown(distillationId) {
    API.distillation.exportMarkdown(distillationId).then(md => {
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `distillation-${distillationId.slice(0, 8)}.md`; a.click();
      URL.revokeObjectURL(url);
      App.showToast('Markdown 已下载', 'success');
    }).catch(e => App.showToast(`导出失败: ${e.message}`, 'error'));
  },
};
