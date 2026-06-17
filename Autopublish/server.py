#!/usr/bin/env python3
"""AutoPublish — 多平台自动发布系统
启动: ./start.sh  或  python3 server.py
访问: http://localhost:8765
"""

from __future__ import annotations

import base64, json, os, re, sys, shutil
from datetime import UTC, datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from autopublish import (
    Platform, PublishInput, execute_publish, execute_publish_plan,
    build_publish_plan, list_attempts,
)

try:
    from adapters.contract import handle_contract, handle_health
except ImportError:
    handle_contract = None
    handle_health = None

# ── Persistence paths ──────────────────────────────────────
DATA_DIR = HERE / ".data"
COOKIES_DIR = HERE / ".cookies"
DATA_DIR.mkdir(exist_ok=True)
COOKIES_DIR.mkdir(exist_ok=True)

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
PUBLISH_LOG_FILE = DATA_DIR / "publish_log.json"

# publish progress state (shared across threads)
_publish_progress: dict[str, str] = {}
_publish_lock = __import__("threading").Lock()

# ── Detect capabilities ────────────────────────────────────

def detect_wechat_api() -> dict:
    """Detect if WeChat API credentials are configured."""
    try:
        from autopublish.wechat_api import WechatApiPublisher
        pub = WechatApiPublisher.from_accounts_json()
        return {"available": True, "message": f"微信 API 可用 (AppID={pub.app_id[:6]}...)"}
    except Exception as e:
        return {"available": False, "message": f"微信 API 未配置: {e}"}

def detect_playwright() -> dict:
    try:
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return {"available": True, "version": "installed", "message": "Playwright + Chromium 可用"}
        except Exception:
            return {"available": False, "version": "no_browser", "message": "Playwright 已安装但 Chromium 未下载，执行: playwright install chromium"}
    except ImportError:
        return {"available": False, "version": "not_installed", "message": "Playwright 未安装，执行: pip install playwright && playwright install chromium"}

def detect_social_upload() -> dict:
    path = os.environ.get("SOCIAL_AUTO_UPLOAD_PATH", "")
    if path and Path(path).exists():
        return {"available": True, "message": f"social-auto-upload 可用: {path}"}
    for p in ["social-auto-upload", "social-auto-upload/main.py"]:
        if shutil.which(p.split("/")[0]):
            return {"available": True, "message": f"social-auto-upload 可用"}
    return {"available": False, "message": "social-auto-upload 未安装"}

def get_system_status() -> dict:
    return {
        "playwright": detect_playwright(),
        "wechat_api": detect_wechat_api(),
        "social_upload": detect_social_upload(),
        "accounts": load_accounts(),
        "publish_count_today": count_today_publishes(),
    }

# ── Data layer ─────────────────────────────────────────────

def load_accounts() -> dict:
    if ACCOUNTS_FILE.exists():
        return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return {
        "wechat_official": {"cookie": "", "account_name": "", "logged_in": False, "mode": "cookie"},
        "toutiao":          {"cookie": "", "account_name": "", "logged_in": False, "mode": "cookie"},
        "xiaohongshu":      {"cookie": "", "account_name": "", "logged_in": False, "mode": "cookie"},
    }

def save_accounts(accounts: dict) -> None:
    ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")

def load_log() -> list:
    if PUBLISH_LOG_FILE.exists():
        return json.loads(PUBLISH_LOG_FILE.read_text(encoding="utf-8"))
    return []

def save_log(log: list) -> None:
    PUBLISH_LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

def count_today_publishes() -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    count = 0
    for entry in load_log():
        if entry.get("time", "").startswith(today):
            count += 1
    return count

# ── HTML ───────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AutoPublish — 多平台自动发布系统</title>
<style>
:root {
  --bg:#f8f8f4; --card:#fff; --text:#1a1a1a; --muted:#888; --border:#e8e8e4;
  --accent:#e65c00; --blue:#0095e6; --green:#2e7d32; --red:#c62828;
  --wechat:#07c160; --toutiao:#e65c00; --xhs:#ff2442;
  --radius:12px; --shadow:0 1px 3px rgba(0,0,0,.05),0 1px 2px rgba(0,0,0,.03);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh}
.layout{display:flex;min-height:100vh}
.sidebar{width:220px;background:#1a1a1a;color:#ccc;padding:24px 0;display:flex;flex-direction:column;flex-shrink:0;position:sticky;top:0;height:100vh;overflow-y:auto}
.sidebar .logo{padding:0 24px 28px;font-size:20px;font-weight:800;color:#fff;letter-spacing:-.5px}
.sidebar .logo span{color:var(--accent)}
.sidebar nav a{display:flex;align-items:center;gap:10px;padding:11px 24px;color:#999;text-decoration:none;font-size:14px;transition:.15s;border-left:3px solid transparent}
.sidebar nav a svg{width:18px;height:18px;opacity:.6}
.sidebar nav a:hover,.sidebar nav a.active{color:#fff;background:rgba(255,255,255,.05);border-left-color:var(--accent)}
.sidebar nav a.active svg{opacity:1}
.sidebar .sys-status{margin-top:auto;padding:16px 24px;font-size:12px;color:#555;border-top:1px solid #2a2a2a}
.sidebar .sys-status .row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.sidebar .sys-status .dot{width:8px;height:8px;border-radius:50%}
.sidebar .sys-status .dot.on{background:var(--green)}
.sidebar .sys-status .dot.off{background:#555}
.sidebar .sys-status .dot.warn{background:#f9a825}
.main{flex:1;padding:36px 44px;max-width:1120px;overflow-y:auto}
h1{font-size:24px;font-weight:700;margin-bottom:4px;letter-spacing:-.3px}
h2{font-size:18px;font-weight:600;margin:28px 0 14px}
.subtitle{color:var(--muted);font-size:14px;margin-bottom:28px}
.card{background:var(--card);border-radius:var(--radius);padding:24px;margin-bottom:20px;box-shadow:var(--shadow);border:1px solid var(--border)}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.card-header h3{font-size:16px;font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.form-group{margin-bottom:14px}
.form-group:last-child{margin-bottom:0}
label{display:block;font-size:13px;font-weight:600;color:#555;margin-bottom:5px}
label .hint{color:var(--muted);font-weight:400;font-size:12px}
input[type="text"],input[type="url"],textarea,select{width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;font-family:inherit;background:#fafaf8;transition:.15s}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px rgba(0,149,230,.08)}
textarea{resize:vertical;min-height:80px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:10px 22px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:.15s;text-decoration:none;white-space:nowrap}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover:not(:disabled){background:#d45300}
.btn-primary:disabled{opacity:.5;cursor:not-allowed}
.btn-outline{background:transparent;border:1.5px solid var(--border);color:var(--text)}
.btn-outline:hover:not(:disabled){border-color:#aaa;background:#fafaf8}
.btn-sm{padding:6px 14px;font-size:12px}
.btn-block{width:100%}
.btn-danger{color:var(--red);border-color:#ffcdd2}
.btn-danger:hover{background:#fff5f5}
.tag{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:14px;font-size:12px;font-weight:500}
.tag-green{background:#e8f5e9;color:var(--green)}
.tag-red{background:#ffebee;color:var(--red)}
.tag-blue{background:#e3f2fd;color:var(--blue)}
.tag-gray{background:#f0f0f0;color:#666}
.tag-orange{background:#fff3e0;color:#e65100}
.platform-badge{display:inline-flex;align-items:center;gap:5px;padding:5px 14px;border-radius:16px;font-size:13px;font-weight:600;color:#fff}
.platform-badge.wechat{background:var(--wechat)}
.platform-badge.toutiao{background:var(--toutiao)}
.platform-badge.xiaohongshu{background:var(--xhs)}
.stat-card{text-align:center;padding:20px 16px}
.stat-card .num{font-size:36px;font-weight:800;line-height:1.2}
.stat-card .num.green{color:var(--green)}
.stat-card .num.orange{color:var(--accent)}
.stat-card .num.blue{color:var(--blue)}
.stat-card .num.gray{color:var(--muted)}
.stat-card .label{font-size:13px;color:var(--muted);margin-top:6px}
.log-entry{display:flex;align-items:flex-start;gap:14px;padding:14px 16px;border-left:3px solid var(--border);margin-bottom:8px;background:#fafaf8;border-radius:0 8px 8px 0;font-size:13px}
.log-entry.success{border-left-color:var(--green)}
.log-entry.failed{border-left-color:var(--red)}
.log-entry .time{color:var(--muted);font-size:11px;white-space:nowrap}
.log-entry .detail{flex:1;min-width:0}
.progress-steps{display:flex;gap:8px;margin:16px 0}
.progress-step{flex:1;text-align:center;padding:14px 8px;background:#f5f5f0;border-radius:10px;font-size:12px;font-weight:500;color:#999;transition:.2s}
.progress-step.done{background:#e8f5e9;color:var(--green)}
.progress-step.active{background:#fff3e0;color:var(--accent);font-weight:700;box-shadow:0 0 0 2px rgba(230,92,0,.2)}
.progress-step.fail{background:#ffebee;color:var(--red)}
.toast{position:fixed;top:20px;right:20px;padding:14px 24px;border-radius:10px;color:#fff;font-size:14px;font-weight:600;z-index:9999;animation:slideIn .3s ease;box-shadow:0 8px 24px rgba(0,0,0,.2);max-width:420px}
.toast.success{background:var(--green)}
.toast.error{background:var(--red)}
.toast.info{background:var(--blue)}
@keyframes slideIn{from{transform:translateX(120%);opacity:0}to{transform:translateX(0);opacity:1}}
.empty-state{text-align:center;padding:48px 20px;color:var(--muted)}
.empty-state .icon{font-size:48px;margin-bottom:12px}
.empty-state p{font-size:14px;margin-top:8px}
.meta-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.checkbox-group{display:flex;gap:20px;flex-wrap:wrap}
.checkbox-group label{display:flex;align-items:center;gap:8px;font-weight:400;cursor:pointer;font-size:14px}
.checkbox-group input[type="checkbox"]{width:18px;height:18px;accent-color:var(--accent)}
.banner{padding:14px 20px;border-radius:10px;font-size:13px;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.banner-info{background:#e3f2fd;color:#01579b;border:1px solid #bbdefb}
.banner-warn{background:#fff8e1;color:#e65100;border:1px solid #ffecb3}
.banner-success{background:#e8f5e9;color:#1b5e20;border:1px solid #c8e6c9}
.release-toggle{display:inline-flex;background:#f0f0f0;border-radius:8px;padding:3px}
.release-toggle button{padding:8px 18px;border:none;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;background:transparent;color:#666;transition:.15s}
.release-toggle button.active{background:#fff;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.08)}
.release-toggle button:disabled{opacity:.4;cursor:not-allowed}
.select-wrapper{position:relative}
.select-wrapper select{-webkit-appearance:none;appearance:none;padding-right:32px}
.select-wrapper::after{content:'';position:absolute;right:12px;top:50%;transform:translateY(-50%);border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid #666;pointer-events:none}
@media(max-width:900px){
  .layout{flex-direction:column}
  .sidebar{width:100%;flex-direction:row;padding:12px 16px;overflow-x:auto;position:static;height:auto}
  .sidebar .logo{padding:0 16px 0 0;font-size:16px}
  .sidebar nav{display:flex;gap:2px}
  .sidebar nav a{border-left:none;border-bottom:2px solid transparent;padding:8px 14px;white-space:nowrap;font-size:12px}
  .sidebar nav a.active{border-left:none;border-bottom-color:var(--accent)}
  .sidebar .sys-status{display:none}
  .main{padding:20px 16px}
  .grid2,.grid3,.grid4{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
  <div class="logo">Auto<span>Publish</span></div>
  <nav>
    <a href="#dashboard" class="active" data-tab="dashboard">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      仪表盘
    </a>
    <a href="#upload" data-tab="upload">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      文章上传
    </a>
    <a href="#accounts" data-tab="accounts">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
      账号管理
    </a>
    <a href="#history" data-tab="history">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
      发布记录
    </a>
  </nav>
  <div class="sys-status" id="sys-status">加载中...</div>
</aside>
<main class="main" id="main-content"></main>
</div>
<div id="toast-container"></div>

<script>
const PLATFORM_NAMES = {wechat_official:'微信公众号',toutiao:'今日头条',xiaohongshu:'小红书'};
const PLATFORM_BADGES = {wechat_official:'wechat',toutiao:'toutiao',xiaohongshu:'xiaohongshu'};
let STATE = {accounts:{},publishLog:[],status:{},publishing:false,currentTab:'',articleId:`article-${Date.now()}`};
function freshArticleId(){ STATE.articleId = `article-${Date.now()}`; }

async function init(){
  loadFormData();
  await refreshAll();
  setupNav();
  // hash routing
  let tab = (window.location.hash||'#dashboard').replace('#','');
  if(!['dashboard','upload','accounts','history'].includes(tab)) tab='dashboard';
  switchTab(tab);
  autoVerifyCookies();
}
async function refreshAll(){
  const [accts,log,status] = await Promise.all([
    api('GET','/api/accounts'),
    api('GET','/api/log'),
    api('GET','/api/status'),
  ]);
  STATE.accounts = accts;
  STATE.publishLog = log;
  STATE.status = status;
  updateSysStatus();
}
// ── Auto-save/restore form data ──────────────────────────
function saveFormData(){
  const data = {};
  const ids = ['article-id','title','body','summary','tags','keywords','author','location','topic-title','cover-path','image-paths','account-label'];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if(el) data[id] = el.value;
  });
  try { localStorage.setItem('autopublish_form', JSON.stringify(data)); } catch(e) {}
}
function loadFormData(){
  try {
    const saved = localStorage.getItem('autopublish_form');
    if(saved){
      const data = JSON.parse(saved);
      Object.entries(data).forEach(([id, val]) => {
        if(id === '__publisher_mode') return;
        const el = document.getElementById(id);
        if(el && val) el.value = val;
      });
    }
  } catch(e) {}
}
// ── Auto cookie verifier ─────────────────────────────────
async function autoVerifyCookies(){
  const accts = STATE.accounts||{};
  const platforms = Object.keys(accts).filter(k => accts[k].cookie && accts[k].cookie.trim() && accts[k].mode !== 'api');
  if(!platforms.length) return;
  let bad = [];
  for(const k of platforms){
    try {
      const res = await api('POST','/api/accounts/verify',{platform:k});
      if(res.ok){
        // Update logged_in status
        if(accts[k]) accts[k].logged_in = true;
      } else {
        if(accts[k]) accts[k].logged_in = false;
        bad.push(PLATFORM_NAMES[k]||k);
      }
    } catch(e) { /* ignore background errors */ }
  }
  if(bad.length > 0){
    toast('Cookie 已失效: ' + bad.join('、') + '，请前往账号管理更新','error');
  }
  updateSysStatus();
  if(STATE.currentTab === 'accounts') renderAccounts();
  if(STATE.currentTab === 'dashboard') renderDashboard();
}
function updateSysStatus(){
  const s = STATE.status;
  const pw = (s.playwright||{}).available;
  const html = `
    <div class="row"><span class="dot ${pw?'on':'off'}"></span> Playwright ${pw?'可用':'不可用'}</div>
    <div class="row"><span class="dot on"></span> Stub 模式 (安全)</div>
    <div style="margin-top:4px;font-size:11px">今日发布: ${s.publish_count_today||0} 篇</div>
  `;
  const el = document.getElementById('sys-status');
  if(el) el.innerHTML = html;
}
function setupNav(){
  document.querySelectorAll('.sidebar nav a').forEach(a=>{
    a.addEventListener('click',e=>{
      e.preventDefault();
      switchTab(a.dataset.tab);
    });
  });
}
function switchTab(tab){
  STATE.currentTab = tab;
  document.querySelectorAll('.sidebar nav a').forEach(a=>a.classList.toggle('active',a.dataset.tab===tab));
  window.location.hash = tab;
  if(tab==='dashboard') renderDashboard();
  else if(tab==='upload') renderUpload();
  else if(tab==='accounts') renderAccounts();
  else if(tab==='history') renderHistory();
}
function toast(msg,type){type=type||'info';const el=document.createElement('div');el.className='toast '+type;el.textContent=msg;document.getElementById('toast-container').appendChild(el);setTimeout(()=>el.remove(),3500)}
async function api(method,path,body){
  const opts={method,headers:{'Content-Type':'application/json'}};
  if(body)opts.body=JSON.stringify(body);
  const res=await fetch(path,opts);
  return res.json();
}

// ═══════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════
function renderDashboard(){
  const s = STATE.status;
  const pw_ok = (s.playwright||{}).available;
  const wechat_api_ok = (s.wechat_api||{}).available;
  const today = s.publish_count_today || 0;
  const accts = STATE.accounts;
  const acct_configured = Object.values(accts).filter(a=>a.logged_in).length;
  const log = STATE.publishLog||[];
  const recent = [...log].reverse().slice(0,8);

  document.getElementById('main-content').innerHTML = `
    <h1>仪表盘</h1>
    <p class="subtitle">系统状态和发布概览</p>

    ${wechat_api_ok ? `
    <div class="banner banner-success">
      <strong>微信 API 已配置</strong> — 公众号将使用 AppID/AppSecret 通过官方接口发布，无需模拟浏览器。
    </div>` : ''}

    ${!pw_ok ? `
    <div class="banner banner-warn">
      <strong>Playwright 未就绪</strong> — 头条和小红书需要使用 Playwright 模拟浏览器发布。
      要启用，请执行: <code style="background:rgba(0,0,0,.06);padding:2px 8px;border-radius:4px">pip install playwright && playwright install chromium</code>
    </div>` : `
    <div class="banner banner-success">
      <strong>Playwright 已就绪</strong> — 头条和小红书可以切换到 Playwright 模式进行真实发布。
    </div>`}

    ${acct_configured === 0 ? `
    <div class="banner banner-warn">
      尚未配置任何平台账号。请前往 <a href="#accounts" onclick="switchTab('accounts');return false" style="color:inherit;font-weight:700">账号管理</a> 配置 Cookie。
    </div>` : ''}

    <div class="grid4" style="margin-bottom:24px">
      <div class="card stat-card">
        <div class="num green">${pw_ok ? '真实' : 'Stub'}</div>
        <div class="label">发布模式</div>
      </div>
      <div class="card stat-card">
        <div class="num ${today>0?'orange':'gray'}">${today}</div>
        <div class="label">今日发布数</div>
      </div>
      <div class="card stat-card">
        <div class="num blue">${acct_configured}</div>
        <div class="label">已配置账号 / 3</div>
      </div>
      <div class="card stat-card">
        <div class="num gray">${log.length}</div>
        <div class="label">历史发布记录</div>
      </div>
    </div>

    <div class="grid3" style="margin-bottom:24px">
      ${['wechat_official','toutiao','xiaohongshu'].map(k=>{
        const a = accts[k]||{};
        return `
        <div class="card" style="text-align:center">
          <div style="margin-bottom:12px"><span class="platform-badge ${PLATFORM_BADGES[k]}">${PLATFORM_NAMES[k]}</span></div>
          <div style="font-size:15px;font-weight:600">${a.account_name||'未配置'}</div>
          <div style="font-size:12px;color:var(--muted);margin-top:4px">
            ${k==='wechat_official'&&wechat_api_ok?'<span class="tag tag-green">API 模式</span>':''}
            ${a.logged_in ? '<span class="tag tag-green">已登录</span>' : '<span class="tag tag-gray">未配置Cookie</span>'}
          </div>
        </div>`;
      }).join('')}
    </div>

    <div class="card">
      <div class="card-header">
        <h3>最近发布</h3>
        <button class="btn btn-outline btn-sm" onclick="switchTab('history')">查看全部</button>
      </div>
      ${recent.length===0 ? '<div class="empty-state"><div class="icon">📋</div><p>还没有发布记录</p></div>' : ''}
      ${recent.map(e=>`
        <div class="log-entry ${e.status}">
          <span class="platform-badge ${PLATFORM_BADGES[e.platform]||'toutiao'}" style="flex-shrink:0">${PLATFORM_NAMES[e.platform]||e.platform}</span>
          <div class="detail">
            <strong>${e.article_id||''}</strong>
            <span class="tag ${e.status==='success'?'tag-green':'tag-red'}">${e.status==='success'?'成功':'失败'}</span>
            ${e.url ? `<span style="font-size:12px;color:var(--muted);margin-left:8px">${e.url}</span>` : ''}
            ${e.error ? `<div style="color:var(--red);font-size:12px;margin-top:2px">${e.error}</div>` : ''}
          </div>
          <span class="time">${(e.time||'').replace('T',' ').substring(0,19)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

// ═══════════════════════════════════════════════════════════
// UPLOAD
// ═══════════════════════════════════════════════════════════
function renderUpload(){
  const pw_ok = (STATE.status.playwright||{}).available;
  document.getElementById('main-content').innerHTML = `
    <h1>文章上传 & 发布</h1>
    <p class="subtitle">填写文章内容与元数据，选择平台，一键发布。</p>

    <div class="card">
      <div class="card-header"><h3>基本信息</h3></div>
      <div class="grid2">
        <div><label>文章 ID <span class="hint">（唯一标识，同一篇文章保持不变可防止重复发布）</span></label><input type="text" id="article-id" value="${STATE.articleId}"></div>
        <div><label>作者</label><input type="text" id="author" value="AI观察员"></div>
      </div>
      <div class="form-group"><label>文章标题 <span class="hint">（各平台会自动截断/改写）</span></label><input type="text" id="title" value="AI大模型正在改变普通人的工作方式"></div>
      <div class="form-group"><label>正文内容 <span class="hint">（支持 Markdown）</span></label><textarea id="body" rows="14">过去一年，AI大模型从实验室走进了每个人的日常办公场景。

第一层变化：信息获取方式的改变

以前我们搜索信息，需要自己在搜索引擎里输入关键词、打开多个网页逐一阅读、对比、整理。现在，你只需要用自然语言提问，AI就能给你一个结构化的回答。这不是搜索工具的升级，而是信息消费方式的根本变化。

第二层变化：内容创作门槛的降低

写报告、做PPT、画图、剪视频——这些原本需要专业技能的事情，现在通过简单的文字描述就能完成。这意味着"会使用AI"比"会某项技能"更重要。

第三层变化：决策方式的升级

当AI能帮你分析数据、总结趋势、给出建议时，"拍脑袋决策"正在变成"数据+AI辅助决策"。普通人也第一次拥有了以前只有大公司才有的分析能力。

普通人应该怎么应对这三层变化？答案是：把AI当作"思考的伙伴"，而不是"替代品"。它擅长信息整理和模式识别，但判断力、创造力、共情能力——这些人类独有的能力，仍然是不可替代的。</textarea></div>
    </div>

    <div class="card">
      <div class="card-header"><h3>元数据</h3></div>
      <div class="grid3">
        <div><label>摘要 <span class="hint">（120字以内）</span></label><textarea id="summary" rows="3">AI大模型带来的三层变化：信息获取、内容创作、决策方式，以及普通人如何应对。</textarea></div>
        <div><label>标签 <span class="hint">（逗号分隔）</span></label><textarea id="tags" rows="3">AI, 大模型, 效率提升, 职场</textarea></div>
        <div><label>关键词 <span class="hint">（逗号分隔）</span></label><textarea id="keywords" rows="3">人工智能, 大模型, 工作效率, AI工具</textarea></div>
      </div>
      <div class="grid2">
        <div><label>话题/选题标题</label><input type="text" id="topic-title" value="AI大模型改变工作方式"></div>
        <div><label>发布地点 <span class="hint">（小红书必填）</span></label><input type="text" id="location" value="北京"></div>
      </div>
      <div class="grid2">
        <div>
          <label>封面图路径 <span class="hint" style="color:var(--red)">（微信公众号 API 必填）</span></label>
          <div style="display:flex;gap:6px">
            <input type="text" id="cover-path" placeholder="/path/to/cover.png（微信公众号必须填写）" style="flex:1">
            <button type="button" class="btn btn-outline btn-sm" onclick="uploadImages('cover-path',false)" title="从本地选择封面图">选择图片</button>
          </div>
        </div>
        <div>
          <label>配图路径 <span class="hint">（逗号分隔，最多9张）</span><span class="hint" style="color:var(--red)"> 小红书必填</span></label>
          <div style="display:flex;gap:6px">
            <input type="text" id="image-paths" placeholder="/path/to/img1.png, /path/to/img2.png" style="flex:1">
            <button type="button" class="btn btn-outline btn-sm" onclick="uploadImages('image-paths',true)" title="从本地选择配图（可多选）">选择图片</button>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><h3>发布设置</h3></div>
      <div class="form-group">
        <label>目标平台</label>
        <div class="checkbox-group">
          <label><input type="checkbox" id="plat-wechat" checked> <span class="platform-badge wechat">公众号</span></label>
          <label><input type="checkbox" id="plat-toutiao" checked> <span class="platform-badge toutiao">今日头条</span></label>
          <label><input type="checkbox" id="plat-xiaohongshu" checked> <span class="platform-badge xiaohongshu">小红书</span></label>
        </div>
      </div>
      <div class="grid2">
        <div><label>账号标签 <span class="hint">（对应账号管理中配置的名称）</span></label><input type="text" id="account-label" value="my-main-account"></div>
        <div>
          <label>发布模式</label>
          <div style="padding:8px 12px;background:var(--accent-light,#eef2ff);border-radius:8px;font-size:13px;display:flex;align-items:center;gap:8px">
            <span class="dot on"></span>
            <span>Playwright 真实发布${pw_ok?'':' <span style="color:var(--red)">(未安装 — 执行: pip install playwright && playwright install chromium)</span>'}</span>
          </div>
        </div>
      </div>
      <div style="margin-top:20px;display:flex;gap:12px">
        <button type="button" class="btn btn-primary btn-block" id="btn-publish" onclick="doPublish()">一键发布到所选平台</button>
        <button class="btn btn-outline" onclick="doPreview()">预览各平台格式</button>
      </div>
      <div id="publish-progress" style="margin-top:16px"></div>
    </div>

    <div class="card" id="publish-result" style="display:none">
      <div class="card-header"><h3>发布结果</h3><button class="btn btn-outline btn-sm" onclick="document.getElementById('publish-result').style.display='none'">收起</button></div>
      <div id="publish-result-content"></div>
    </div>
  `;
}

const selectedPublisherMode = 'playwright';
function collectInput(){
  // Auto-save form data on each collect
  saveFormData();
  return {
    article_id: document.getElementById('article-id').value,
    title: document.getElementById('title').value,
    body: document.getElementById('body').value,
    summary: document.getElementById('summary').value,
    tags: document.getElementById('tags').value.split(',').map(s=>s.trim()).filter(Boolean),
    keywords: document.getElementById('keywords').value.split(',').map(s=>s.trim()).filter(Boolean),
    author: document.getElementById('author').value,
    location: document.getElementById('location').value,
    topic_title: document.getElementById('topic-title').value,
    cover_path: document.getElementById('cover-path').value,
    image_paths: document.getElementById('image-paths').value.split(',').map(s=>s.trim()).filter(Boolean),
    account_label: document.getElementById('account-label').value,
    platforms: [
      ...(document.getElementById('plat-wechat').checked?['wechat_official']:[]),
      ...(document.getElementById('plat-toutiao').checked?['toutiao']:[]),
      ...(document.getElementById('plat-xiaohongshu').checked?['xiaohongshu']:[]),
    ],
    publisher_type: selectedPublisherMode,
  };
}
async function uploadImages(fieldId, multi=true){
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.multiple = multi;
  input.onchange = async () => {
    const files = Array.from(input.files);
    if(!files.length) return;
    toast('正在上传图片...');
    try {
      const fileData = await Promise.all(files.map(f => new Promise((res,rej) => {
        const reader = new FileReader();
        reader.onload = () => res({name: f.name, data: reader.result});
        reader.onerror = rej;
        reader.readAsDataURL(f);
      })));
      const resp = await api('POST', '/api/upload', {files: fileData});
      if(resp.ok){
        const field = document.getElementById(fieldId);
        const existing = field.value.split(',').map(s=>s.trim()).filter(Boolean);
        const newPaths = resp.paths.filter(p => !existing.includes(p));
        field.value = [...existing, ...newPaths].join(', ');
        toast(`已上传 ${resp.paths.length} 张图片`);
      } else {
        toast('上传失败: ' + (resp.error||'未知错误'), 'error');
      }
    } catch(e){ toast('上传失败: '+e.message,'error'); }
  };
  input.click();
}
async function doPublish(){
  console.log('doPublish called, STATE.publishing=', STATE.publishing);
  if(STATE.publishing){console.log('Already publishing, skip');return;}
  const input = collectInput();
  console.log('collectInput done, title=', input.title, 'platforms=', input.platforms);
  if(!input.title||!input.body){toast('请填写标题和正文','error');console.log('Missing title/body');return}
  if(input.platforms.length===0){toast('请至少选择一个目标平台','error');console.log('No platforms');return}

  // Warn if playwright mode but no cookies
  if(input.publisher_type==='playwright'){
    const accts = STATE.accounts;
    const missing = input.platforms.filter(p=>!accts[p]||(!accts[p].logged_in && accts[p].mode !== 'api'));
    if(missing.length>0){
      toast('以下平台未配置Cookie: '+missing.map(p=>PLATFORM_NAMES[p]).join('、')+'，发布会失败','error');
    }
  }

  STATE.publishing=true;
  const btn=document.getElementById('btn-publish');
  btn.textContent='发布中...';btn.disabled=true;

  const platformNames = input.platforms.map(p=>PLATFORM_NAMES[p]||p);
  const progressEl = document.getElementById('publish-progress');
  if(progressEl){
    progressEl.innerHTML=`
      <div class="progress-steps" id="progress-steps">
        <div class="progress-step active" id="step-status">正在提交发布请求...</div>
      </div>
    `;
  }

  try{
    // Step 1: Submit publish (returns immediately with task_id)
    const submitRes = await api('POST','/api/publish',input);
    console.log('Submit result:', submitRes);
    if(submitRes.error){throw new Error(submitRes.error);}
    const taskId = submitRes.task_id;

    // Step 2: Poll progress
    let done = false;
    while(!done){
      await new Promise(r=>setTimeout(r, 800));
      const prog = await api('GET','/api/publish/progress/'+taskId);
      console.log('Progress:', prog);

      if(prog.done){
        done = true;
        // Show final results
        const result = prog.result || {plans:[],errors:[]};
        const plans = result.plans||[];
        const statusEl = document.getElementById('step-status');
        if(statusEl){
          const allOk = plans.every(p=>p.result?.status==='success') && plans.length>0;
          statusEl.className = 'progress-step ' + (allOk ? 'done' : 'fail');
          statusEl.textContent = allOk ? '发布完成' : '发布完成（有失败）';
        }
        if(plans.length===0 && (result.errors||[]).length>0){
          toast('发布失败: '+result.errors.map(e=>e.error||e).join('; '),'error');
        }
        showResults({plans, errors: result.errors||[], error: prog.error||null});
        const allOk2 = plans.every(p=>p.result?.status==='success'||p.result?.status==='duplicate') && plans.length>0;
        const anyOk = plans.some(p=>p.result?.status==='success');
        if(allOk2){ toast('全部发布成功！','success'); freshArticleId(); }
        else if(anyOk){
          // Uncheck platforms that already succeeded so retry only hits failed ones
          const PLAT_CB = {wechat_official:'plat-wechat',toutiao:'plat-toutiao',xiaohongshu:'plat-xiaohongshu'};
          plans.filter(p=>p.result?.status==='success'||p.result?.status==='duplicate').forEach(p=>{
            const cb = document.getElementById(PLAT_CB[p.platform]);
            if(cb) cb.checked = false;
          });
          toast('部分平台发布失败，已自动取消勾选成功的平台，可直接重试失败的平台','error');
        } else { toast('发布失败，请查看下方错误信息','error'); }
        await refreshAll();
      } else {
        // Update progress indicator
        const statusEl = document.getElementById('step-status');
        if(statusEl){
          const statusMap = {
            'starting': '正在提交发布请求...',
            'building_plan': '正在构建发布计划...',
            'publishing': '正在发布到 ' + platformNames.join('、') + '...',
          };
          statusEl.textContent = statusMap[prog.status] || ('发布中: '+JSON.stringify(prog.status));
        }
      }
    }
  }catch(e){
    console.error('doPublish error:', e);
    toast('发布异常: '+e.message,'error');
    const progressEl = document.getElementById('publish-progress');
    if(progressEl) progressEl.innerHTML = '<div style="color:var(--red);padding:12px;background:#fff5f5;border-radius:8px;margin-top:12px"><strong>错误:</strong> '+e.message+'</div>';
  }finally{
    STATE.publishing=false;
    const btn=document.getElementById('btn-publish');
    if(btn){btn.textContent='一键发布到所选平台';btn.disabled=false;}
  }
}
function showResults(results){
  const div=document.getElementById('publish-result');
  const content=document.getElementById('publish-result-content');
  div.style.display='block';
  // Support both array and {plans, errors, error} format
  const items = Array.isArray(results) ? results : [results];
  content.innerHTML=items.map(r=>{
    if(!r) return '';
    if(r.error)return `<div class="log-entry failed"><div class="detail"><strong>错误</strong>: ${r.error}</div></div>`;
    if(!r.plans || r.plans.length===0) return '<div class="log-entry"><div class="detail">无发布结果</div></div>';
    return (r.plans).map(p=>`
      <div class="log-entry ${p.result?.status==='success'?'success':'failed'}">
        <span class="platform-badge ${PLATFORM_BADGES[p.platform]||'toutiao'}">${PLATFORM_NAMES[p.platform]||p.platform}</span>
        <div class="detail">
          <span class="tag ${p.result?.status==='success'?'tag-green':'tag-red'}">${p.result?.status==='success'?'发布成功':'发布失败'}</span>
          ${p.result?.platform_url&&p.result?.status==='success'?`<span style="font-size:12px;color:var(--muted);margin-left:8px">${p.result.platform_url}</span>`:''}
          ${p.result?.error_message?`<div style="color:var(--red);font-size:12px;margin-top:4px">${p.result.error_message}</div>`:''}
          ${p.real_publish===false?`<div style="color:var(--muted);font-size:11px;margin-top:2px">(Stub 模式 — 未实际发布)</div>`:''}
        </div>
      </div>
    `).join('');
  }).join('');
}
async function doPreview(){
  const input=collectInput();
  if(!input.title||!input.body){toast('请填写标题和正文','error');return}
  const res=await api('POST','/api/preview',input);
  const div=document.getElementById('publish-result');
  const content=document.getElementById('publish-result-content');
  div.style.display='block';
  content.innerHTML=(res.previews||[]).map(p=>`
    <div class="card" style="margin-bottom:14px">
      <h3 style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <span class="platform-badge ${PLATFORM_BADGES[p.platform]||'toutiao'}">${PLATFORM_NAMES[p.platform]||p.platform}</span>
        ${p.title}
      </h3>
      <div style="margin-bottom:10px;font-size:13px;color:var(--muted)">${(p.tags||[]).map(t=>`<span class="tag tag-gray">${t}</span>`).join(' ')}</div>
      <div style="background:#fafaf8;padding:16px;border-radius:8px;font-size:14px;white-space:pre-wrap;max-height:300px;overflow-y:auto;line-height:1.8">${p.body}</div>
      <div style="margin-top:12px;font-size:12px;color:var(--muted);display:flex;align-items:center;gap:8px">
        就绪检查:
        ${p.readiness?.passed
          ?'<span class="tag tag-green">通过 (评分:'+p.readiness.score+')</span>'
          :'<span class="tag tag-orange">有阻塞项</span>'}
        ${(p.readiness?.blocking_reasons||[]).length?` — ${p.readiness.blocking_reasons.join('; ')}`:''}
      </div>
    </div>
  `).join('');
}

// ═══════════════════════════════════════════════════════════
// ACCOUNTS
// ═══════════════════════════════════════════════════════════
function renderAccounts(){
  const platforms = [
    {key:'wechat_official',name:'微信公众号',badge:'wechat',desc:'微信公众平台',loginUrl:'https://mp.weixin.qq.com/',newArticleUrl:'https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&isNew=1',api:true},
    {key:'toutiao',name:'今日头条',badge:'toutiao',desc:'头条号后台',loginUrl:'https://mp.toutiao.com/',newArticleUrl:'https://mp.toutiao.com/profile_v4/content-management/article-write',api:false},
    {key:'xiaohongshu',name:'小红书',badge:'xiaohongshu',desc:'创作者中心',loginUrl:'https://creator.xiaohongshu.com/',newArticleUrl:'https://creator.xiaohongshu.com/note/publish?type=normal',api:false},
  ];
  document.getElementById('main-content').innerHTML = `
    <h1>账号管理</h1>
    <p class="subtitle">为每个平台配置发布凭证。数据保存在本地 <code>.data/accounts.json</code>。</p>

    ${platforms.map(p=>{
      const a = STATE.accounts[p.key]||{};
      const hasCred = !!(a.cookie||'').trim();
      return `
      <div class="card">
        <div class="card-header">
          <h3><span class="platform-badge ${p.badge}">${p.name}</span>
            ${hasCred ? '<span class="tag tag-green">已配置</span>' : '<span class="tag tag-gray">未配置</span>'}
          </h3>
          <div style="display:flex;gap:8px">
            <a href="${p.loginUrl}" target="_blank" class="btn btn-outline btn-sm">打开登录页</a>
            <a href="${p.newArticleUrl}" target="_blank" class="btn btn-outline btn-sm">打开发布页</a>
          </div>
        </div>
        <p style="color:var(--muted);font-size:13px;margin-bottom:14px">${p.desc}</p>
        <div class="grid2">
          <div>
            <label>账号名称 / 标签</label>
            <input type="text" id="acct-${p.key}-name" value="${a.account_name||''}" placeholder="如：主账号">
          </div>
          <div>
            <label>凭证方式</label>
            <div class="select-wrapper">
              <select id="acct-${p.key}-mode" onchange="onModeChange('${p.key}')">
                ${p.api ? `<option value="api" ${a.mode==='api'?'selected':''}>AppID / AppSecret</option>` : ''}
                <option value="cookie" ${a.mode==='cookie'||!a.mode?'selected':''}>浏览器 Cookie</option>
              </select>
            </div>
          </div>
        </div>
        <div class="form-group" id="acct-${p.key}-api-section" style="display:${(p.api&&a.mode==='api')?'block':'none'}">
          <label>AppID 和 AppSecret <span class="hint">（公众号 API 发布，无需浏览器）</span></label>
          <textarea id="acct-${p.key}-cookie-api" rows="3" placeholder="AppID=wx5f4b4975e0db0cb0&#10;AppSecret=e7278e365cc9662b683f8b9a54ede7c7">${(a.mode==='api')?a.cookie||'':''}</textarea>
        </div>
        <div class="form-group" id="acct-${p.key}-cookie-section" style="display:${(p.api&&a.mode==='api')?'none':'block'}">
          <label>Cookie 字符串</label>
          <textarea id="acct-${p.key}-cookie-browser" rows="4" placeholder="从浏览器开发者工具 Application → Cookies 中复制。或粘贴 JSON 数组">${(a.mode!=='api')?a.cookie||'':''}</textarea>
        </div>
        <div style="display:flex;gap:12px;align-items:center">
          <button class="btn btn-primary btn-sm" onclick="saveAccount('${p.key}')">保存</button>
          ${p.api ? `<span style="font-size:12px;color:var(--muted)">API 模式由微信服务器校验，无需本地验证</span>` : `<button class="btn btn-outline btn-sm" onclick="verifyCookie('${p.key}')">验证 Cookie</button>`}
          ${hasCred?`<button class="btn btn-outline btn-sm btn-danger" onclick="clearAccount('${p.key}')">清除</button>`:''}
        </div>
        <div id="acct-${p.key}-status" style="margin-top:10px;font-size:13px"></div>
      </div>`;
    }).join('')}

    <div class="card" style="background:#fff9f5;border-color:#ffe0b2">
      <h3>如何配置？</h3>
      <ol style="font-size:14px;color:#555;padding-left:20px;line-height:2.2">
        <li><strong>公众号（推荐 API）</strong>：登录 <a href="https://mp.weixin.qq.com/" target="_blank">微信公众平台</a> → 设置与开发 → 基本配置 → 获取 AppID 和 AppSecret，并添加服务器 IP 到白名单</li>
        <li><strong>头条 / 小红书</strong>：用 Chrome/Edge 打开对应平台并<strong>手动登录</strong></li>
        <li>按 <kbd style="background:#eee;padding:2px 8px;border-radius:4px;font-family:monospace">F12</kbd> 打开开发者工具</li>
        <li>切换到 <strong>Application</strong>（应用程序）→ <strong>Cookies</strong></li>
        <li>选择平台域名，复制所有 Cookie（可全选后导出为 JSON）</li>
        <li>粘贴到上方文本框，点击<strong>保存</strong>，然后点击<strong>验证 Cookie</strong></li>
      </ol>
    </div>
  `;
}
function onModeChange(key){
  const mode = document.getElementById(`acct-${key}-mode`).value;
  const apiSection = document.getElementById(`acct-${key}-api-section`);
  const cookieSection = document.getElementById(`acct-${key}-cookie-section`);
  if(apiSection) apiSection.style.display = mode === 'api' ? 'block' : 'none';
  if(cookieSection) cookieSection.style.display = mode === 'api' ? 'none' : 'block';
}
async function saveAccount(key){
  const name=document.getElementById(`acct-${key}-name`).value;
  const mode=document.getElementById(`acct-${key}-mode`).value;
  // Pick the right textarea based on mode
  let cookie = '';
  if(mode === 'api'){
    const ta = document.getElementById(`acct-${key}-cookie-api`);
    if(ta) cookie = ta.value;
  } else {
    const ta = document.getElementById(`acct-${key}-cookie-browser`);
    if(ta) cookie = ta.value;
  }
  await api('POST','/api/accounts',{platform:key,account_name:name,cookie,mode,logged_in:!!cookie.trim()});
  await refreshAll();
  toast((cookie.trim()?'已保存: ':'已清除: ')+PLATFORM_NAMES[key],'success');
  renderAccounts();
}
async function verifyCookie(key){
  const statusEl=document.getElementById(`acct-${key}-status`);
  statusEl.innerHTML='<span style="color:var(--blue)">验证中，正在用 Playwright 测试 Cookie 是否有效...</span>';
  try{
    const res=await api('POST','/api/accounts/verify',{platform:key});
    if(res.ok){
      statusEl.innerHTML='<span class="tag tag-green">Cookie 有效 — 无需重新登录</span>';
      toast(PLATFORM_NAMES[key]+' Cookie 验证成功','success');
    }else{
      statusEl.innerHTML='<span class="tag tag-red">'+ (res.error||'Cookie 无效或已过期') +'</span>';
      toast(PLATFORM_NAMES[key]+' Cookie 无效，请重新获取','error');
    }
  }catch(e){
    statusEl.innerHTML='<span class="tag tag-red">验证失败: '+e.message+'</span>';
  }
}
async function clearAccount(key){
  await api('DELETE',`/api/accounts/${key}`);
  await refreshAll();
  toast('已清除: '+PLATFORM_NAMES[key],'success');
  renderAccounts();
}

// ═══════════════════════════════════════════════════════════
// HISTORY
// ═══════════════════════════════════════════════════════════
function renderHistory(){
  const log=[...(STATE.publishLog||[])].reverse();
  document.getElementById('main-content').innerHTML=`
    <h1>发布记录</h1>
    <p class="subtitle">所有历史发布记录，包含成功和失败的发布。</p>
    <div style="display:flex;gap:8px;margin-bottom:20px">
      <button class="btn btn-outline btn-sm" onclick="refreshAll().then(renderHistory)">刷新列表</button>
      <button class="btn btn-outline btn-sm btn-danger" onclick="clearLog()">清空记录</button>
    </div>
    <div class="card">
      ${log.length===0?'<div class="empty-state"><div class="icon">📋</div><p>还没有发布记录。去 <a href="#upload" style="color:var(--accent)" onclick="switchTab(\'upload\');return false">上传文章</a> 试试。</p></div>':''}
      ${log.map(e=>`
        <div class="log-entry ${e.status}">
          <span class="platform-badge ${PLATFORM_BADGES[e.platform]||'toutiao'}" style="flex-shrink:0">${PLATFORM_NAMES[e.platform]||e.platform}</span>
          <div class="detail">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <strong>${e.article_id||e.id||'未知'}</strong>
              <span class="tag ${e.status==='success'?'tag-green':'tag-red'}">${e.status==='success'?'成功':'失败'}</span>
              <span class="tag tag-gray">${e.publisher_type||'stub'}</span>
              ${e.url?`<span style="font-size:12px;color:var(--muted)">${e.url}</span>`:''}
            </div>
            ${e.error?`<div style="color:var(--red);font-size:12px;margin-top:4px">${e.error}</div>`:''}
          </div>
          <span class="time">${(e.time||'').replace('T',' ').substring(0,19)}</span>
        </div>
      `).join('')}
    </div>
  `;
}
async function clearLog(){
  if(!confirm('确认清空所有发布记录？此操作不可撤销。'))return;
  await api('POST','/api/log/clear');
  await refreshAll();
  toast('发布记录已清空','success');
  renderHistory();
}

init();
</script>
</body>
</html>"""

# ── Request Handler ───────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._html(HTML)
        if path == "/api/status":
            return self._json(get_system_status())
        if path == "/health":
            if handle_health:
                code, data = handle_health()
                return self._json(data, code)
            return self._json({"ok": True, "module": "autopublish", "version": "3.0.5"}, 200)
        if path == "/contract":
            if handle_contract:
                code, data = handle_contract()
                return self._json(data, code)
            return self._json({"module": "autopublish", "contract_version": "1.0", "endpoints": []}, 200)
        if path == "/api/accounts":
            return self._json(load_accounts())
        if path == "/api/log":
            return self._json(load_log())
        if path == "/api/publish/attempts":
            return self._json([a.__dict__ if hasattr(a,'__dict__') else {} for a in list_attempts()])
        if path.startswith("/api/publish/progress/"):
            task_id = path.split("/")[-1]
            with _publish_lock:
                val = _publish_progress.get(task_id, "unknown")
            try:
                return self._json(json.loads(val) if isinstance(val, str) else {"status": val})
            except (json.JSONDecodeError, TypeError):
                return self._json({"status": str(val)})
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/publish":
            return self._handle_publish(body)
        if path == "/api/preview":
            return self._handle_preview(body)
        if path == "/api/accounts":
            return self._handle_save_account(body)
        if path == "/api/accounts/verify":
            return self._handle_verify_cookie(body)
        if path == "/api/accounts/test":
            return self._handle_test_account(body)
        if path == "/api/log/clear":
            save_log([])
            return self._json({"ok": True})
        if path == "/api/upload":
            return self._handle_upload(body)
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/accounts/"):
            platform = path.split("/")[-1]
            accounts = load_accounts()
            if platform in accounts:
                accounts[platform] = {"cookie":"","account_name":"","logged_in":False,"mode":"cookie"}
                save_accounts(accounts)
                # Also remove cookie file
                cf = COOKIES_DIR / f"{platform}_cookies.json"
                if cf.exists(): cf.unlink()
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Handlers ──────────────────────────────────────────

    def _handle_publish(self, body: dict):
        """Publish in background thread with progress tracking."""
        task_id = f"task-{datetime.now(UTC).timestamp():.0f}"
        with _publish_lock:
            _publish_progress[task_id] = "starting"

        def publish_bg():
            try:
                with _publish_lock:
                    _publish_progress[task_id] = "building_plan"
                input_data = PublishInput(
                    article_id=body.get("article_id", f"article-{datetime.now(UTC).timestamp():.0f}"),
                    title=body.get("title", ""),
                    body=body.get("body", ""),
                    summary=body.get("summary", ""),
                    tags=body.get("tags", []),
                    keywords=body.get("keywords", []),
                    author=body.get("author", ""),
                    location=body.get("location", ""),
                    cover_path=body.get("cover_path", ""),
                    image_paths=body.get("image_paths", []),
                    account_label=body.get("account_label", ""),
                    topic_title=body.get("topic_title", ""),
                    platforms=[Platform(p) for p in body.get("platforms", ["wechat_official"])],
                )
                publisher_type = body.get("publisher_type", "playwright")
                print(f"[autopublish] publish request: publisher_type={publisher_type!r}, platforms={[p.value for p in input_data.platforms]}")
                with _publish_lock:
                    _publish_progress[task_id] = "publishing"
                result = execute_publish(input_data, publisher_type=publisher_type)

                log = load_log()
                for plan in result.plans:
                    log.append({
                        "id": plan.get("plan_id", ""),
                        "article_id": result.article_id,
                        "platform": plan.get("platform", ""),
                        "status": plan.get("result", {}).get("status", "unknown"),
                        "url": plan.get("result", {}).get("platform_url", ""),
                        "error": plan.get("result", {}).get("error_message", ""),
                        "time": datetime.now(UTC).isoformat(),
                        "publisher_type": publisher_type,
                    })
                for err in result.errors:
                    log.append({
                        "id": "", "article_id": result.article_id,
                        "platform": err.get("platform", ""), "status": "failed",
                        "url": "", "error": err.get("error", ""),
                        "time": datetime.now(UTC).isoformat(),
                        "publisher_type": publisher_type,
                    })
                save_log(log)
                with _publish_lock:
                    _publish_progress[task_id] = json.dumps({"done": True, "result": result.to_dict()}, ensure_ascii=False)
            except Exception as exc:
                with _publish_lock:
                    _publish_progress[task_id] = json.dumps({"done": True, "error": str(exc)}, ensure_ascii=False)

        Thread(target=publish_bg, daemon=True).start()
        self._json({"task_id": task_id, "status": "started"})

    def _handle_preview(self, body: dict):
        try:
            input_data = PublishInput(
                article_id="preview", title=body.get("title",""), body=body.get("body",""),
                summary=body.get("summary",""), tags=body.get("tags",[]),
                keywords=body.get("keywords",[]), author=body.get("author",""),
                location=body.get("location",""), cover_path=body.get("cover_path",""),
                image_paths=body.get("image_paths",[]),
                account_label=body.get("account_label",""),
                topic_title=body.get("topic_title",""),
            )
            platforms = [Platform(p) for p in body.get("platforms", ["wechat_official","toutiao","xiaohongshu"])]
            previews = []
            for platform in platforms:
                plan = build_publish_plan(input_data, platform)
                previews.append({
                    "platform": platform.value,
                    "title": plan.title, "body": plan.body, "tags": plan.tags,
                    "summary": plan.summary,
                    "readiness": {
                        "passed": plan.readiness_report.passed,
                        "score": plan.readiness_report.score,
                        "blocking_reasons": plan.readiness_report.blocking_reasons,
                    },
                })
            self._json({"previews": previews})
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def _handle_save_account(self, body: dict):
        accounts = load_accounts()
        platform = body.get("platform", "")
        if platform in accounts:
            accounts[platform] = {
                "cookie": body.get("cookie", ""),
                "account_name": body.get("account_name", ""),
                "mode": body.get("mode", "cookie"),
                "logged_in": body.get("logged_in", False),
            }
            save_accounts(accounts)
        self._json({"ok": True})

    def _handle_upload(self, body: dict):
        """Accept base64-encoded images, save to .data/uploads/, return server paths."""
        upload_dir = DATA_DIR / "uploads"
        upload_dir.mkdir(exist_ok=True)
        saved = []
        for f in body.get("files", []):
            raw_name = re.sub(r"[^\w\-.]", "_", f.get("name", "image.png"))
            data_url = f.get("data", "")
            if "," in data_url:
                data_url = data_url.split(",", 1)[1]
            try:
                img_bytes = base64.b64decode(data_url)
            except Exception as e:
                return self._json({"ok": False, "error": f"base64 decode error: {e}"}, 400)
            dest = upload_dir / raw_name
            counter = 1
            while dest.exists():
                stem, suffix = Path(raw_name).stem, Path(raw_name).suffix
                dest = upload_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            dest.write_bytes(img_bytes)
            saved.append(str(dest))
        self._json({"ok": True, "paths": saved})

    def _handle_test_account(self, body: dict):
        platform = body.get("platform", "")
        accounts = load_accounts()
        if platform in accounts and accounts[platform].get("cookie"):
            self._json({"ok": True, "message": f"Cookie 已配置 ({len(accounts[platform]['cookie'])} 字符)"})
        else:
            self._json({"ok": False, "error": "未配置 Cookie"})

    def _parse_any_cookie(self, raw: str, origin_url: str) -> list[dict]:
        """Parse cookie from two formats:
        A) JSON array from browser DevTools export.
        B) Simple text: key1=value1; key2=value2
        Returns a list of cookie dicts for context.add_cookies().
        """
        raw = raw.strip()
        # --- Format A: JSON array ---
        if raw.startswith("[") and raw.endswith("]"):
            try:
                arr = json.loads(raw)
                cookies = []
                for c in arr:
                    entry = {
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ""),
                        "path": c.get("path", "/"),
                    }
                    if "secure" in c:
                        entry["secure"] = c["secure"]
                    if "httpOnly" in c:
                        entry["httpOnly"] = c["httpOnly"]
                    if "sameSite" in c:
                        s = c["sameSite"]
                        if s == "no_restriction":
                            entry["sameSite"] = "None"
                        elif s in ("strict", "lax"):
                            entry["sameSite"] = s.capitalize()
                        # "unspecified" → omit, let Playwright default
                    if "expirationDate" in c:
                        entry["expires"] = c["expirationDate"]
                    cookies.append(entry)
                return cookies
            except (json.JSONDecodeError, KeyError):
                pass

        # --- Format B: simple text ---
        cookies = []
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies.append({
                    "name": k.strip(), "value": v.strip(),
                    "domain": "", "path": "/", "url": origin_url,
                })
        return cookies

    def _handle_verify_cookie(self, body: dict):
        """Verify cookie by launching Playwright, loading cookie, and checking login status."""
        platform = body.get("platform", "")
        accounts = load_accounts()
        acct = accounts.get(platform, {})
        mode = acct.get("mode", "cookie")
        # API mode — skip browser verification
        if mode == "api":
            return self._json({"ok": True, "message": "API 模式，不使用浏览器 Cookie 验证"})
        cookie_str = (acct.get("cookie") or "").strip()
        if not cookie_str:
            return self._json({"ok": False, "error": "未配置 Cookie，请先在账号管理中填写 Cookie"})

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return self._json({"ok": False, "error": "Playwright 未安装。执行: pip install playwright && playwright install chromium"})

        login_urls = {
            "wechat_official": "https://mp.weixin.qq.com/",
            "toutiao": "https://mp.toutiao.com/",
            "xiaohongshu": "https://www.xiaohongshu.com/",
        }
        url = login_urls.get(platform)
        if not url:
            return self._json({"ok": False, "error": f"未知平台: {platform}"})

        try:
            cookies_to_set = self._parse_any_cookie(cookie_str, url)
            if not cookies_to_set:
                return self._json({"ok": False, "error": "无法解析 Cookie，请检查格式"})

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()

                # Navigate first to establish origin, then inject cookies, then reload
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                context.add_cookies(cookies_to_set)
                page.goto(url, timeout=20000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                current_url = page.url.lower()

                # Check for login redirect
                login_patterns = ["login", "passport", "auth", "signin", "qrcode"]
                is_login_page = any(p in current_url for p in login_patterns)

                browser.close()

                if is_login_page:
                    return self._json({"ok": False, "error": "Cookie 已过期或无效 — 浏览器被重定向到登录页，请重新获取 Cookie"})
                else:
                    return self._json({"ok": True, "message": f"Cookie 有效 — 成功访问 {platform}，当前页面: {current_url[:80]}"})

        except Exception as e:
            return self._json({"ok": False, "error": f"浏览器验证失败: {str(e)[:200]}"})

    # ── Helpers ───────────────────────────────────────────

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, html: str):
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(payload))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[autopublish] {args[0]}")


# ── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    server = HTTPServer(("0.0.0.0", port), Handler)

    # Detect environment
    pw = detect_playwright()
    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║       AutoPublish  多平台自动发布系统                  ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print(f"  ▶ 打开浏览器: http://localhost:{port}")
    print()
    if pw["available"]:
        print(f"  ✓ Playwright + Chromium 可用 — 支持真实发布")
    else:
        print(f"  ✗ {pw['message']}")
        print(f"    当前仅 Stub 安全模式可用")
    print()
    print(f"  按 Ctrl+C 停止服务")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务已停止\n")
        server.shutdown()
