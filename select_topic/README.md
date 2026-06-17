# 名人热点智能匹配选题系统

## 项目概述

基于名人人物模型资产与全网实时热点，搭建的一套自动化、可量化、人机协同的智能选题系统。实现热点自动抓取 → 五维打分筛选 → 名人精准匹配 → 分值化审核流转的全链路。

**核心能力**：以快打慢、抢占热点窗口期、量化匹配零主观判断。

**技术栈**：Python 3.14 + FastAPI + SQLite + 纯 HTML/JS/CSS，136 项测试全部通过。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器 (SPA)                          │
│  index.html  /  app.js  /  components.js  /  api.js     │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP (REST API)
┌────────────────────▼────────────────────────────────────┐
│                 FastAPI 服务层                           │
│  server/routes/ — 8 个路由模块, 17 个端点                │
│  server/scheduler.py — 后台定时采集 (asyncio)            │
│  server/app.py — 生命周期管理                             │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                 核心引擎层                                │
│  scoring_engine.py  — 五维打分 (双定位)                  │
│  matching_engine.py — 六维名人匹配 (LLM + 规则)          │
│  celebrity_loader.py — 9 位名人 5 层 DNA 加载            │
│  core/collector/    — 采集模块 (4 文件)                  │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              SQLite 数据库 (8 张表)                       │
│  topics / score_results / match_results / review_logs   │
│  config / collection_logs / collection_state             │
└─────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
select_topic/
├── main.py                         # 启动入口 (uvicorn, port 8766)
├── config.py                       # 全局配置 (LLM/采集器/DB路径/默认定位)
├── init_db.py                      # 数据库建表 + 种子数据 + 自动迁移
├── requirements.txt                # Python 依赖
├── test_suite.py                   # 136 项测试（单元 + 集成, ~1020行）
│
├── core/                           # 核心引擎（不依赖 HTTP 框架）
│   ├── models.py                   # 18 个 Pydantic 数据模型
│   ├── scoring_engine.py           # 五维打分引擎（双定位 + 双权重体系）
│   ├── matching_engine.py          # 六维名人匹配（LLM + 规则双模式）
│   ├── celebrity_loader.py         # 从 distilled_characters 加载 9 位名人 5 层 DNA
│   └── collector/                  # 采集模块
│       ├── __init__.py             # 公共 API (scrape_all, distill_batch, deduplicate)
│       ├── base.py                 # HotItem / DistilledTopic 数据结构
│       ├── direct_scraper.py       # 轻量 HTTP 抓取各平台热榜 + TrendRadar MCP 客户端
│       ├── topic_distiller.py      # LLM 蒸馏（分块10条）+ JSON 截断修复 + 规则回退
│       └── dedup.py                # 三阶段去重: URL精确 → 批内相似 → 跨DB相似
│
├── server/                         # FastAPI 后端
│   ├── app.py                      # 应用工厂 + CORS + 静态文件 + 调度器生命周期
│   ├── database.py                 # aiosqlite 异步连接 (row_factory)
│   ├── scheduler.py                # 后台定时采集调度器 (asyncio, 默认3600s)
│   └── routes/
│       ├── topics.py               # 选题 CRUD + 筛选（status/grade/search/source_type）
│       ├── scoring.py              # 打分接口（支持 positioning 参数）
│       ├── matching.py             # 匹配接口
│       ├── review.py               # 审核流转接口
│       ├── pipeline.py             # 一键流程（创建→打分→筛选→匹配, 含 80 分门槛）
│       ├── collect.py              # 采集 API + URL 导入（含 80 分门槛）
│       ├── celebrities.py          # 名人数据查询
│       └── config.py               # 权重/阈值配置读写
│
├── static/                         # 单页前端 (SPA)
│   ├── index.html                  # 主页面 (~90行)
│   ├── css/style.css               # 样式 (~555行)
│   └── js/
│       ├── api.js                  # API 调用层 (~90行)
│       ├── app.js                  # 主控制器 + 状态管理 (~320行)
│       └── components.js           # UI 渲染组件 (~300行)
│
└── data/                           # 运行时数据（gitignore）
    ├── config.json                 # 运行时配置
    ├── select_topic.db             # SQLite 数据库
    └── server.log                  # 运行日志
```

---

## 数据库设计 (7 张表)

| 表名 | 说明 | 核心字段 |
|------|------|----------|
| `topics` | 选题主表 | id, title, source_url, source_type(auto/manual), source_platform, raw_content, heat_level, status, source_material(JSON), batch_id |
| `score_results` | 打分结果 | topic_id, 5维分数, total_score, grade(S/A/B/C), bonus_details(JSON), weight_mode, platform, **positioning** |
| `match_results` | 匹配结果 | topic_id, celebrity_id/name, match_score, match_reason, rank |
| `review_logs` | 审核记录 | topic_id, action, previous_status → new_status, note |
| `config` | 配置 | key-value (weights, rating_thresholds) |
| `collection_logs` | 采集日志 | batch_id, source_name, items_fetched/new, status, error_message |
| `collection_state` | 采集状态持久化 | key-value |

---

## API 端点 (17 个)

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/topics` | 创建选题 |
| `GET` | `/api/topics` | 选题列表（支持 status/grade/min_score/search/source_type/分页） |
| `GET` | `/api/topics/{id}` | 选题详情（含打分+匹配+审核记录+原文材料） |
| `DELETE` | `/api/topics/{id}` | 删除选题 |
| `POST` | `/api/topics/{id}/score` | 执行五维打分（含 positioning 参数） |
| `POST` | `/api/topics/{id}/match` | 执行名人匹配 |
| `POST` | `/api/topics/{id}/review` | 审核操作 (confirm/discard/backup/adjust) |
| `POST` | `/api/pipeline/run` | 一键流程（创建→打分→80分筛选→匹配） |
| `POST` | `/api/collect/trigger` | 手动触发全平台采集 |
| `GET` | `/api/collect/status` | 采集调度器状态 |
| `POST` | `/api/collect/import-url` | URL 导入（爬取网页→LLM蒸馏→80分筛选） |
| `GET` | `/api/collect/logs` | 采集运行日志 |
| `GET` | `/api/celebrities` | 名人列表 |
| `GET` | `/api/celebrities/{id}` | 名人详情（含5层DNA） |
| `GET` | `/api/config/weights` | 获取权重配置 |
| `PUT` | `/api/config/weights` | 更新权重配置 |
| `GET` | `/api/config/rating-thresholds` | 获取评级阈值 |

---

## 核心引擎

### 全局「定位」变量

系统支持两种内容定位，有独立的评分体系：

| 定位 | 键值 | 领域焦点 | 评分重点 |
|------|------|----------|----------|
| 商业科技 | `business_tech` | AI、互联网、新能源、商业模式 | 关键词专业度、方法论深度 |
| 娱乐鸡汤 | `entertainment` | 综艺、情感、成长、生活方式 | 情感共鸣、传播性、原创度 |

**UI 层面**：头部工具栏有「定位」下拉框，左右切换后所有打分/匹配/导入均使用对应标准。

### 五维打分引擎 (scoring_engine.py)

**两套完整的评分体系**，各含 5 个维度 × 6 组权重 × 独立加减分规则。

#### 商业科技

| 维度 | 评分方式 | 权重体系 |
|------|----------|----------|
| 领域相关性 | 核心关键词（AI/融资/芯片等）+ 负关键词反过滤（吃瓜/八卦等） | 2模式 × 3平台 = 6套 |
| 热点时效性 | 正则匹配时间词（刚刚→95, 今天→92, 昨天→85...） | |
| 内容价值延展性 | 深度指标（方法论/复盘/数据）vs 浅度指标（快讯/流水账） | |
| 合规风险度 | 反向指标，高=低风险（敏感词检测） | |
| 赛道竞争度 | 反向指标，高=蓝海（独家/非共识 vs 热搜/刷屏） | |

加减分：AI话题 +5、大厂财报 +5、纯新闻复述 -10、敏感金融 -10。新号有额外规则。

#### 娱乐鸡汤

| 维度 | 评分方式 | 权重偏向 |
|------|----------|----------|
| 领域相关性 | 核心关键词（综艺/影视/情感/育儿/成长等），负关键词（政治/暴力） | 新号时效性权重最高 0.35-0.38 |
| 热点时效性 | 新增热播/首播/上线/开播等娱乐热词 | 老号价值权重最高 0.25-0.33 |
| 内容价值延展性 | 情感共鸣/观点独特/实用技巧 vs 纯资讯/搬运 | 小红书价值权重 0.33 |
| 合规风险度 | 隐私泄露/偷拍/造谣/抄袭/虚假人设 vs 正能量/原创 | |
| 赛道竞争度 | 独家角度/冷门佳片 vs 大众热议/千篇一律 | |

加减分：独家爆料 +5、情感共鸣 +5、名人相关 +5、纯搬运 -10、低俗擦边 -10、过期旧闻 -8。

**评级**：S≥90 / A≥80 / B≥70 / C<70

### 六维名人匹配引擎 (matching_engine.py)

LLM 从 6 个维度评估：话题重合度、价值观匹配度、思维适配度、风格契合度、边界安全性、演化一致性。并发调用（信号量限制 4），失败自动回退到规则匹配。Top 3 结果输出。

### 采集模块 (core/collector/)

**数据流**（全内存，不写文件）：
```
热榜 API → [HotItem] → LLM 蒸馏 → [DistilledTopic]
→ 三阶段去重 → 五维评分 → 低于 80 分丢弃 → 入库 + 规则匹配
→ 原始 HTML/JSON 随函数返回被 GC，不存磁盘
```

**当前状态**：
- 头条热榜 ✅ 正常（30条/次）
- 微博热搜 ❌ 403（需要 cookie/反爬）
- 小红书热榜 ❌ 404（API 路径已变更）
- 新榜 ✅ 已接入自动化来源（优先公共 JSON，回退公开页面解析；遇到登录/反爬时跳过）
- 今日热榜 ✅ 已接入自动化来源（公开页面解析，默认覆盖首页/微博/百度/知乎榜）

### 三阶段去重 (core/collector/dedup.py)

1. **URL 精确匹配**：DB 中已存在的 source_url 直接跳过
2. **批内标题相似度**：字符 3-gram Jaccard ≥ 0.70 的去重（解决 LLM 蒸馏产生多版本问题）
3. **跨 DB 标题相似度**：与最近 72h 内已有选题对比，相似 ≥ 0.70 的跳过

### 80 分门槛（全链路）

低于 80 分的选题在任何入口都会被拒绝：

| 入口 | 文件 | 行为 |
|------|------|------|
| 自动采集 | `server/scheduler.py:142` | 不入库，跳过 |
| 手动导入 | `server/routes/pipeline.py:60-71` | 入库但标为 `discarded`，不匹配，返回 `{status: "filtered"}` |
| 链接导入 | `server/routes/collect.py:118-129` | 同上 |
| 单独打分 | `server/routes/scoring.py` | 正常打分（不拦截，由上游判断） |

无高分选题时，前端弹窗提示"本轮采集未发现 80 分以上的选题，暂无可入库选题。"

### 状态流转

`pending → scored → matched → {confirmed | discarded | backup | adjust}`

---

## 已接入的名人模型库

从 `../distilled_characters/data/` 加载 9 位名人 5 层 DNA：

王煜全、九边、老喻、吴军、梁宁、万维钢、刘润、施展、何刚（8/9 有完整 DNA）

---

## 命令速查

```bash
cd /Users/bessie/cursor/Auto_content_production/select_topic

# 启动服务（端口 8766）
python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8766

# 运行全部测试（136项）
python3 -m pytest test_suite.py -v

# 仅单元测试（秒级，不需要服务）
python3 -m pytest test_suite.py -v -k "TestDimension or TestBonus or TestScore or TestModels or TestRuleBased or TestEntertainment"

# 仅娱乐鸡汤测试
python3 -m pytest test_suite.py -v -k "Entertainment"

# 仅 API 集成测试
python3 -m pytest test_suite.py -v -k "TestAPI or TestTopicCRUD or TestScoring or TestMatching or TestPipeline or TestReview or TestEdge"

# 触发一次手动采集（商业科技定位）
curl -X POST http://127.0.0.1:8766/api/collect/trigger

# 导入 URL（娱乐鸡汤定位）
curl -X POST http://127.0.0.1:8766/api/collect/import-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "positioning": "entertainment"}'

# Pipeline 一键导入（含 80 分门槛过滤）
curl -X POST http://127.0.0.1:8766/api/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{"title": "选题标题", "raw_content": "内容", "positioning": "business_tech"}'

# 查看采集日志
curl http://127.0.0.1:8766/api/collect/logs?limit=10

# 重建数据库
rm -f data/select_topic.db && python3 init_db.py
```

---

## 前端使用指南

访问 `http://127.0.0.1:8766`

### 头部工具栏
- **定位**：切换「商业科技」/「娱乐鸡汤」，所有后续评分使用对应标准
- **权重方案**：新号冷启动 / 老号深度运营
- **目标平台**：公众号 / 今日头条 / 小红书
- **采集热点**：手动触发全平台热点采集（含加载动画 + 去重 + 入库）
- **手动导入**：弹窗双标签页导入
- **采集状态**：显示上次采集时间

### 导入弹窗
- **手动输入**：填写标题/链接/内容，选择定位/平台/权重方案，一键处理
- **链接导入**：粘贴任意网页 URL，系统自动抓取页面内容并通过 LLM 提炼为选题

### 左侧列表
- 按状态/评级/来源类型筛选选题
- 来源标记：自动（绿色）/ 手动（灰色）
- 点击查看详情

### 右侧详情
- 话题信息（标题、来源类型、平台、热度、原文链接）
- 原文材料列表（点击跳转到来源网页）
- 五维评分柱状图（含定位/权重方案/平台信息）
- TOP3 名人匹配卡片
- 审核记录
- 操作按钮：打分 / 匹配 / 打分+匹配 / 确认 / 暂存 / 淘汰 / 重置

---

## 配置参考

```python
# config.py — 完整配置结构
{
    "server_host": "127.0.0.1",
    "server_port": 8766,
    "default_positioning": "business_tech",   # 默认定位
    "llm_backend": {
        "name": "deepseek",
        "type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "collector": {
        "enabled": True,
        "interval_seconds": 3600,              # 自动采集间隔
        "auto_score_threshold": 80,            # 入库最低分（全链路生效）
        "trendradar": {
            "enabled": True,                   # 需要先 clone TrendRadar
            "working_dir": "../TrendRadar",
        },
        "direct_scrape": {"enabled": True},    # TrendRadar 不可用时回退
        "platforms": ["toutiao", "weibo", "xiaohongshu", "newrank", "tophub"],
        "liquid": {"max_items_per_batch": 20, "model": "deepseek-chat"},
        "dedup": {"title_similarity_threshold": 0.70, "lookback_hours": 72},
    },
}
```

---

## 已知问题

1. **微博热榜爬虫 403**：需要添加有效的 Cookie/登录态
2. **小红书热榜爬虫 404**：API 端点 `/api/sns/web/v1/homefeed` 已失效，需要研究新的接口
3. **TrendRadar**：虽然配置已启用，但需要先在 `../TrendRadar` 路径下 clone 项目才能工作

---

## LLM 配置

| 配置项 | 值 | 用途 |
|--------|-----|------|
| 模型 | deepseek-chat | |
| API Base URL | https://api.deepseek.com/v1 | |
| 调用场景 | 名人匹配、话题蒸馏、URL 内容提取 | |
| 蒸馏分块 | 每批 10 条，max_tokens=4000 | 防止 JSON 截断 |
| 截断修复 | 自动补全未闭合的括号/引号 | |
| 回退策略 | LLM 失败时自动回退到规则蒸馏 | 关键词过滤娱乐/时政 |

---

## 版本历史

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-06 | MVP：手动导入 → 五维打分 → 名人匹配 → 审核流转 |
| v2.0 | 2026-06 | Phase 2：双源采集、原文材料追踪、后台定时调度、空间优化、三阶段去重、80分门槛 |
| v2.1 | 2026-06 | 新增「定位」变量：商业科技/娱乐鸡汤双评分体系、全链路 80 分门槛覆盖 |
