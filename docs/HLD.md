# 自动内容生产-发布系统 · 高层设计文档（HLD v1）

> 状态：**草案，待评审**
> 关联：[PRD.md](./PRD.md) v1.1
> 日期：2026-06-16

---

## 1. 文档目的

把 PRD 里抽象的需求落到**架构形态**：模块边界、调用方向、数据流、状态机、契约骨架、DB 概念模型。

本文档**不包含**：
- 具体字段名、字段类型（→ LLD）
- 具体 SQL 语句（→ LLD）
- 错误码完整枚举（→ LLD）
- 代码实现细节（→ 开发计划）

---

## 2. 架构总览

### 2.1 系统拓扑

```
                        ┌──────────────────────────┐
                        │     Web UI (浏览器)       │
                        │  127.0.0.1:8800 (静态)    │
                        └──────────┬───────────────┘
                                   │ HTTP/JSON
                                   ▼
                ┌────────────────────────────────────┐
                │       编排器 Orchestrator           │
                │       127.0.0.1:8800                │
                │  ┌──────────────────────────────┐   │
                │  │ • API Layer (FastAPI)        │   │
                │  │ • State Machine Engine       │   │
                │  │ • Scheduler (cron+保底+审稿)  │   │
                │  │ • Retry/Backoff Controller   │   │
                │  │ • Bridge Clients (HTTP)      │   │
                │  └──────────────────────────────┘   │
                │  ┌──────────────────────────────┐   │
                │  │ SQLite: pipeline.db          │   │
                │  │ Files: assets/ logs/         │   │
                │  └──────────────────────────────┘   │
                └─┬──────┬──────┬──────┬──────┬──────┘
                  │      │      │      │      │
            ┌─────▼┐  ┌──▼───┐ ┌▼────┐ ┌▼────┐ ┌▼─────────┐
            │distil│  │select│ │writ │ │plat │ │Autopub-  │
            │led_  │  │_topic│ │ing  │ │form_│ │lish      │
            │chars │  │      │ │     │ │scorr│ │          │
            │ 8767 │  │ 8766 │ │ 8788│ │ 8789│ │ 8765     │
            └──────┘  └──────┘ └─────┘ └─────┘ └──────────┘
              人物         选题         写作       评分        发布
```

### 2.2 模块清单与职责

| 模块 | 端口 | 进程 | 职责（一句话） |
|---|---|---|---|
| `orchestrator` | 8800 | 编排器 + Web UI | 调度、状态机、持久化、UI 入口 |
| `distilled_characters` | 8767 | 已有 | 维护人物语态库，按选题返回最佳人物 |
| `select_topic` | 8766 | 已有 | 抓取热点选题、与人物匹配候选 |
| `writing` | 8788 | 已有 | 多 agent 对抗写作，产出多平台稿件包 |
| `platform_scorer` | 8789 | **新增** | 对稿件包按平台维度打分+理由 |
| `Autopublish` | 8765 | 已有 | 三平台自动发布（公众号 / 小红书 / 头条） |

### 2.3 关键设计原则

1. **编排器是唯一持久化源**：业务模块的内部 DB 视为缓存，编排器 DB 是 source of truth
2. **业务模块无状态**（视编排器视角）：编排器随时可重发同一请求，模块自己负责幂等
3. **同步 HTTP 调用为主**：MVP 不引入消息队列，编排器用 asyncio 协程并发
4. **失败不丢任务**：任务任何环节崩溃，编排器重启后能恢复
5. **契约 > 代码**：模块间只看契约 schema，不互相理解实现

---

## 3. 数据流

### 3.1 主流程（全自动）

```
┌────────┐ cron 08:00       ┌─────────────────┐
│调度器  ├──触发─────────────►│ select_topic    │
└────────┘                    │ POST /collect   │
                              └────────┬────────┘
                                       │ 返回 topic[]
                                       ▼
                              ┌──────────────────┐
                              │ 编排器 去重 L1+L2 │
                              │ (本地规则)        │
                              └────────┬─────────┘
                                       │ 非重复 topic
                                       ▼
                              ┌──────────────────┐
                              │ distilled_chars  │
                              │ POST /match      │
                              └────────┬─────────┘
                                       │ character_id
                                       ▼
                              ┌──────────────────┐
                              │ writing          │
                              │ POST /tasks      │
                              │ POST /tasks/run  │
                              │ GET  /tasks/{id} │← 轮询
                              └────────┬─────────┘
                                       │ finalPackage
                                       ▼
                              ┌──────────────────┐
                              │ 编排器 图片落地    │
                              │ 下载 OSS → 本地   │
                              └────────┬─────────┘
                                       ▼
                              ┌──────────────────┐
                              │ platform_scorer  │
                              │ POST /score      │
                              └────────┬─────────┘
                                       │ scores
                                       ▼
                              ┌──────────────────┐
                              │ 编排器 审稿队列   │
                              │ 2h 超时计时       │
                              └────────┬─────────┘
                                       │
                          ┌────────────┼────────────┐
                          ▼            ▼            ▼
                       人工通过     超时         人工驳回
                          │            │            │
                          ▼            ▼            ▼
                              ┌──────────────────┐
                              │ Autopublish      │
                              │ execute_publish  │
                              │ (按 scorer 评分)  │
                              └────────┬─────────┘
                                       ▼
                                  published
```

### 3.2 用户提选题流（S2）

编排器跳过 `select_topic /collect`，直接 `select_topic POST /topics`（用户提交的选题入库）→ 后续同主流程。

### 3.3 23:00 保底调度流

```
每日 23:00 cron 触发
  ↓
扫描今日已发布表，统计每平台 count
  ↓
For 每个 count==0 的平台:
  ↓
  从今日 scored 状态的稿件中，挑选该平台评分最高的一篇
  ↓
  绕过审稿队列直接进入 publishing
```

### 3.4 失败干预流（S4）

任何环节失败 → 任务进入 `failed`，**自动重试触发**（最多 3 次，30s/2min/10min）→ 若仍失败则停在 `failed` 等待人工。

人工动作：
- "重试" → 任务回到上一个状态，重置 retry_count=0
- "跳过该平台" → 仅 publishing 阶段，移除该平台后继续其他平台
- "终止" → 强制置为 `rejected`

---

## 4. 状态机详细规则

### 4.1 状态列表

| 状态 | 是否终态 | 入口条件 | 出口条件 |
|---|---|---|---|
| `collected` | 否 | 选题入库（抓取/用户） | 去重通过 → matched；去重失败 → duplicated |
| `duplicated` | **是** | 命中去重规则 | — |
| `matched` | 否 | 人物匹配成功 | 写作任务创建 → writing |
| `writing` | 否 | 写作模块开始 | 写作完成 → drafted；写作失败 → failed |
| `drafted` | 否 | finalPackage 落库 + 图片落地 | 评分完成 → scored |
| `scored` | 否 | 平台评分落库 | 进入审稿队列 → reviewing |
| `reviewing` | 否 | 等待人工或超时 | 通过/超时 → publishing；驳回 → rejected |
| `publishing` | 否 | 发布开始 | 至少 1 个平台成功 → published；全失败 → failed |
| `published` | **是** | 至少 1 个平台 success | — |
| `failed` | 否 | 任一环节失败 | 自动重试 / 人工干预 |
| `rejected` | **是** | 人工驳回 | — |

### 4.2 状态切换不变量

- 每次切换必须写一条 `audit_log`（包含 from_state, to_state, trigger, payload_snapshot）
- 切换是原子操作（DB 事务）
- 任何状态都必须可序列化为 JSON（重启可恢复）

### 4.3 重试规则

- **每个状态独立计数**：进入 `writing` 时 retry_count_writing=0
- 进入 `failed` 状态 → 调度器检查 `retry_count < 3` → 触发延迟重试任务
- 重试间隔：`30s × 4^retry_count` → 30s / 2min / 10min
- 重试上限触发 → 留在 `failed`，等待人工

### 4.4 终态处理

- `duplicated` / `published` / `rejected` 进入归档，UI 默认不显示但可查
- `failed` 超过 24h 未处理 → UI 红色高亮提醒

---

## 5. 模块契约（顶层 schema）

> **设计约定**：所有模块对编排器暴露**完全相同形态的 5 类接口**。具体字段在 LLD。

### 5.1 通用接口（所有模块必须提供）

| 路径 | 方法 | 用途 |
|---|---|---|
| `/health` | GET | 健康检查，返回 `{ok, uptime, version}` |
| `/contract` | GET | 返回契约版本号 + 该模块支持的业务端点列表 |

### 5.2 业务端点（按模块）

#### `distilled_characters` (8767)
| 路径 | 方法 | 输入要点 | 输出要点 |
|---|---|---|---|
| `/api/characters` | GET | — | 人物列表 |
| `/api/match` | POST | topic_brief | matched_character_id + score |

#### `select_topic` (8766)
| 路径 | 方法 | 输入要点 | 输出要点 |
|---|---|---|---|
| `/api/collect/trigger` | POST | — | 触发抓取，返回任务句柄 |
| `/api/topics` | GET | status, limit | topic[] |
| `/api/topics` | POST | topic_brief | 用户提交选题入库 |
| `/api/topics/{id}` | GET | — | topic 详情 |

#### `writing` (8788)
| 路径 | 方法 | 输入要点 | 输出要点 |
|---|---|---|---|
| `/api/tasks` | POST | topic + character + platforms | task_id |
| `/api/tasks/{id}/run` | POST | — | 启动写作 |
| `/api/tasks/{id}` | GET | — | task 状态 + finalPackage(若完成) |

#### `platform_scorer` (8789) **新模块**
| 路径 | 方法 | 输入要点 | 输出要点 |
|---|---|---|---|
| `/api/score` | POST | finalPackage | `{wechat:{score,reason}, ...}` |

#### `Autopublish` (8765)
| 路径 | 方法 | 输入要点 | 输出要点 |
|---|---|---|---|
| `/api/publish` | POST | PublishInput | publish_result |
| `/api/publish/{plan_id}` | GET | — | 发布进度 |

### 5.3 契约统一约束

1. **时间字段**：ISO 8601 UTC（`2026-06-16T12:34:56Z`）
2. **ID 字段**：UUID v4 字符串
3. **错误响应**：HTTP 4xx/5xx + body `{error: {code, message, details}}`
4. **trace_id**：所有请求支持 `X-Trace-Id` header，模块原样回传到日志和响应
5. **幂等键**：所有 POST 必须接受 `Idempotency-Key` header，重复请求返回相同结果
6. **超时契约**：模块自己设的内部超时必须 ≤ 25s（编排器 30s 留 5s 网络余量）

---

## 6. 错误码命名规范

格式：`{MODULE}.{CATEGORY}.{SPECIFIC}`

- `MODULE`: ORCH / DISTILL / SELECT / WRITE / SCORE / PUBLISH
- `CATEGORY`: INPUT / EXTERNAL / INTERNAL / TIMEOUT / RATELIMIT
- `SPECIFIC`: 蛇形小写

**示例**：
- `PUBLISH.EXTERNAL.WECHAT_ERRCODE_40004`
- `WRITE.TIMEOUT.LLM_RESPONSE`
- `ORCH.INPUT.MISSING_FIELD`
- `PUBLISH.INTERNAL.COOKIE_NOT_FOUND`

完整错误码表在 LLD 落定。

---

## 7. DB 概念模型（编排器）

### 7.1 主要实体

```
┌─────────────┐         ┌─────────────┐         ┌──────────────┐
│   topic     │ 1     1 │   article   │ 1     N │   publish    │
│             ├─────────┤             ├─────────┤              │
│ id          │         │ id          │         │ id           │
│ title       │         │ topic_id    │         │ article_id   │
│ source      │         │ status      │         │ platform     │
│ entities    │         │ retry_count │         │ status       │
│ topic_kws   │         │ payload     │         │ url          │
│ status      │         │ created_at  │         │ scheduled_at │
│ created_at  │         └──────┬──────┘         └──────────────┘
└─────────────┘                │
                               │ 1
                          ┌────▼────────┐
                          │   score     │
                          │             │
                          │ article_id  │
                          │ platform    │
                          │ score       │
                          │ reason      │
                          │ generated_at│
                          └─────────────┘

┌─────────────┐
│ audit_log   │ ← 每次状态切换写一条
│             │
│ id          │
│ entity_type │ (topic / article / publish)
│ entity_id   │
│ from_state  │
│ to_state    │
│ trigger     │ (auto/user/cron/retry)
│ payload     │ (snapshot JSON)
│ trace_id    │
│ at          │
└─────────────┘

┌─────────────┐
│   asset     │ ← 图片落地表
│             │
│ id          │
│ article_id  │
│ platform    │
│ local_path  │
│ origin_url  │ (OSS 原 URL，仅记录)
│ kind        │ (cover / inline)
└─────────────┘
```

### 7.2 关系约束

- `topic 1→0..1 article`（被去重的 topic 没有 article）
- `article 1→3 score`（每平台一条评分，即使不发也评）
- `article 1→0..3 publish`（实际推送哪几个平台由调度决定）
- `audit_log` 是只追加日志，从不更新或删除

### 7.3 业务模块的 DB

各模块自己的 SQLite/JSON 保留，**但只视为该模块内部缓存**：
- 编排器从不直接读写业务模块 DB
- 业务模块 DB 损坏不影响编排器恢复（重新发请求即可）

---

## 8. 横切关注点

### 8.1 日志与 trace_id

- 编排器创建任意 article 时分配 `trace_id`（UUID v4）
- 编排器调外部模块时附 `X-Trace-Id` header
- 业务模块必须在自己日志里打印 trace_id（要求模块 adapter 层实现）
- 编排器统一日志目录：`/orchestrator/logs/YYYY-MM-DD.log`

### 8.2 配置管理

- 全局共享配置：`shared_config.json`（端口、API key、账号信息）
- 编排器特定配置：`.env`（数据库路径、日志级别）
- **配置变更不需要重启业务模块**（编排器每次调用都从 shared_config 读最新 URL）

### 8.3 守护进程

- `launchd` plist：`~/Library/LaunchAgents/com.bessie.autocontent.{module}.plist`
- 每个模块独立 plist，独立日志，独立重启策略（崩溃自动拉起）
- 编排器 plist 额外 `KeepAlive=true`

### 8.4 资源清理（基本约定）

- 图片 asset 落本地：`/orchestrator/assets/{article_id}/`
- 已发布文章的图片 asset 保留 **7 天**（平台已有留存，本地无需长留）
- rejected 文章 asset 保留 14 天

详细清理策略见 §8.5。

### 8.5 数据清理策略（防本机数据膨胀）

**目标**：本机部署，磁盘和 IO 都有限，必须主动清理临时数据 + 过期资产，保住"重要业务数据"。

#### 8.5.1 触发机制（双触发）

| 触发器 | 频率/条件 | 行为 |
|---|---|---|
| **定时 sweep** | 每 3 小时（cron `0 */3 * * *`） | 跑一次完整清理流程 |
| **阈值守护** | 每 10 分钟巡检一次 | 编排器数据目录总占用 > **2.5 GB** → 立即触发清理 sweep |
| **手动触发** | UI 按钮 `立即清理` | 强制跑一次 sweep |

#### 8.5.2 保留分级

清理时按"重要性梯度"决定保留期。**永久保留**的是业务核心数据，**短期保留**的是辅助/中间产物。

| 数据类别 | 保留期 | 触发清理时的处置 |
|---|---|---|
| `audit_log` 全部记录 | **永久** | 不删（合规 + 故障溯源） |
| `published` 状态的 article + score + publish 记录 | **永久** | DB 记录永久保留 |
| `published` article 的封面图 | **7 天** | 7 天后封面删，保留 DB 记录（平台已留存） |
| `published` article 的正文 inline 图 | **7 天** | 7 天后删（平台已留存） |
| 用户**主动**提交的 topic（无论后续状态） | **永久** | 不删（用户意图珍贵） |
| 自动抓取的 `duplicated` topic | **7 天** | 7 天后物理删除 |
| `rejected` article | **14 天** | 14 天后 article + asset 都删，audit_log 保留 |
| `failed` 已耗尽自动重试 + 无人处理 article | **7 天** | 7 天后转 `rejected` 并按 rejected 流程删 |
| `collected` / `matched` 卡死 ≥ 48h 的 article | **48 小时** | 直接转 `failed`，下一轮清理处理 |
| 已评分但**未发布**的 article（`scored` / `reviewing`）| **永久** | 不删（用户问的"已评分的选题"，明确保住） |
| 编排器日志 | **14 天** | `/orchestrator/logs/` 按天滚动，14 天前删 |
| writing 模块的 intermediate / debug 临时文件 | **24 小时** | 编排器调 writing 的 admin 端点触发清理 |
| 业务模块 SQLite 缓存 | 按需 | 编排器不直接动；提供 `/api/admin/cleanup` 让各模块自己实现 |

#### 8.5.3 阈值清理时的额外行为

当因为 > 2.5 GB 触发紧急清理时，**在常规规则之上追加：**
1. **缩短** `published` 图片保留期 7 → 1 天（已发布过 1 天的，立即删图片，DB 记录保留）
2. **缩短** `rejected` 保留期 14 → 3 天
3. 仍超阈值 → UI 红色告警 + 暂停新任务接收，等用户介入

#### 8.5.4 清理工作流

```
sweep 触发
  ↓
1. 扫描 DB：按分类标记可删 entity_id 集合
  ↓
2. 物理删除 asset 文件（带 try/except，单个失败不阻塞整体）
  ↓
3. DELETE FROM 各表（事务批量）
  ↓
4. VACUUM SQLite（每周日凌晨执行，平时跳过 — VACUUM 锁库）
  ↓
5. 写一条 sweep_log：{started_at, ended_at, freed_bytes, deleted_counts}
  ↓
6. 暴露 GET /api/admin/cleanup-history 供 UI 查看
```

#### 8.5.5 与状态机的关系

- 清理只读 / 删除 article，不改 `status` 字段
- 例外：`collected`/`matched` 卡死 48h → 状态切到 `failed`（写 audit_log，trigger=`cleanup_timeout`）
- 例外：`failed` 满 7 天 → 状态切到 `rejected`（写 audit_log，trigger=`cleanup_abandon`）

#### 8.5.6 安全保护

- 清理任务 **持锁运行**（同一时刻只有 1 个 sweep）
- 任何状态切换为 `publishing` 期间的 article **跳过清理**（避免删到正在发的）
- DB 删除前先 dry-run：若一次预删 > 1000 条 → 中断 + UI 告警（防止规则 bug 大屠杀）

---

## 9. 部署架构

### 9.1 目录布局（确定）

```
/Auto_content_production/
├── docs/                  ← PRD / HLD / LLD / 开发计划
├── shared_config.json     ← 全局共享配置
├── orchestrator/
│   ├── server.py
│   ├── data/pipeline.db
│   ├── assets/{article_id}/
│   ├── logs/YYYY-MM-DD.log
│   └── static/            ← Web UI
├── distilled_characters/  ← 不动现有代码 + adapter 层
├── select_topic/          ← 不动现有代码 + adapter 层
├── writing/               ← 不动现有代码 + adapter 层
├── platform_scorer/       ← 新建
│   ├── server.py
│   └── prompts/
├── Autopublish/           ← 不动现有代码 + adapter 层
└── .archive/              ← 旧 DB 备份
```

### 9.2 端口约定

| 端口 | 用途 |
|---|---|
| 8765 | Autopublish |
| 8766 | select_topic |
| 8767 | distilled_characters |
| 8788 | writing |
| 8789 | platform_scorer |
| 8800 | orchestrator + Web UI |

### 9.3 启动顺序

1. 业务模块（5 个，可并发启动）
2. 编排器（最后，启动时探测各模块 `/health`，全 ok 才进入工作状态）

---

## 10. 关键设计决策记录（ADR）

| # | 决策 | 备选 | 理由 |
|---|---|---|---|
| ADR-1 | 用同步 HTTP + asyncio，不用消息队列 | MQ（RabbitMQ/Redis） | MVP 单机、量小、复杂度收益不匹配 |
| ADR-2 | 编排器为唯一 SoT，模块 DB 是缓存 | 共享 DB / 联邦查询 | 解耦、可独立重启 |
| ADR-3 | 图片立刻下载到本地 | 发布时再下载 | OSS URL 24h 过期已踩坑（v0 教训） |
| ADR-4 | 模块 adapter 层独立提供 `/contract` | 全部接口写死编排器 | 未来加模块只需改 contract，编排器自适应 |
| ADR-5 | 状态机的状态字段是字符串枚举 | int 状态码 | 日志可读、SQL 查询友好 |
| ADR-6 | 不引入 Redis 做调度 | Redis Streams / Celery | 单机 cron + asyncio 足够 |
| ADR-7 | 双触发数据清理（3h 定时 + 2.5G 阈值） | 单时间触发 / 单阈值触发 / 不清理 | 本机磁盘有限，时间防累积、阈值防突发膨胀；分级保留确保业务核心数据不误删 |

---

## 11. 待 LLD 决定的细节

- 每个 schema 的完整字段（类型、可选、默认值）
- DB 完整 CREATE TABLE 语句 + 索引
- 错误码完整枚举（按上面命名规范填充）
- 每个 API 的请求/响应示例 payload
- UI 页面线框（侧栏导航、任务详情页布局、审稿改稿表单）
- launchd plist 模板

---

## 12. 文档版本

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-06-16 | 初版，待评审 |
| v1.1 | 2026-06-16 | 新增 §8.5 数据清理策略（双触发 + 分级保留），新增 ADR-7 |
| v1.2 | 2026-06-16 | published 文章图片保留期 30→7 天（平台已留存）；紧急清理阶梯 7→1 天 |
