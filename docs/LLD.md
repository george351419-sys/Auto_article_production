# 自动内容生产-发布系统 · 细节设计文档（LLD v1）

> 状态：**草案，待评审**
> 关联：[PRD.md](./PRD.md) v1.1 · [HLD.md](./HLD.md) v1.2
> 日期：2026-06-16

---

## 1. 文档目的

把 HLD 里"按概念"描述的内容落到**可直接写代码**的精度：
- 完整 DB schema（CREATE TABLE + 索引）
- 每个 API 端点的请求/响应字段类型
- 错误码完整枚举
- 重试 / 超时 / 限流的具体数值
- UI 页面线框 + 交互
- launchd plist / 配置文件 / 日志格式

本文档完成后，**任何独立工程师拿着 LLD 都能从零开始实现**。

---

## 2. 完整 DB Schema（编排器）

### 2.1 数据库文件

- 路径：`/orchestrator/data/pipeline.db`
- 引擎：SQLite 3，启用 WAL 模式
- 编码：UTF-8
- 时区：所有 `*_at` 字段存 UTC ISO 字符串

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

### 2.2 表定义

#### topic — 选题

```sql
CREATE TABLE topic (
    id              TEXT PRIMARY KEY,           -- UUID v4
    title           TEXT NOT NULL,
    title_normalized TEXT NOT NULL,             -- 去标点/小写/去停用词后
    source          TEXT NOT NULL,              -- 'auto' / 'user' / 'crawler:xxx'
    source_url      TEXT,                       -- 原文 URL（若有）
    brief           TEXT,                       -- 选题概述
    raw_material    TEXT,                       -- 原始素材 JSON
    entities        TEXT,                       -- JSON array, e.g. ["DeepSeek","梁文锋"]
    topic_keywords  TEXT,                       -- JSON array, e.g. ["AI融资","大模型"]
    status          TEXT NOT NULL,              -- collected/duplicated/matched/...
    dup_of_topic_id TEXT,                       -- 若重复，指向被复制的 topic
    user_submitted  INTEGER NOT NULL DEFAULT 0, -- 1 = 用户主动提交（永久保留）
    trace_id        TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX idx_topic_status ON topic(status);
CREATE INDEX idx_topic_created ON topic(created_at);
CREATE INDEX idx_topic_normalized ON topic(title_normalized);
```

#### article — 文章任务

```sql
CREATE TABLE article (
    id                  TEXT PRIMARY KEY,
    topic_id            TEXT NOT NULL REFERENCES topic(id),
    character_id        TEXT,                   -- 匹配的人物 ID
    status              TEXT NOT NULL,          -- writing/drafted/scored/reviewing/...
    writing_task_id     TEXT,                   -- writing 模块返回的 task_id
    final_package       TEXT,                   -- writing 返回的 finalPackage JSON
    retry_count         INTEGER NOT NULL DEFAULT 0,  -- 当前状态的重试计数
    next_retry_at       TEXT,                   -- 下次重试时间
    last_error_code     TEXT,
    last_error_message  TEXT,
    review_deadline_at  TEXT,                   -- reviewing 状态的超时点（+2h）
    trace_id            TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_article_status ON article(status);
CREATE INDEX idx_article_topic ON article(topic_id);
CREATE INDEX idx_article_retry ON article(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX idx_article_review ON article(review_deadline_at) WHERE status = 'reviewing';
```

#### score — 平台评分

```sql
CREATE TABLE score (
    id           TEXT PRIMARY KEY,
    article_id   TEXT NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    platform     TEXT NOT NULL,                 -- wechat / xiaohongshu / toutiao
    score        INTEGER NOT NULL,              -- 0–100
    reason       TEXT NOT NULL,
    generation_n INTEGER NOT NULL DEFAULT 1,    -- 第 N 次评分（改稿后重评 +1）
    generated_at TEXT NOT NULL,
    UNIQUE (article_id, platform, generation_n)
);
CREATE INDEX idx_score_article ON score(article_id);
```

#### publish — 发布记录

```sql
CREATE TABLE publish (
    id              TEXT PRIMARY KEY,
    article_id      TEXT NOT NULL REFERENCES article(id),
    platform        TEXT NOT NULL,
    status          TEXT NOT NULL,              -- pending/success/failed/skipped/duplicate
    platform_url    TEXT,                       -- 发布成功后的平台 URL
    platform_msg_id TEXT,                       -- 平台返回的 media_id 等
    error_code      TEXT,
    error_message   TEXT,
    scheduled_at    TEXT NOT NULL,
    executed_at     TEXT,
    duration_ms     INTEGER,
    trace_id        TEXT NOT NULL,
    UNIQUE (article_id, platform)
);
CREATE INDEX idx_publish_status ON publish(status);
CREATE INDEX idx_publish_scheduled ON publish(scheduled_at);
```

#### asset — 图片/封面落地

```sql
CREATE TABLE asset (
    id          TEXT PRIMARY KEY,
    article_id  TEXT NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    platform    TEXT,                           -- 该图片归属的平台（NULL=通用）
    kind        TEXT NOT NULL,                  -- 'cover' / 'inline'
    local_path  TEXT NOT NULL,                  -- 相对编排器根的路径
    origin_url  TEXT,                           -- OSS 原 URL（仅记录）
    bytes       INTEGER,
    sha256      TEXT,
    downloaded_at TEXT NOT NULL,
    deleted_at  TEXT                            -- 软删时间（实际文件已删）
);
CREATE INDEX idx_asset_article ON asset(article_id);
CREATE INDEX idx_asset_deleted ON asset(deleted_at) WHERE deleted_at IS NULL;
```

#### audit_log — 状态切换审计

```sql
CREATE TABLE audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type   TEXT NOT NULL,                -- topic / article / publish
    entity_id     TEXT NOT NULL,
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    trigger       TEXT NOT NULL,                -- auto/user/cron/retry/cleanup_timeout/...
    actor         TEXT,                         -- 'system' / user identifier
    payload_json  TEXT,                         -- 切换时的状态快照
    trace_id      TEXT NOT NULL,
    at            TEXT NOT NULL
);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_at ON audit_log(at);
```

#### cleanup_log — 清理任务日志

```sql
CREATE TABLE cleanup_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger         TEXT NOT NULL,              -- cron_3h / threshold_2_5g / manual
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    freed_bytes     INTEGER,
    deleted_topics  INTEGER DEFAULT 0,
    deleted_articles INTEGER DEFAULT 0,
    deleted_assets  INTEGER DEFAULT 0,
    deleted_logs    INTEGER DEFAULT 0,
    error_message   TEXT
);
```

#### settings — 运行时可调参数（key-value）

```sql
CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- 初始记录：
-- ('schema_version', '1')
-- ('cleanup.threshold_gb', '2.5')
-- ('cleanup.sweep_cron', '0 */3 * * *')
-- ('review.timeout_hours', '2')
-- ('boost.daily_check_hour', '23')
-- ('retry.max_attempts', '3')
```

### 2.3 迁移机制

- 编排器启动时读 `settings.schema_version`，与代码内常量比对
- 若 DB 不存在 → 执行 `migrations/0001_init.sql`
- 后续 schema 改动按 `0002_*.sql / 0003_*.sql` 顺序执行
- 不支持降级（向前兼容假设）

---

## 3. 模块契约详细 Schema

### 3.1 通用约定

```yaml
# 所有请求/响应都用 JSON
Content-Type: application/json

# 编排器调用业务模块时的 headers
X-Trace-Id: <UUID v4>
Idempotency-Key: <UUID v4>           # POST 必带
User-Agent: orchestrator/1.0

# 业务模块返回错误时的 body 格式
{
  "error": {
    "code": "WRITE.EXTERNAL.LLM_TIMEOUT",
    "message": "...",
    "details": { ... }   # 可选
  }
}
```

### 3.2 健康检查 `/health`（所有模块）

```yaml
GET /health
Response 200:
{
  "ok": true,
  "module": "writing",
  "version": "1.2.3",
  "uptime_seconds": 86400,
  "deps_ok": true            # 上游依赖（如 DB、LLM）是否健康
}
```

### 3.3 契约自描述 `/contract`（所有模块）

```yaml
GET /contract
Response 200:
{
  "module": "writing",
  "contract_version": "1.0",
  "endpoints": [
    { "path": "/api/tasks", "method": "POST", "purpose": "create_task" },
    { "path": "/api/tasks/{id}/run", "method": "POST", "purpose": "run_task" },
    ...
  ]
}
```

### 3.4 `distilled_characters` 详细

```yaml
POST /api/match
Request:
{
  "topic_brief": "string, ≤500字",
  "topic_keywords": ["string"],     # 可选，提高匹配准确度
  "trace_id": "uuid"
}
Response 200:
{
  "matched": {
    "character_id": "uuid",
    "character_name": "string",
    "voice_summary": "string",
    "match_score": 87               # 0-100
  },
  "alternatives": [                 # 候选项，UI 备用
    { "character_id": "...", "match_score": 75 }
  ]
}
```

### 3.5 `select_topic` 详细

```yaml
POST /api/collect/trigger
Request: {}
Response 202:
{
  "collect_id": "uuid",
  "estimated_seconds": 60
}
```

```yaml
GET /api/topics?status=ready&limit=30
Response 200:
{
  "topics": [
    {
      "id": "uuid",
      "title": "string",
      "brief": "string",
      "source": "string",
      "source_url": "string|null",
      "raw_material": { ... },        # 原始素材
      "discovered_at": "iso8601"
    }
  ]
}
```

```yaml
POST /api/topics                       # 用户提交选题
Request:
{
  "title": "string",
  "brief": "string|null",
  "source_url": "string|null",
  "raw_material": "string|null"
}
Response 201:
{
  "id": "uuid",
  "created_at": "iso8601"
}
```

### 3.6 `writing` 详细

```yaml
POST /api/tasks
Request:
{
  "topic": "string",
  "topic_brief": "string",
  "character_id": "uuid",
  "platforms": ["wechat", "xiaohongshu", "toutiao"],
  "promotion_goal": "string",
  "source_materials": [
    { "title": "...", "url": "...", "snippet": "..." }
  ]
}
Response 201:
{
  "task_id": "uuid",
  "estimated_seconds": 600
}
```

```yaml
POST /api/tasks/{task_id}/run
Response 202:
{
  "task_id": "uuid",
  "started_at": "iso8601"
}
```

```yaml
GET /api/tasks/{task_id}
Response 200:
{
  "task_id": "uuid",
  "status": "pending|running|completed|failed",
  "progress": 0-100,
  "current_stage": "string",          # e.g. "drafting", "image_generation"
  "final_package": {                  # 完成时才有
    "platforms": [
      {
        "platform": "wechat",
        "titles": ["..."],            # 至少 1 个，可能多个备选
        "formatted_article": "...",
        "summary": "...",
        "keywords": ["..."],
        "tags": ["..."],
        "pinned_comment": "...",
        "images": [
          {
            "id": "string",
            "url": "https://oss.../xxx.png",  # OSS 临时 URL
            "prompt": "...",
            "kind": "cover|inline",
            "placement": "string"
          }
        ],
        "cover_plan": { "url": "...", "title_overlay": "..." }
      }
    ]
  },
  "error": { "code": "...", "message": "..." }     # 失败时
}
```

### 3.7 `platform_scorer` 详细（新模块）

```yaml
POST /api/score
Request:
{
  "article_id": "uuid",
  "topic_brief": "string",
  "platforms": ["wechat","xiaohongshu","toutiao"],
  "package_summary": {                # 简化版 finalPackage，节省 token
    "platforms": [
      {
        "platform": "wechat",
        "title": "string",
        "summary": "string",
        "tags": ["..."],
        "image_count": 5
      }
    ]
  }
}
Response 200:
{
  "scores": {
    "wechat":      { "score": 88, "reason": "..." },
    "xiaohongshu": { "score": 62, "reason": "..." },
    "toutiao":     { "score": 75, "reason": "..." }
  },
  "generated_at": "iso8601",
  "model": "deepseek-chat"
}
```

**评分规则（写进 platform_scorer 的 system prompt，LLD 不展开 prompt 详文）：**
- 0-100 分制，60 为基准线
- 必须给出 reason（≤120字），指明强项+弱项
- 阈值约定：≥ 70 推荐发布；50-69 边缘；< 50 不建议

### 3.8 `Autopublish` 详细

```yaml
POST /api/publish
Request:
{
  "article_id": "uuid",
  "platform": "wechat_official|xiaohongshu|toutiao",
  "title": "string",
  "body": "string",                   # markdown 或 HTML
  "summary": "string",
  "tags": ["string"],
  "keywords": ["string"],
  "author": "string",
  "location": "string",
  "account_label": "string",
  "topic_title": "string",
  "cover_path": "string|null",        # 本地路径（绝对路径）
  "image_paths": ["string"],          # 本地路径
  "pinned_comment": "string|null"
}
Response 200:
{
  "plan_id": "uuid",
  "status": "success|failed|duplicate|retrying",
  "platform_url": "string|null",
  "platform_msg_id": "string|null",
  "error_message": "string|null",
  "duration_ms": 12345
}
```

```yaml
GET /api/publish/{plan_id}
Response 200:
{
  "plan_id": "uuid",
  "status": "...",
  "history": [
    { "at": "iso8601", "event": "started" },
    { "at": "iso8601", "event": "cookie_loaded" },
    ...
  ]
}
```

### 3.9 编排器对外 API（供 Web UI 使用）

| 路径 | 方法 | 用途 |
|---|---|---|
| `GET /api/topics?status=...` | 列选题 |
| `POST /api/topics` | 用户提选题 |
| `GET /api/articles?status=...` | 列文章任务 |
| `GET /api/articles/{id}` | 文章详情（含 score、publish、asset） |
| `POST /api/articles/{id}/review` | 审稿动作 `{action: approve/reject, modifications: {...}}` |
| `POST /api/articles/{id}/rescore` | 重新评分 |
| `POST /api/articles/{id}/retry` | 重试失败任务 |
| `POST /api/articles/{id}/skip-platform` | 发布阶段跳过某平台 |
| `POST /api/articles/{id}/terminate` | 强制终止 |
| `GET  /api/admin/cleanup-history` | 清理历史 |
| `POST /api/admin/cleanup-now` | 手动触发清理 |
| `GET  /api/admin/services` | 各模块健康状态 |
| `GET  /api/settings` / `PUT /api/settings/{key}` | 运行时参数 |
| `GET  /api/dashboard` | 主面板聚合数据 |

---

## 4. 错误码完整表

格式：`MODULE.CATEGORY.SPECIFIC`

### 4.1 编排器 (ORCH)

| Code | 含义 | HTTP |
|---|---|---|
| `ORCH.INPUT.MISSING_FIELD` | 必填字段缺失 | 400 |
| `ORCH.INPUT.INVALID_STATUS` | 状态非法切换 | 409 |
| `ORCH.INPUT.ARTICLE_NOT_FOUND` | 文章不存在 | 404 |
| `ORCH.INTERNAL.DB_LOCKED` | SQLite 锁等待超时 | 500 |
| `ORCH.INTERNAL.STATE_MACHINE_INVARIANT` | 状态机不变量破坏 | 500 |
| `ORCH.EXTERNAL.MODULE_UNREACHABLE` | 业务模块不可达 | 502 |
| `ORCH.EXTERNAL.MODULE_TIMEOUT` | 业务模块超时 | 504 |

### 4.2 select_topic (SELECT)

| Code | 含义 | HTTP |
|---|---|---|
| `SELECT.INPUT.INVALID_TITLE` | 标题为空或过长 | 400 |
| `SELECT.EXTERNAL.CRAWLER_FAIL` | 抓取源失败 | 502 |
| `SELECT.INTERNAL.DEDUP_LLM_FAIL` | 实体提取失败 | 500 |

### 4.3 distilled_characters (DISTILL)

| Code | 含义 | HTTP |
|---|---|---|
| `DISTILL.INPUT.NO_BRIEF` | 缺少 topic_brief | 400 |
| `DISTILL.INTERNAL.NO_MATCH` | 无可用人物 | 503 |

### 4.4 writing (WRITE)

| Code | 含义 | HTTP |
|---|---|---|
| `WRITE.INPUT.MISSING_CHARACTER` | character_id 缺失或不存在 | 400 |
| `WRITE.TIMEOUT.LLM_RESPONSE` | LLM 超时 | 504 |
| `WRITE.EXTERNAL.LLM_RATELIMIT` | LLM 限流 | 429 |
| `WRITE.EXTERNAL.IMAGE_GEN_FAIL` | 图片生成失败 | 502 |
| `WRITE.INTERNAL.AGENT_LOOP_LIMIT` | 对抗 agent 迭代超限 | 500 |

### 4.5 platform_scorer (SCORE)

| Code | 含义 | HTTP |
|---|---|---|
| `SCORE.INPUT.EMPTY_PACKAGE` | 入参 package 为空 | 400 |
| `SCORE.TIMEOUT.LLM_RESPONSE` | LLM 超时 | 504 |
| `SCORE.EXTERNAL.LLM_FAIL` | LLM 调用失败 | 502 |
| `SCORE.INTERNAL.PARSE_FAIL` | LLM 输出无法解析为分数 JSON | 500 |

### 4.6 Autopublish (PUBLISH)

| Code | 含义 | HTTP |
|---|---|---|
| `PUBLISH.INPUT.MISSING_PLATFORM` | platform 字段缺失或非法 | 400 |
| `PUBLISH.INPUT.NO_IMAGES` | 小红书无图片 | 400 |
| `PUBLISH.INTERNAL.COOKIE_NOT_FOUND` | Cookie 文件不存在 | 500 |
| `PUBLISH.INTERNAL.COOKIE_EXPIRED` | Cookie 过期被平台拒 | 401 |
| `PUBLISH.EXTERNAL.WECHAT_ERRCODE_40001` | 微信 access_token 失效 | 502 |
| `PUBLISH.EXTERNAL.WECHAT_ERRCODE_40004` | 微信不合法的 media_id | 502 |
| `PUBLISH.EXTERNAL.XHS_BIND_NOT_BIND` | 小红书账号未绑定 | 502 |
| `PUBLISH.EXTERNAL.TOUTIAO_RISK_BLOCK` | 头条风控拦截 | 502 |
| `PUBLISH.EXTERNAL.IMAGE_403` | 图片 URL 403（OSS 过期） | 502 |
| `PUBLISH.TIMEOUT.PLAYWRIGHT` | Playwright 操作超时 | 504 |

---

## 5. 重试 / 超时 / 限流 参数表

| 场景 | 参数 | 值 |
|---|---|---|
| 编排器调用业务模块 HTTP | 超时 | 30s |
| 编排器调 writing GET（轮询） | 超时 | 10s |
| 业务模块内部超时（契约约束） | 上限 | 25s |
| 业务模块超时 → 重试 | 间隔 | 30s → 2min → 10min |
| 业务模块超时 → 重试 | 最大次数 | 3 |
| 自动重试总时长上限 | — | 15 min |
| LLM 调用超时（写作 / 评分） | 单次 | 60s |
| LLM 调用重试（在业务模块内） | 次数 | 2 次 |
| 写作任务 GET 轮询频率 | — | 每 10s |
| 写作任务整体上限 | — | 30 min |
| 审稿超时 | — | 2h，自动发 |
| 23:00 保底触发 | cron | `0 23 * * *` |
| 清理 sweep cron | — | `0 */3 * * *` |
| 阈值守护巡检 | — | 每 10 min |
| 清理触发阈值 | — | 2.5 GB |
| VACUUM SQLite | cron | `0 3 * * 0`（周日凌晨 3 点） |
| 健康检查频率 | — | 每 30s |
| Web UI 数据刷新 | 前端轮询 | 每 5s（任务详情）/ 每 30s（列表） |

---

## 6. UI 页面规格

### 6.1 路由

| 路径 | 页面 |
|---|---|
| `/` | 主面板 Dashboard |
| `/topics` | 选题列表 |
| `/topics/{id}` | 选题详情 |
| `/articles` | 文章任务列表 |
| `/articles/{id}` | 文章详情 / 审稿 |
| `/services` | 各模块健康状态 |
| `/settings` | 系统设置 |
| `/cleanup` | 清理历史 |

### 6.2 主面板 Dashboard 线框

```
┌─────────────────────────────────────────────────────────────────┐
│  自动内容生产系统    [模块状态: ●●●●● 全绿]  [清理: 1.2G/2.5G]   │
├─────────────────────────────────────────────────────────────────┤
│  今日发布进度                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                         │
│  │公众号 1/N│ │小红书 1/N│ │ 头条 1/N │                         │
│  │   ✓     │ │   ✓     │ │   ✓     │                          │
│  └──────────┘ └──────────┘ └──────────┘                         │
│                                                                  │
│  待审稿件 (3)                            [全部审稿 →]            │
│  • [稿件标题1]      生成 30 分钟前    剩 1h30m   [审稿]          │
│  • [稿件标题2]      生成 1 小时前      剩 1h     [审稿]          │
│                                                                  │
│  最近失败 (1)                                                    │
│  • [稿件标题3]   PUBLISH.EXTERNAL.IMAGE_403   [重试][终止]       │
│                                                                  │
│  快捷操作                                                        │
│  [手动提选题] [立即抓选题] [立即清理] [查看日志]                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 文章详情 / 审稿页线框

```
┌─────────────────────────────────────────────────────────────────┐
│  文章 {{title}}      状态: reviewing    trace: a3f...82d        │
├─────────────────────────────────────────────────────────────────┤
│  时间线                                                          │
│  collected → matched → writing → drafted → scored → reviewing    │
│                                                                  │
│  评分                                          [重新评分]        │
│  ┌──────────────┬──────┬───────────────────────────────────┐    │
│  │公众号        │ 88   │ 深度长文契合公众号读者偏好...     │    │
│  │小红书        │ 62   │ 图片占比不足，标题缺少 emoji...   │    │
│  │头条          │ 75   │ 时效性强，适合头条推荐...         │    │
│  └──────────────┴──────┴───────────────────────────────────┘    │
│                                                                  │
│  [Tab: 公众号 | 小红书 | 头条]                                   │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ 标题: [可编辑]                                          │     │
│  │ 摘要: [可编辑]                                          │     │
│  │ 正文: [可编辑富文本]                                    │     │
│  │ 封面: [图片预览, 可替换]                                │     │
│  │ 标签: [可编辑]                                          │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  [保存修改]  [通过并发布]  [驳回]  [跳过此平台]                  │
│                                                                  │
│  超时倒计时: 1h 23m 后自动发布                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 6.4 服务健康页

```
模块            状态    版本      uptime     最后失败
─────────────────────────────────────────────────────
orchestrator   ●Up    1.0.0    2d 4h      —
distilled_ch   ●Up    1.2.3    1d 12h     —
select_topic   ●Up    1.1.0    1d 12h     2h 前: SELECT.EXTERNAL.CRAWLER_FAIL
writing        ●Up    2.0.1    1d 12h     —
platform_sc    ●Up    1.0.0    8h         —
Autopublish    ⚠Slow  3.0.5    1d 12h     30m 前: PUBLISH.TIMEOUT.PLAYWRIGHT

[重启全部] [打开 cookie 管理]
```

### 6.5 交互约束

- 所有"危险操作"（驳回 / 终止）必须二次确认
- 审稿编辑框启用自动保存草稿（每 30s 写本地存储）
- 倒计时实时显示（前端 setInterval 每秒更新）
- 列表页支持按 status / source / 日期筛选

---

## 7. launchd plist 模板

路径：`~/Library/LaunchAgents/com.bessie.autocontent.{module}.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bessie.autocontent.{MODULE_NAME}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{MODULE_ROOT}/server.py</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>{PORT}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{MODULE_ROOT}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>AUTO_CONTENT_CONFIG</key>
        <string>/Users/bessie/cursor/Auto_content_production/shared_config.json</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>{MODULE_ROOT}/logs/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{MODULE_ROOT}/logs/launchd.stderr.log</string>
</dict>
</plist>
```

**6 个 plist 生成（用脚本批量渲染）：**
- `com.bessie.autocontent.orchestrator.plist` (port 8800)
- `com.bessie.autocontent.distilled_characters.plist` (8767)
- `com.bessie.autocontent.select_topic.plist` (8766)
- `com.bessie.autocontent.writing.plist` (8788)
- `com.bessie.autocontent.platform_scorer.plist` (8789)
- `com.bessie.autocontent.autopublish.plist` (8765)

---

## 8. 配置文件 schema

### 8.1 `shared_config.json` 最终形态

```json
{
  "version": "1.0",
  "llm": {
    "deepseek": {
      "api_key": "sk-...",
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-chat"
    },
    "qwen": {
      "api_key": "sk-...",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "model": "qwen3.5-flash"
    }
  },
  "services": {
    "orchestrator_url":         "http://127.0.0.1:8800",
    "distilled_characters_url": "http://127.0.0.1:8767",
    "select_topic_url":         "http://127.0.0.1:8766",
    "writing_url":              "http://127.0.0.1:8788",
    "platform_scorer_url":      "http://127.0.0.1:8789",
    "autopublish_url":          "http://127.0.0.1:8765"
  },
  "publishing": {
    "account_label": "my-main-account",
    "author": "烽灵",
    "location": "北京",
    "platforms": ["wechat_official", "xiaohongshu", "toutiao"]
  },
  "pipeline": {
    "auto_scan_cron": "0 8 * * *",
    "review_timeout_hours": 2,
    "boost_check_hour": 23,
    "auto_dispatch_to_writing": true
  },
  "cleanup": {
    "sweep_cron": "0 */3 * * *",
    "threshold_gb": 2.5,
    "guard_check_minutes": 10,
    "vacuum_cron": "0 3 * * 0"
  },
  "scoring": {
    "publish_threshold": 70,
    "boost_min_score": 50
  }
}
```

### 8.2 编排器 `.env`

```bash
ORCH_DB_PATH=./data/pipeline.db
ORCH_ASSETS_DIR=./assets
ORCH_LOGS_DIR=./logs
ORCH_LOG_LEVEL=INFO
ORCH_LOG_RETENTION_DAYS=14
```

---

## 9. 日志格式规范

### 9.1 编排器日志（结构化 JSON Lines）

文件：`/orchestrator/logs/YYYY-MM-DD.log`

每行一条 JSON：
```json
{
  "ts": "2026-06-16T08:34:21.123Z",
  "level": "INFO",
  "logger": "orchestrator.state_machine",
  "trace_id": "a3f2c1...",
  "entity_type": "article",
  "entity_id": "uuid",
  "event": "state_transition",
  "from": "writing",
  "to": "drafted",
  "duration_ms": 612443,
  "extra": { ... }
}
```

**强制字段**：`ts`, `level`, `logger`, `event`
**强烈建议**：`trace_id`, `entity_id`

### 9.2 业务模块日志

模块自由格式，但 **必须打印 `trace_id`** 用于关联。

---

## 10. 文件目录结构（最终落定）

```
/Auto_content_production/
├── docs/
│   ├── PRD.md
│   ├── HLD.md
│   ├── LLD.md
│   └── DEV_PLAN.md         ← 下一步产出
├── shared_config.json
├── orchestrator/
│   ├── server.py
│   ├── state_machine.py
│   ├── scheduler.py
│   ├── bridge/             ← 调业务模块的 HTTP client
│   │   ├── distilled.py
│   │   ├── select_topic.py
│   │   ├── writing.py
│   │   ├── scorer.py
│   │   └── autopublish.py
│   ├── cleanup.py
│   ├── migrations/
│   │   └── 0001_init.sql
│   ├── data/pipeline.db
│   ├── assets/{article_id}/
│   ├── logs/YYYY-MM-DD.log
│   └── static/             ← Web UI
├── distilled_characters/
│   └── adapters/contract.py   ← 新增 adapter 层
├── select_topic/
│   └── adapters/contract.py
├── writing/
│   └── adapters/contract.py
├── platform_scorer/        ← 新建模块
│   ├── server.py
│   ├── prompts/system.md
│   └── adapters/contract.py
├── Autopublish/
│   └── adapters/contract.py
├── deploy/
│   ├── launchd/            ← plist 模板
│   └── scripts/install.sh
└── .archive/               ← 旧 DB 备份
```

---

## 11. 已确定的设计参数总表（速查）

| 项目 | 值 |
|---|---|
| 审稿超时 | 2 小时 |
| 保底触发时间 | 每日 23:00 |
| 评分阈值（推荐发布） | ≥ 70 |
| 评分阈值（保底候选） | ≥ 50 |
| 失败自动重试 | 3 次，30s/2min/10min |
| 重试总时长 | ≤ 15 min |
| 清理 sweep 周期 | 3 小时 |
| 清理阈值 | 2.5 GB |
| 阈值守护频率 | 10 分钟 |
| 选题去重时间窗 | 7 天 |
| L2 去重 Jaccard 阈值 | ≥ 0.7 |
| 已发布图片保留 | 7 天 |
| rejected 文章保留 | 14 天 |
| duplicated 选题保留 | 7 天 |
| 卡死任务转 failed | 48 小时 |
| failed 转 rejected | 7 天 |
| 编排器日志保留 | 14 天 |
| HTTP 超时 | 30s |
| LLM 超时 | 60s |
| 健康检查频率 | 30s |

---

## 12. 文档版本

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-06-16 | 初版，待评审 |
