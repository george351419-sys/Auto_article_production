# 全自动内容生产流水线 · Auto Content Production

> 从热点捕捉 → 人物匹配 → 多 Agent 对抗写作 → 平台评分 → 自动发布，一套端到端的内容工厂。

---

## 为什么要做这个系统？

内容创作的本质矛盾是**速度与质量的对立**：追热点需要快，出好文需要精。人工运营在热点窗口期（通常 12–24 小时）内完成选题、写作、配图、三平台发布，几乎不可能不出错。

这个系统的设计目标是：**把内容从业者从执行层解放出来，专注于审美与判断**。机器负责快，人负责对。

---

## 架构总览

```
                   ┌──────────────────────────────────────────┐
                   │         Web UI  (浏览器 · 8800)           │
                   │   仪表盘 / 文章管理 / 账号设置 / 模型配置    │
                   └──────────────────┬───────────────────────┘
                                      │ REST API
                   ┌──────────────────▼───────────────────────┐
                   │          编排器 Orchestrator (8800)        │
                   │  ┌─────────────────────────────────────┐  │
                   │  │  状态机引擎  State Machine           │  │
                   │  │  定时调度器  APScheduler             │  │
                   │  │  重试控制器  Retry + Backoff          │  │
                   │  │  桥接客户端  Bridge Clients (httpx)  │  │
                   │  └─────────────────────────────────────┘  │
                   │  SQLite: pipeline.db  |  assets/  logs/   │
                   └──┬──────┬──────┬──────┬──────┬───────────┘
                      │      │      │      │      │
              ┌───────▼┐ ┌───▼──┐ ┌─▼────┐ ┌▼────┐ ┌▼──────────┐
              │蒸馏角色  │ │热点  │ │对抗  │ │评分  │ │自动发布    │
              │distilled│ │选题  │ │写作  │ │引擎  │ │Autopublish│
              │_chars   │ │select│ │writ- │ │plat- │ │           │
              │  8767   │ │_topic│ │ing   │ │form_ │ │  8765     │
              │         │ │ 8766 │ │ 8788 │ │scor  │ │           │
              └─────────┘ └──────┘ └──────┘ │ 8789 │ └───────────┘
                角色DNA库    选题库   14Agent  └──────┘  三平台发布
```

### 六大模块职责

| 模块 | 端口 | 技术栈 | 职责 |
|---|---|---|---|
| `orchestrator` | 8800 | Python · FastAPI · SQLite | **唯一持久化源**；状态机调度；Web UI |
| `distilled_characters` | 8767 | Python · FastAPI | 维护名人/KOL 的「语态 DNA」资产库 |
| `select_topic` | 8766 | Python · FastAPI | 全网热点抓取 + 五维评分 + 人物精准匹配 |
| `writing` | 8788 | TypeScript · Node.js | 14 Agent 对抗写作流水线，产出多平台稿件包 |
| `platform_scorer` | 8789 | Python · FastAPI | 对稿件按平台维度评分，决定发布优先级 |
| `Autopublish` | 8765 | Python · Playwright · FastAPI | 微信公众号 / 今日头条 / 小红书 自动化发布 |

---

## 核心设计思想

### 1. 编排器是唯一的真相来源

所有业务模块（writing、select_topic 等）**不互相通信**，只和编排器通信。编排器的 `pipeline.db` 是 source of truth。

好处在于：任何一个业务模块崩溃、重启，编排器重新轮询即可恢复。业务模块不需要关心自己「在流水线的哪一步」，只需要响应当前请求。

```
❌ 错误模式：writing 写完直接通知 Autopublish 发布
✅ 正确模式：writing 写完 → 编排器更新状态 → 编排器触发 Autopublish
```

### 2. 文章状态机

每篇文章是一个有穷状态机，只能按单向路径推进，不可逆：

```
pending → selecting → selected → writing → reviewing → publishing → published
                                                ↑
                                          (人工审核窗口)
                                          超时自动通过
```

状态机的价值：**任何步骤失败都不会产生「幽灵任务」**。编排器定时 tick（每 10 秒）扫描所有 `in-progress` 状态的文章，根据当前状态决定下一步动作。即使服务宕机，重启后 tick 会自然接管。

### 3. 幂等设计防止重复发布

发布链路最怕的是重复：同一篇文章在同一平台发两次。系统用**双层幂等**防止这个问题：

- **内存层**：进程内 `_published_plans` 集合，单次运行内快速拦截
- **持久层**：`publish_log.json` 全量扫描，跨重启保持去重效果

微信公众号额外强制 `max_retries=0`，因为草稿创建是非幂等操作（每次调用都会在草稿箱产生一篇新文章）。

### 4. 写作：14 Agent 对抗式流水线

写作模块不是「一个 LLM 写完」，而是**三个 Agent 集群串联 + 迭代反馈**：

```
写手集群（3 主笔 + 2 辅笔）
      ↓  产出初稿
编辑集群（结构编辑 + 语态编辑 + 事实核查）
      ↓  综合评分 < 7 → 回流给写手修改
运营集群（SEO、平台适配、配图规划）
      ↓  最终发布包（多平台差异化内容）
```

关键细节：每个 Agent 的输出都包含 `score`（0-10）和 `issues`（具体问题列表），下游 Agent 把上游的问题作为上下文输入，形成**有记忆的对抗**。这比「一遍写完再人工修」的模式产出质量高得多。

### 5. 平台内容差异化，而非简单复制粘贴

三个平台的内容格式和受众完全不同：

| 平台 | 语态 | 关键约束 | 系统处理 |
|---|---|---|---|
| 微信公众号 | 深度·权威·完整 | HTML 正文，封面 2.35:1 | Markdown→HTML，API 存草稿 |
| 今日头条 | 口语·快节奏 | 纯文本，标题 ≤30 字 | 去 Markdown 标记，截断标题 |
| 小红书 | 亲切·碎片化 | 正文 ≤1000 字，图 1-9 张 | emoji 过滤，弯引号→直引号，批量图片上传 |

写作 Agent 为每个平台分别生成内容，`platforms.py` 再做格式清洗，不是把同一篇文章硬塞进三个格式。

### 6. 图片生成闭环

文章配图不需要人工选图。写作 Agent 在正文中嵌入 `![alt](prompt://...)` 占位符，调度器在发布前自动调用阿里云万象（Wanx）API 生成真实图片，并将本地路径回填到稿件，同时加入 `image_paths` 发给 Playwright 上传。

```python
# 写作 Agent 产出
![量子计算示意图](prompt://一颗发光的蓝色量子球体，科技感，深蓝背景)

# 调度器处理后
![量子计算示意图](/path/to/assets/article-id/xiaohongshu/wanx_a3f9b1.jpg)
```

### 7. Cookie 隔离与安全

发布平台的 Cookie 保存在 `Autopublish/.data/accounts.json`（不进 git），模型 API Key 在 `writing/.env` 和根目录 `.env`（均在 `.gitignore`），`shared_config.json` 用 `${ENV_VAR}` 引用变量而非明文存储。所有秘密**本地写盘，永不上传**。

---

## 数据流示意

```
[定时任务 / 人工触发]
        │
        ▼
 select_topic 抓热点
        │  5 维评分 (时效/话题/人物契合/互动预测/内容潜力)
        ▼
 distilled_characters 匹配人物
        │  返回语态 DNA（人物背景 + 代表文章 + 价值观）
        ▼
 writing 对抗写作（14 Agent × 多轮迭代）
        │  产出: { title, formattedArticle, summary, tags, images }
        ▼
 platform_scorer 平台评分
        │  各平台得分 ≥ 阈值（默认 70）才进发布
        ▼
 [人工审核窗口，默认 2h，超时自动通过]
        │
        ▼
 Autopublish 三平台发布
  ├── 微信公众号：WeChat API → 草稿箱（人工群发）
  ├── 今日头条：Playwright 浏览器自动化
  └── 小红书：Playwright + 批量图片上传
        │
        ▼
 状态 → published，写入 publish_log.json
```

---

## 快速上手

### 环境要求

- Python 3.11+
- Node.js 18+
- Playwright（`playwright install chromium`）

### 1. 克隆与依赖

```bash
git clone https://github.com/george351419-sys/Auto_article_production.git
cd Auto_article_production

# Python 环境（编排器 + Autopublish + 其他模块）
python3 -m venv .venv && source .venv/bin/activate
pip install -r orchestrator/requirements.txt

# 写作模块
cd writing && npm install && cd ..
```

### 2. 配置

**第一步：复制配置模板**

`shared_config.json` 不在 git 里（含 API Key 引用）。参考以下模板创建：

```json
{
  "version": "1.0",
  "llm": {
    "qwen": {
      "api_key": "${QWEN_API_KEY}",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "model": "qwen-plus"
    }
  },
  "image_gen": {
    "provider": "wanx",
    "api_key": "your-dashscope-key",
    "model": "wanx2.1-t2i-turbo",
    "size": "1024*1024",
    "max_inline_images": 3
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
    "author": "你的署名",
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

**第二步：设置 API Key（.env）**

```bash
# 根目录 .env（编排器读取）
echo "DEEPSEEK_API_KEY=sk-..." >> .env
echo "QWEN_API_KEY=sk-..."    >> .env

# writing/.env（写作模块读取）
# 可通过 Web UI「账号管理 → 模型配置」直接设置，无需手动编辑
```

**第三步：配置发布平台 Cookie**

启动后，打开 `http://127.0.0.1:8800` → 「账号管理」→ 填入各平台 Cookie：

- **微信公众号**：AppID + AppSecret（公众号后台 → 设置与开发 → 基本配置）
- **今日头条**：登录 `mp.toutiao.com` → DevTools → Application → Cookies → 导出 JSON
- **小红书**：登录 `creator.xiaohongshu.com` → 同上导出 Cookie

### 3. 启动服务

以下命令请**分开在多个终端窗口逐条执行**：

```bash
# 终端 1：编排器（含 Web UI）
cd orchestrator && python3 server_v2.py

# 终端 2：写作模块
cd writing && npm run dev

# 终端 3：Autopublish
cd Autopublish && python3 server.py

# 终端 4：选题模块（可选）
cd select_topic && python3 -m uvicorn server.app:app --port 8766

# 终端 5：人物模块（可选）
cd distilled_characters && python3 main.py --port 8767

# 终端 6：评分模块（可选）
cd platform_scorer && python3 server.py
```

打开浏览器访问 **http://127.0.0.1:8800** 即可进入控制台。

---

## 控制台功能

### 仪表盘

实时显示各模块服务状态（绿点/红点）、文章流水线统计、存储占用。

### 文章管理

- 查看所有文章的当前状态和历史记录
- 手动推进（触发 tick）
- 审核：通过 / 拒绝 / 补写
- 查看写作结果、各平台内容预览

### 账号管理

- **发布平台账号**：Cookie 配置，支持在线校验
- **模型配置**（新）：
  - 文本生成模型：支持 8 家厂商一键切换（通义千问 / DeepSeek / OpenAI / Moonshot / 智谱 / MiniMax / 百川 / SiliconFlow），切换后无需重启生效
  - 图片生成模型：阿里云万象 / 火山引擎 / DALL·E / Stability AI

### 热点选题

手动触发采集，或查看当前候选选题池，支持一键分发到写作流水线。

---

## 关键设计决策记录

### 为什么选 SQLite 而不是 PostgreSQL？

单机部署，不需要多实例并发写入。SQLite 的 WAL 模式足以支撑并发读 + 定时写的场景，且零运维成本。如果未来需要横向扩展，只需替换编排器的 DB 层即可，状态机逻辑不变。

### 为什么写作模块用 TypeScript 而不是 Python？

写作模块的核心是**流式 LLM 调用 + JSON 解析 + 复杂 prompt 拼接**。Node.js 的事件循环天然适合 I/O 密集型任务，TypeScript 的类型系统对多 Agent 间的结构体传递提供了良好的约束。同时团队在 React/Next.js 上已有积累，TypeScript 降低了写作模块前端可视化的门槛。

### 为什么 Playwright 而不是 API？

微信公众号有完整的开放 API，所以优先使用 API。但今日头条和小红书没有提供第三方发布 API（或需企业资质才能申请），只能通过浏览器自动化模拟人工操作。Playwright 的优势是稳定性高、支持多浏览器、截图调试方便。

### 为什么文章状态机不允许回退？

内容生产流水线的每一步都消耗资源（API 调用费用、时间）。允许回退会引入复杂的「回退后重入」逻辑，且调试困难。正确的做法是：**任何步骤失败 → 记录错误 → 保持当前状态 → 重试**，而不是回到上一个状态重新来过。只有人工审核 reject 才会将文章标记为 `failed`，不再自动重试。

### 为什么图片生成在调度器而不是写作模块？

写作模块的职责是「生成文字内容」，它不应该知道图片的存储路径、平台差异、API 限制等细节。写作 Agent 只需要声明「这里需要一张什么样的图」（`prompt://...`），由编排器在发布前统一生成和注入。这样写作模块可以专注于内容质量，而图片策略可以独立迭代。

---

## 目录结构

```
Auto_article_production/
├── orchestrator/          # 编排器（状态机+API+UI）
│   ├── server_v2.py       # FastAPI 主服务
│   ├── scheduler_v2.py    # APScheduler + 状态推进逻辑
│   ├── state_machine.py   # 状态转移函数
│   ├── crud.py            # DB 读写
│   ├── static/index.html  # 单文件 SPA 控制台
│   └── bridge/            # 各模块 HTTP 客户端
├── writing/               # 写作模块（TypeScript + Node.js）
│   ├── server/            # Express + 14 Agent 流水线
│   └── src/               # 前端（文章预览）
├── Autopublish/           # 自动发布模块
│   └── autopublish/
│       ├── platforms.py         # 各平台内容格式化
│       ├── playwright_publisher.py  # 浏览器自动化
│       ├── wechat_api.py        # 微信公众号 API
│       └── scheduler.py        # 发布调度 + 幂等去重
├── select_topic/          # 选题模块
├── distilled_characters/  # 人物 DNA 库
├── platform_scorer/       # 平台评分引擎
├── shared_config.json     # 全局配置（不进 git）
└── .env                   # API Key（不进 git）
```

---

## 常见问题

**Q: 小红书发布后正文显示不全？**

小红书正文硬上限 1000 字，`platforms.py` 会自动截断到 1000 字，`playwright_publisher.py` 进一步截断到 900 字（为 hashtag 预留空间）。如果写作 Agent 产出内容过长，这是预期行为。

**Q: 微信公众号发布后看不到文章？**

系统只将文章存入**草稿箱**（不自动群发）。登录公众号后台 → 草稿箱，手动点击「群发」完成发布。这是有意为之——群发是不可逆操作，应由人工确认。

**Q: 图片生成失败，发布时图片为空？**

检查 `shared_config.json` 中 `image_gen.api_key` 是否正确配置，或通过 Web UI「账号管理 → 图片生成模型」重新填写 API Key。

**Q: 发布提示「已发布过相同文章，跳过重复发布」？**

这是幂等保护机制。如需强制重新发布，需要：1) 重启 Autopublish 服务（清除内存去重集合）；2) 删除 `Autopublish/.data/publish_log.json` 中对应条目。

**Q: 如何切换写作用的 LLM？**

打开 Web UI → 账号管理 → 文本生成模型 → 选择厂商和模型 → 保存。无需重启任何服务，下次写作任务自动使用新模型。

---

## 测试

```bash
# 编排器单元测试
cd orchestrator && python3 -m pytest ../tests/ -v

# 写作模块测试
cd writing && npm test
```

---

## License

MIT

---

*由 Claude Code 辅助开发 · 架构设计与核心实现均经人工审核*
