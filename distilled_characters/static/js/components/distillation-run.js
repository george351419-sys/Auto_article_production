/* ── Distillation Run & Live Progress Component ─────────────────── */
const DistillationRun = {
  _ws: null,
  _distId: null,
  _onComplete: null,
  _stepStates: {},

  // Step label map
  STEP_LABELS: {
    step1_collection: '素材归档与分级',
    step2_surface: '表层萃取 · 表达DNA',
    step3_midlayer: '中层蒸馏 · 思维工具',
    step4_deep: '深层蒸馏 · 世界观',
    step5_boundary: '边界补全 · 演化',
    step6_verification: '三重验证 · 封装',
  },
  STEP_ORDER: ['step1_collection', 'step2_surface', 'step3_midlayer', 'step4_deep', 'step5_boundary', 'step6_verification'],

  connect(distillationId, onComplete) {
    this._distId = distillationId;
    this._onComplete = onComplete;
    this._stepStates = {};

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/api/ws/pipeline/${distillationId}`;

    try {
      this._ws = new WebSocket(url);
      this._ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        this._stepStates[data.step_name] = data.status;
        this._updateLiveDisplay(data);
        // If we got 'cancelled', notify
        if (data.status === 'cancelled') {
          App.showToast('蒸馏已取消', 'info');
        }
      };
      this._ws.onerror = () => this._startPolling();
      this._ws.onclose = () => {
        if (this._onComplete) setTimeout(() => this._onComplete(), 800);
      };
    } catch (e) {
      this._startPolling();
    }
  },

  _startPolling() {
    const check = async () => {
      try {
        const d = await API.distillation.get(this._distId);
        if (d.status === 'completed' || d.status === 'failed' || d.status === 'cancelled') {
          const msg = d.status === 'completed' ? '蒸馏完成！' : d.status === 'cancelled' ? '蒸馏已取消' : '蒸馏失败';
          const type = d.status === 'completed' ? 'success' : d.status === 'cancelled' ? 'info' : 'error';
          App.showToast(msg, type);
          if (this._onComplete) this._onComplete();
          return;
        }
        setTimeout(check, 3000);
      } catch (e) {
        setTimeout(check, 5000);
      }
    };
    setTimeout(check, 3000);
  },

  // Render a static progress display for a distillation (no WebSocket needed)
  renderProgress(distId, stepResults) {
    const container = document.getElementById(`live-steps-${distId}`);
    if (!container) return '';

    let html = '<div style="font-size:13px;font-weight:600;margin-bottom:8px;">管道进度</div>';
    for (const name of this.STEP_ORDER) {
      const state = (stepResults && stepResults[name] && stepResults[name].status) || 'pending';
      const icon = { running: '◎', completed: '●', failed: '✕', pending: '○' }[state] || '○';
      html += `<div class="pipeline-step-row">
        <div class="pipeline-step-icon ${state}">${icon}</div>
        <div class="pipeline-step-label">${this.STEP_LABELS[name] || name}</div>
        <div class="pipeline-step-status ${state}">${state === 'completed' ? '完成' : state === 'failed' ? '失败' : state === 'running' ? '运行中' : '等待'}</div>
      </div>`;
    }
    return html;
  },

  _updateLiveDisplay(data) {
    document.querySelectorAll('[id^="live-steps-"]').forEach(el => {
      const distId = el.id.replace('live-steps-', '');
      if (distId === this._distId) {
        const icon = { running: '◎', completed: '●', failed: '✕', pending: '○' }[data.status] || '○';

        let html = '<div style="font-size:13px;font-weight:600;margin-bottom:8px;">管道进度</div>';
        for (const name of this.STEP_ORDER) {
          const state = name === data.step_name ? data.status : (this._stepStates[name] || 'pending');
          const stepIcon = { running: '◎', completed: '●', failed: '✕', pending: '○' }[state] || '○';
          html += `<div class="pipeline-step-row">
            <div class="pipeline-step-icon ${state}">${stepIcon}</div>
            <div class="pipeline-step-label">${this.STEP_LABELS[name] || name}</div>
            <div class="pipeline-step-status ${state}">${state === 'completed' ? '完成' : state === 'failed' ? '失败' : state === 'running' ? '运行中' : '等待'}</div>
          </div>`;
        }

        el.innerHTML = html;
      }
    });
  },
};
