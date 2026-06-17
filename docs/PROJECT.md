# Auto Content Production — 全自动内容生产流水线

## 项目概述

本机长跑、全自动为主、人可随时介入的多平台内容生产流水线。从热点采集 → AI 写作（多 Agent 对抗）→ 平台评分 + 配图 → 审核 → 自动发布。

### 一句话

一条指令走完：选题抓取 → 匹配人物语态 → 多 Agent 对抗写作（含 LLM + 图片生成）→ 三平台评分 → 审稿 → 发布。

### 技术栈

| 层 | 技术 |
|---|---|
| 编排器 | Python / FastAPI + SQLite |
| 写作引擎 | TypeScript / Express (Node.js) |
| 发布器 | Python (HTTP API + Playwright) |
| 图片生成 | Volcano Engine ARK `/v3/images/generations` (OpenAI 兼容) |
| 写作 LLM | Volcano Engine ARK (doubao-seed-1-6, OpenAI 兼容协议) |
| 采集器 | Python + 直连 HTTP 抓取 (头条 / 微博 / 小红书 / 新榜) |
| 人物蒸馏 | Python / FastAPI |
| 平台评分 | Python / FastAPI |
| 守护 | macOS launchd plist |

---

## 模块架构

```
                    ┌──────────────────────┐
                    │   orchestrator:8800  │  ← 总控 / 仪表板 / 状态机
                    └──┬──┬──┬──┬──┬──────┘
                       │  │  │  │  │
        ┌──────────────┘  │  │  │  └─────────┐
        ▼                 ▼  ▼  ▼            ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│select_topic  │  │   writing    │  │  Autopublish │
│   :8766      │  │   :8788      │  │   :8765      │
│ 选题采集匹配  │  │ AI写作+生图  │  │ 多平台发布    │
└──────────────┘  └──────────────┘  └──────────────┘
        │
┌──────────────┐  ┌──────────────┐
│distilled_    │  │platform_scorer│
│characters:8767│  │   :8789      │
│ 名人语态库    │  │ 多平台评分    │
└──────────────┘  └──────────────┘
```

### 各模块端口与运行状态

| 模块 | 端口 | 启动命令 | 状态 |
|------|------|---------|------|
| **orchestrator** | 8800 | `python3 server_v2.py` | ✅ 总控编排、状态机、仪表板 |
| **writing** | 8788 | `npx tsx server/index.ts` | ✅ 火山 LLM + 火山生图 |
| **Autopublish** | 8765 | `python3 server.py` | ✅ Markdown→HTML + 微信 CDN |
| **select_topic** | 8766 | `uvicorn server.app:app` | ✅ 热点采集与匹配 |
| **distilled_characters** | 8767 | `python3 main.py` | ✅ 名人语态数据库 |
| **platform_scorer** | 8789 | `python3 server.py` | ✅ 三平台评分 |
| **Web UI** | 8800 | (orchestrator 提供) | ✅ http://127.0.0.1:8800 |

---

## 最近变更（2026-06-17）

### 图片问题的根因与修复

#### 问题根因

发布的文章中图片显示为「文字描述」而不是真实图片。追踪全链路后发现三层问题：

| 层 | 问题 |
|---|---|
| **写作模块** | 图片生成后只有 OSS URL（DashScope 临时链接），**从未下载到本地**，`ImageAsset` 没有 `localPath` 字段 |
| **编排器** | 发布 payload 中 `cover_path` 恒为空，`image_paths` 恒为空 |
| **Autopublish** | 正文 Markdown `![alt](url)` 直接作为 `content` 传给微信 API，微信不渲染 Markdown 显示为纯文本 |

底层原因：**阿里云百炼 DashScope 账户欠费**，所有图片生成返回 400 Arrearage。

#### 修复方案（三层防御）

**Level 1 — 写作模块（根因修复）：**
- `shared/types.ts`: `ImageAsset` 新增 `localPath?: string` 字段
- `pipeline.ts`: 新增 `downloadImagesToLocal()`，图片生成后立即下载到 `data/assets/{taskId}/`
- `imageGeneration.ts`: 新增 `generateVolcanoImage()`，优先使用火山引擎生图

**Level 2 — 编排器（兜底）：**
- `scheduler_v2.py`: `_per_platform_payload` 中：
  - 从 `images[]` 中下载 OSS/HTTP 图片到临时文件
  - 如果 `cover_path` 仍为空，从正文 `![alt](url)` 提取第一张图下载作为封面

**Level 3 — Autopublish（最后防线）：**
- `wechat_api.py`: 新增 `_markdown_body_to_html()`：
  - `![alt](真实URL)` → 下载→上传微信 CDN→`<img>` 标签
  - `![alt](prompt://...)` → 完全清除
  - `## 标题` → `<h2>`、`**粗体**` → `<strong>`
  - 段落包裹 `<p>` + 换行 `<br>`
- `scheduler.py`: readiness 检查提前返回补上 `result` 字段，错误消息正确传播

### 配置变更

| 项目 | 之前 | 现在 |
|---|---|---|
| **写作 LLM** | DeepSeek (`sk-e694...`) | **火山引擎** doubao-seed-1-6 (`ep-20260617223809-snkhz`) |
| **图片生成** | 阿里百炼 wanx2.1（欠费） | **火山引擎** (`ep-20260418221504-6rj9s`) |
| **备份 LLM** | 阿里 Qwen (DashScope) | **火山引擎** 同一端点 |

### API 配置（.env）

```
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=ark-33595fa8-43db-405a-8ebe-c858af55939b-9a480
LLM_MODEL=ep-20260617223809-snkhz

QWEN_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
QWEN_MODEL=ep-20260617223809-snkhz
QWEN_API_KEY=ark-33595fa8-43db-405a-8ebe-c858af55939b-9a480

# 图片生成（火山引擎优先，DashScope 回退）
VOLCANO_IMAGE_API_KEY=ark-33595fa8-43db-405a-8ebe-c858af55939b-9a480
VOLCANO_IMAGE_ENDPOINT=ep-20260418221504-6rj9s

ALI_BAILIAN_API_KEY=sk-a9ca457acade4f5bb3722ea04a26a9d9
ALI_IMAGE_MODEL=wanx2.1-t2i-turbo
```

---

## 状态机流水线

```
collected → matched → writing → drafted → scored → reviewing → publishing → published
                                                      ↓              ↓
                                                   rejected        failed
```

- `failed` 可重试回到 `matched/writing/drafted/scored/reviewing/publishing`
- 终止态: `published`, `rejected`, `duplicated`
- 审稿超时 2 小时自动通过
- 每个状态转移写入 `audit_log`

### 调度器节奏

| 作业 | 频率 | 行为 |
|---|---|---|
| `tick` | 每 2 分钟 | 推进所有文章一步 |
| `check_review_timeouts` | 每 5 分钟 | 超 2h 自动发布 |
| `process_due_retries` | 每 1 分钟 | 失败文章重试 |
| `run_boost_publish` | 23:00 | 保底每平台至少 1 篇 |
| `run_sweep` | 每 3 小时 | 清理过期的 asset / 日志 |

---

## Agent 管理

仪表板「Agent 管理」Tab（`:8800/#agents`）可以查看和编辑所有 14 个写作子 Agent 的 system prompt：

| 集群 | Agent | 角色 |
|---|---|---|
| **写手集群** | 张素材 / 赵立意 / 李文章 / 钱人味 / 刘风格 / 写手主Agent | 素材→立意→写作→润色→风格→派单 |
| **编辑集群** | 吴查查 / 孙风控 / 周挑刺 / 编辑主Agent | 事实核查→合规→内容质检→汇总 |
| **运营集群** | 陈排版 / 章上线 / 标题大师 / 严反馈 | 排版→元数据→标题→终审 |

修改自动持久化到 `writing/config/agent-overrides.json`。

---

## 已知问题

1. **写作模块进程不稳定** — 在沙箱环境中，`npx tsx` 进程可能被系统杀死。如果仪表板显示 writing 模块 Down，需要重新启动：`cd writing && npx tsx server/index.ts`
2. **Toutiao cookie 过期** — 头条的 Playwright 发布依赖有效 cookie，需定期在仪表板「账号管理」页面更新
3. **旧文章图片** — 已写成的旧文章的 `final_package` 中图片是 `prompt://` 占位符，需要重走写作流程才能生成真实图片
4. **人物匹配** — 如果没有配置蒸馏人物，写作使用默认声线，文章风格较通用
5. **select_topic 采集** — 部分平台（小红书的 edith API 不稳定）可能采集失败，可手动重新触发

---

## 快速启动

```bash
# 1. 启动所有模块（按端口顺序）
cd Autopublish && python3 server.py &              # :8765
cd select_topic && python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8766 &
cd distilled_characters && python3 main.py --port 8767 &
cd writing && npx tsx server/index.ts &              # :8788
cd platform_scorer && python3 server.py &            # :8789
cd orchestrator && python3 server_v2.py &            # :8800

# 2. 打开仪表板
open http://127.0.0.1:8800

# 3. 仪表板操作
# - 点「采集选题」抓取热点
# - 点「同步选题」同步到流水线
# - 点「推进一步」手动触发
```

### 服务健康检查

```bash
curl http://127.0.0.1:8800/api/admin/services
# 返回各模块 Up/Down 状态
```
