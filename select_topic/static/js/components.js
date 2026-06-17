/** components.js — UI rendering functions for topic selection system */

// ── Status badges ────────────────────────────────────────────────────────
const STATUS_MAP = {
  pending:   { label: '待处理', cls: 'badge-gray' },
  scored:    { label: '已打分', cls: 'badge-blue' },
  matched:   { label: '已匹配', cls: 'badge-purple' },
  confirmed: { label: '已确认', cls: 'badge-green' },
  discarded: { label: '已淘汰', cls: 'badge-red' },
  backup:    { label: '暂存备选', cls: 'badge-yellow' },
};

const GRADE_COLORS = { S: '#f59e0b', A: '#10b981', B: '#3b82f6', C: '#ef4444' };

function statusBadge(status) {
  const s = STATUS_MAP[status] || { label: status, cls: 'badge-gray' };
  return `<span class="status-badge ${s.cls}">${s.label}</span>`;
}

// ── Topic list item ──────────────────────────────────────────────────────
function renderTopicItem(t, selectedId) {
  const score = t.total_score ? `${t.total_score}分` : '-';
  const grade = t.grade || '';
  const gradeClr = GRADE_COLORS[grade] || '#999';
  const isSelected = t.id === selectedId;
  const matchInfo = (t.matches && t.matches.length > 0)
    ? t.matches.map(m => m.celebrity_name).join(', ')
    : '未匹配';
  const sourceLabel = t.source_type === 'auto' ? '<span class="source-indicator auto">自动</span>' : '<span class="source-indicator manual">手动</span>';

  return `
    <div class="topic-item ${isSelected ? 'selected' : ''}" data-id="${t.id}">
      <div class="topic-item-header">
        <span class="topic-title-text">${escHtml(t.title)}</span>
        ${sourceLabel}
        ${statusBadge(t.status)}
      </div>
      <div class="topic-item-meta">
        <span style="color:${gradeClr};font-weight:600;">${grade || '-'}</span>
        <span>${score}</span>
        <span class="topic-match-preview">${matchInfo}</span>
      </div>
      <div class="topic-item-time">${fmtTime(t.created_at)}</div>
    </div>`;
}

// ── Detail panel ─────────────────────────────────────────────────────────
function renderDetail(topic) {
  const t = topic;
  const score = t.score;
  const matches = t.matches || [];
  // Parse source material
  let sourceMaterials = [];
  try { sourceMaterials = JSON.parse(t.source_material || '[]'); } catch { /* stay empty */ }
  if (!Array.isArray(sourceMaterials)) sourceMaterials = [];

  const sourceLabel = t.source_type === 'auto' ? '自动采集' : '手动导入';
  const heatLabels = { hot: '🔥 高热', warm: '🌡 温热', normal: '平常' };

  return `
    <div class="detail-section">
      <h3>话题信息</h3>
      <div class="info-grid">
        <div class="info-item"><label>标题</label><span>${escHtml(t.title)}</span></div>
        <div class="info-item"><label>来源</label><span>${sourceLabel} ${t.source_platform ? '· ' + t.source_platform : ''} ${t.heat_level ? heatLabels[t.heat_level] || t.heat_level : ''}</span></div>
        <div class="info-item"><label>状态</label>${statusBadge(t.status)}</div>
        <div class="info-item"><label>时间</label><span>${fmtTime(t.created_at)}</span></div>
        ${t.source_url ? `<div class="info-item"><label>链接</label><span><a href="${escHtml(t.source_url)}" target="_blank">查看原文</a></span></div>` : ''}
      </div>
      ${t.raw_content ? `
        <div class="content-box">
          <label>内容摘要</label>
          <p>${escHtml(t.raw_content).substring(0, 300)}${t.raw_content.length > 300 ? '...' : ''}</p>
        </div>` : ''}
      ${sourceMaterials.length > 0 ? `
        <div class="source-material-section">
          <h4>📎 原文材料 (${sourceMaterials.length})</h4>
          <ul class="source-material-list">
            ${sourceMaterials.map(sm => `
              <li class="source-material-item">
                <a href="${escHtml(sm.url)}" target="_blank">${escHtml(sm.title || sm.url)}</a>
                ${sm.platform ? `<span class="platform-tag">${PLATFORM_LABELS[sm.platform] || sm.platform}</span>` : ''}
              </li>`).join('')}
          </ul>
        </div>` : ''}
    </div>

    ${score ? `
    <div class="detail-section">
      <h3>话题评分 <span class="grade-badge" style="background:${GRADE_COLORS[score.grade] || '#999'}">${score.grade}级 · ${score.total_score}分</span></h3>
      <div class="score-bars">
        ${scoreBar('领域相关性', score.relevance_score, '#6366f1')}
        ${scoreBar('热点时效性', score.timeliness_score, '#f59e0b')}
        ${scoreBar('内容价值延展性', score.value_score, '#10b981')}
        ${scoreBar('合规风险度', score.compliance_score, '#3b82f6')}
        ${scoreBar('赛道竞争度', score.competition_score, '#8b5cf6')}
      </div>
      <div class="score-footer">
        <span>定位: ${score.positioning === 'entertainment' ? '娱乐鸡汤' : '商业科技'}</span>
        <span>权重方案: ${score.weight_mode === 'new_account' ? '新号冷启动' : '老号深度运营'}</span>
        <span>目标平台: ${PLATFORM_LABELS[score.platform] || score.platform}</span>
      </div>
      ${renderBonus(score.bonus_details)}
    </div>` : ''}

    ${matches.length > 0 ? `
    <div class="detail-section">
      <h3>名人匹配 TOP3</h3>
      <div class="match-cards">
        ${matches.map((m, i) => renderMatchCard(m, i)).join('')}
      </div>
    </div>` : ''}

    ${(t.review_logs && t.review_logs.length > 0) ? `
    <div class="detail-section">
      <h3>审核记录</h3>
      <div class="review-logs">
        ${t.review_logs.map(l => `
          <div class="review-log-item">
            <span class="log-action">${ACTION_LABELS[l.action] || l.action}</span>
            <span class="log-note">${escHtml(l.note || '')}</span>
            <span class="log-time">${fmtTime(l.created_at)}</span>
          </div>`).join('')}
      </div>
    </div>` : ''}

    ${renderActions(t)}
  `;
}

function scoreBar(label, value, color) {
  const pct = Math.round(value);
  return `
    <div class="score-bar-row">
      <span class="score-bar-label">${label}</span>
      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:${pct}%;background:${color}"></div>
      </div>
      <span class="score-bar-value">${pct}</span>
    </div>`;
}

function renderBonus(bonusJson) {
  if (!bonusJson) return '';
  let details;
  try { details = JSON.parse(bonusJson); } catch { return ''; }
  if (!details.length) return '';
  return `
    <div class="bonus-details">
      ${details.map(d => `
        <span class="bonus-tag ${d.type}">${d.type === 'bonus' ? '+' : ''}${d.points} ${d.name}</span>
      `).join('')}
    </div>`;
}

function renderMatchCard(m, index) {
  const rankEmoji = ['🥇', '🥈', '🥉'][index] || '';
  const hue = [40, 200, 270][index]; // gold, cyan, purple
  return `
    <div class="match-card" style="border-left: 4px solid hsl(${hue}, 70%, 50%)">
      <div class="match-card-header">
        <span class="match-rank">${rankEmoji} #${index + 1}</span>
        <span class="match-name">${escHtml(m.celebrity_name)}</span>
        <span class="match-score">${m.match_score}分</span>
      </div>
      <div class="match-reason">${escHtml(m.match_reason || '暂无匹配理由')}</div>
    </div>`;
}

function renderActions(t) {
  const canScore = t.status === 'pending';
  const canMatch = t.status === 'scored' || t.status === 'matched';
  const canReview = t.status === 'matched' || t.status === 'scored';

  return `
    <div class="detail-section actions-section">
      <h3>操作</h3>
      <div class="action-buttons">
        ${canScore ? `<button class="btn btn-primary" onclick="App.scoreTopic('${t.id}')">🎯 智能打分</button>` : ''}
        ${canMatch ? `<button class="btn btn-secondary" onclick="App.matchTopic('${t.id}')">🔗 匹配名人</button>` : ''}
        ${canScore && canMatch ? `<button class="btn btn-accent" onclick="App.scoreAndMatch('${t.id}')">⚡ 打分+匹配</button>` : ''}
        ${canReview ? `
          <button class="btn btn-success" onclick="App.reviewTopic('${t.id}', 'confirm')">✅ 确认选题</button>
          <button class="btn btn-warning" onclick="App.reviewTopic('${t.id}', 'backup')">📥 暂存备选</button>
          <button class="btn btn-danger" onclick="App.reviewTopic('${t.id}', 'discard')">🗑 淘汰</button>
        ` : ''}
        ${t.status === 'confirmed' || t.status === 'discarded' || t.status === 'backup' ? `
          <button class="btn btn-secondary" onclick="App.resetTopic('${t.id}')">🔄 重置状态</button>
        ` : ''}
      </div>
    </div>`;
}

// ── Modal / import form ──────────────────────────────────────────────────
function renderImportModal() {
  return `
    <div class="modal-overlay" id="importModal">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-tabs">
            <span class="modal-tab active" data-tab="manual">手动输入</span>
            <span class="modal-tab" data-tab="url">链接导入</span>
          </div>
          <button class="modal-close" onclick="App.closeImportModal()">&times;</button>
        </div>
        <!-- Tab: Manual input -->
        <div class="modal-tab-panel" id="tab-manual">
          <div class="modal-body">
            <div class="form-row">
              <div class="form-group form-group-half">
                <label>定位</label>
                <select id="importPositioning">
                  <option value="business_tech">商业科技</option>
                  <option value="entertainment">娱乐鸡汤</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label>话题标题 *</label>
              <input type="text" id="importTitle" placeholder="输入新闻/热点标题...">
            </div>
            <div class="form-group">
              <label>来源链接</label>
              <input type="url" id="importUrl" placeholder="https://...">
            </div>
            <div class="form-group">
              <label>内容摘要/正文</label>
              <textarea id="importContent" rows="5" placeholder="粘贴新闻内容或核心信息..."></textarea>
            </div>
            <div class="form-group">
              <label>目标平台</label>
              <select id="importPlatform">
                <option value="wechat">公众号</option>
                <option value="toutiao">今日头条</option>
                <option value="xiaohongshu">小红书</option>
              </select>
            </div>
            <div class="form-group">
              <label>权重方案</label>
              <select id="importWeightMode">
                <option value="new_account">新号冷启动模式</option>
                <option value="old_account">老号深度运营模式</option>
              </select>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" onclick="App.closeImportModal()">取消</button>
            <button class="btn btn-primary" onclick="App.importAndPipeline()">导入并一键处理</button>
          </div>
        </div>
        <!-- Tab: URL import -->
        <div class="modal-tab-panel" id="tab-url" style="display:none">
          <div class="modal-body">
            <p class="form-hint">粘贴任意网页链接，系统将自动抓取页面内容并通过 AI 提炼为选题。</p>
            <div class="form-row">
              <div class="form-group form-group-half">
                <label>定位</label>
                <select id="importPositioningUrl">
                  <option value="business_tech">商业科技</option>
                  <option value="entertainment">娱乐鸡汤</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label>网页链接 *</label>
              <input type="url" id="importUrlInput" placeholder="https://...">
            </div>
            <div class="form-group">
              <label>目标平台</label>
              <select id="importPlatformUrl">
                <option value="wechat">公众号</option>
                <option value="toutiao">今日头条</option>
                <option value="xiaohongshu">小红书</option>
              </select>
            </div>
            <div class="form-group">
              <label>权重方案</label>
              <select id="importWeightModeUrl">
                <option value="new_account">新号冷启动模式</option>
                <option value="old_account">老号深度运营模式</option>
              </select>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" onclick="App.closeImportModal()">取消</button>
            <button class="btn btn-primary" id="btnUrlImport">导入并自动提取</button>
          </div>
        </div>
      </div>
    </div>`;
}

// ── Helpers ──────────────────────────────────────────────────────────────
function escHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

const PLATFORM_LABELS = { wechat: '公众号', toutiao: '今日头条', xiaohongshu: '小红书' };
const ACTION_LABELS = { confirm: '确认选题', discard: '淘汰', backup: '暂存备选', adjust: '调整匹配' };
