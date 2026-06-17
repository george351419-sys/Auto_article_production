/* ── Material Upload Component ──────────────────────────────────── */
const MaterialUpload = {
  _selectedFiles: [],
  _activeMethod: null,

  form() {
    return `
      <div class="upload-methods" id="upload-methods">
        <div class="upload-method" data-method="file" onclick="MaterialUpload.showFileUpload()">
          <div class="upload-method-icon">📁</div>
          <div class="upload-method-label">上传文件</div>
          <div class="upload-method-desc">上传 PDF / DOCX / TXT / Markdown / XMind 等文件</div>
        </div>
        <div class="upload-method" data-method="paste" onclick="MaterialUpload.showPaste()">
          <div class="upload-method-icon">📝</div>
          <div class="upload-method-label">粘贴文本</div>
          <div class="upload-method-desc">直接粘贴文章、访谈等文本内容</div>
        </div>
        <div class="upload-method" data-method="url" onclick="MaterialUpload.showUrl()">
          <div class="upload-method-icon">🔗</div>
          <div class="upload-method-label">网址抓取</div>
          <div class="upload-method-desc">输入URL自动提取正文内容</div>
        </div>
      </div>
      <div id="upload-form-area"></div>
    `;
  },

  _setActiveMethod(method) {
    this._activeMethod = method;
    document.querySelectorAll('#upload-methods .upload-method').forEach(el => {
      el.classList.toggle('upload-method-active', el.dataset.method === method);
    });
  },

  // ── File Upload ──────────────────────────────────────────

  showFileUpload() {
    this._setActiveMethod('file');
    const area = document.getElementById('upload-form-area');
    this._selectedFiles = [];
    area.innerHTML = `
      <form onsubmit="MaterialUpload.submitFiles(event)" id="file-upload-form">
        <div class="file-drop-zone" id="file-drop-zone">
          <div class="file-drop-icon">📂</div>
          <div class="file-drop-label">拖拽文件到此处，或点击选择</div>
          <div class="file-drop-desc">支持 PDF / DOCX / TXT / Markdown / XMind 等格式，可同时选择多个文件</div>
          <input type="file" id="file-input" multiple accept=".pdf,.docx,.doc,.txt,.md,.markdown,.csv,.json,.html,.htm,.xmind,.xmnd" style="display:none;" onchange="MaterialUpload.onFilesSelected(event)">
          <button type="button" class="btn btn-secondary mt-2" onclick="document.getElementById('file-input').click()">选择文件</button>
        </div>
        <div id="file-list" class="mt-2"></div>
        <div class="flex-center gap-2 mt-3">
          <div class="form-group" style="flex:1;">
            <label class="form-label">素材类型</label>
            <select class="form-input" name="source_type" id="file-source-type">
              <option value="fragment_expression">自动检测</option>
              <option value="systematic_output">系统著作</option>
              <option value="improv_expression">即兴表达</option>
              <option value="decision_behavior">决策行为</option>
              <option value="fragment_expression">碎片表达</option>
              <option value="third_party">他者视角</option>
              <option value="timeline">时间线</option>
            </select>
          </div>
          <div class="form-group" style="flex:1;">
            <label class="form-label">置信度</label>
            <select class="form-input" name="confidence" id="file-confidence">
              <option value="B">B</option>
              <option value="A">A</option>
              <option value="S">S</option>
              <option value="C">C</option>
            </select>
          </div>
        </div>
        <button type="submit" class="btn btn-primary" id="file-submit-btn" disabled>上传文件</button>
      </form>
    `;

    // Drag and drop
    const dropZone = document.getElementById('file-drop-zone');
    ['dragenter', 'dragover'].forEach(ev => {
      dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.add('file-drop-active'); });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.remove('file-drop-active'); });
    });
    dropZone.addEventListener('drop', (e) => {
      this._selectedFiles = Array.from(e.dataTransfer.files);
      this._renderFileList();
    });
  },

  onFilesSelected(event) {
    this._selectedFiles = Array.from(event.target.files);
    this._renderFileList();
  },

  _renderFileList() {
    const container = document.getElementById('file-list');
    const btn = document.getElementById('file-submit-btn');
    if (!container) return;

    if (this._selectedFiles.length === 0) {
      container.innerHTML = '';
      if (btn) btn.disabled = true;
      return;
    }

    if (btn) btn.disabled = false;

    const totalSize = this._selectedFiles.reduce((s, f) => s + f.size, 0);
    const sizeStr = totalSize < 1024 * 1024
      ? (totalSize / 1024).toFixed(1) + ' KB'
      : (totalSize / 1024 / 1024).toFixed(1) + ' MB';

    container.innerHTML = `
      <div class="file-list-header flex-center" style="justify-content:space-between;">
        <strong>已选择 ${this._selectedFiles.length} 个文件</strong>
        <span class="text-sm text-muted">共 ${sizeStr}</span>
      </div>
      ${this._selectedFiles.map((f, i) => `
        <div class="file-item flex-center" style="justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border);">
          <div class="flex-center gap-2">
            <span>${this._fileIcon(f.name)}</span>
            <span>${App.escapeHtml(f.name)}</span>
          </div>
          <div class="flex-center gap-2">
            <span class="text-xs text-muted">${(f.size / 1024).toFixed(1)} KB</span>
            <button type="button" class="btn-icon" onclick="MaterialUpload._removeFile(${i})" title="移除">✕</button>
          </div>
        </div>
      `).join('')}
    `;
  },

  _fileIcon(name) {
    const ext = (name || '').split('.').pop().toLowerCase();
    const icons = { pdf: '📕', docx: '📘', doc: '📘', txt: '📄', md: '📝', csv: '📊', json: '📋', html: '🌐', xmind: '🧠', xmnd: '🧠' };
    return icons[ext] || '📎';
  },

  _removeFile(index) {
    this._selectedFiles.splice(index, 1);
    this._renderFileList();
    // Update file input
    const dt = new DataTransfer();
    this._selectedFiles.forEach(f => dt.items.add(f));
    document.getElementById('file-input').files = dt.files;
  },

  async submitFiles(event) {
    event.preventDefault();
    if (this._selectedFiles.length === 0) {
      App.showToast('请先选择文件', 'error');
      return;
    }

    const formData = new FormData();
    this._selectedFiles.forEach(f => formData.append('files', f));
    formData.append('source_type', document.getElementById('file-source-type')?.value || 'fragment_expression');
    formData.append('confidence', document.getElementById('file-confidence')?.value || 'B');

    // Show progress
    const btn = document.getElementById('file-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = '上传中...'; }

    try {
      const res = await fetch(`/api/characters/${CharacterDetail._charId}/materials/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }
      const result = await res.json();
      if (result.uploaded > 0) {
        App.showToast(`成功上传 ${result.uploaded} 个文件`, 'success');
      }
      if (result.failed > 0) {
        const errDetail = result.errors.map(e => `${e.filename}: ${e.error}`).join('; ');
        App.showToast(`${result.failed} 个文件上传失败: ${errDetail}`, 'error', 8000);
      }
      App.closeModal();
      CharacterDetail._loadMaterials();
    } catch (e) {
      App.showToast(`上传失败: ${e.message}`, 'error');
    }
  },

  // ── Paste ────────────────────────────────────────────────

  showPaste() {
    this._setActiveMethod('paste');
    const area = document.getElementById('upload-form-area');
    area.innerHTML = `
      <form onsubmit="MaterialUpload.submitPaste(event)">
        <div class="form-group">
          <label class="form-label">标题</label>
          <input type="text" class="form-input" name="title" placeholder="素材标题">
        </div>
        <div class="form-group">
          <label class="form-label">内容</label>
          <textarea class="form-textarea" name="content" required placeholder="在此粘贴文本..." style="min-height:200px;"></textarea>
        </div>
        <div class="flex-center gap-2">
          <div class="form-group" style="flex:1;">
            <label class="form-label">素材类型</label>
            <select class="form-input" name="source_type">
              <option value="fragment_expression">碎片表达</option>
              <option value="systematic_output">系统著作</option>
              <option value="improv_expression">即兴表达</option>
              <option value="decision_behavior">决策行为</option>
              <option value="third_party">他者视角</option>
              <option value="timeline">时间线</option>
            </select>
          </div>
          <div class="form-group" style="flex:1;">
            <label class="form-label">置信度</label>
            <select class="form-input" name="confidence">
              <option value="B">B</option>
              <option value="S">S</option>
              <option value="A">A</option>
              <option value="C">C</option>
            </select>
          </div>
        </div>
        <button type="submit" class="btn btn-primary">保存素材</button>
      </form>
    `;
  },

  // ── URL ─────────────────────────────────────────────────

  showUrl() {
    this._setActiveMethod('url');
    const area = document.getElementById('upload-form-area');
    area.innerHTML = `
      <form onsubmit="MaterialUpload.submitUrl(event)">
        <div class="form-group">
          <label class="form-label">标题</label>
          <input type="text" class="form-input" name="title" placeholder="素材标题">
        </div>
        <div class="form-group">
          <label class="form-label">网址</label>
          <input type="url" class="form-input" name="url" required placeholder="https://...">
        </div>
        <div class="form-group">
          <label class="form-label">备注/手动输入内容（可选）</label>
          <textarea class="form-textarea" name="content" placeholder="如果网址无法自动抓取，可在此粘贴内容"></textarea>
        </div>
        <button type="submit" class="btn btn-primary">保存素材</button>
      </form>
    `;
  },

  // ── Submits ─────────────────────────────────────────────

  async submitPaste(event) {
    event.preventDefault();
    const f = event.target;
    const data = {
      title: f.title.value.trim() || '手动输入素材',
      raw_content: f.content.value.trim(),
      source_type: f.source_type.value,
      confidence: f.confidence.value,
    };
    try {
      await API.materials.create(CharacterDetail._charId, data);
      App.closeModal();
      App.showToast('素材已添加', 'success');
      CharacterDetail._loadMaterials();
    } catch (e) {
      App.showToast(`保存失败: ${e.message}`, 'error');
    }
  },

  async submitUrl(event) {
    event.preventDefault();
    const f = event.target;
    const data = {
      title: f.title.value.trim() || '网页抓取素材',
      url: f.url.value.trim(),
      raw_content: f.content.value.trim() || '（待自动抓取）',
      source_type: 'third_party',
      confidence: 'B',
    };
    try {
      await API.materials.create(CharacterDetail._charId, data);
      App.closeModal();
      App.showToast('素材已添加', 'info');
      CharacterDetail._loadMaterials();
    } catch (e) {
      App.showToast(`保存失败: ${e.message}`, 'error');
    }
  },
};
