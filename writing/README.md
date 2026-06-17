# Auto Writing Agent System (自动化文章写作系统)

一个基于多Agent协作流水线的自动化内容生产系统，通过14个专业Agent的分工与迭代，从选题到发布的全流程自动化。

---

## 快速开始

```bash
# 1. 安装依赖
npm install

# 2. 复制环境变量文件
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY（DeepSeek 或 OpenAI 兼容 API）

# 3. 启动（同时启动后端和前端）
npm run dev

# 或分别启动：
npm run server    # 后端 API → http://localhost:8787
npm run client    # 前端 UI  → http://localhost:5175
```

**前端端口可指定**：`npx vite --host 0.0.0.0 --port 5177 --strictPort`

**后端端口可指定**：`PORT=8789 npx tsx server/index.ts`

---

## 架构概览

```
用户创建任务 → 写手Agent集群(3人+2人) → 编辑Agent集群(3人) → 运营Agent集群(4人) → 发布包
                    ↑                      ↓
                    └── 未达7分，回流整改 ──┘
```

### 三个集群，14个Agent

| 集群 | Agent | 职责 | 评分权 |
|------|-------|------|--------|
| **写手** | 张素材 | 双阶段素材采集与核验 | — |
| | 赵立意 | 思想定调、结构、标题 | — |
| | 李文章 | 初稿撰写 | — |
| | 钱人味 | 去AI机器感、真人语感润色 | — |
| | 刘风格 | 抽象声线统一、IP调性校准 | — |
| | **编辑主控** | 汇总编辑侧问题，派单给写手 | — |
| | **写手主控** | 拆解退稿单，派单给写手侧Agent | — |
| **编辑** | 吴查查 | 事实错误核查 | 2分 |
| | 孙风控 | 合规安全审核（高危内容） | 1分 |
| | 周挑刺 | 有用性/可读性/有趣性质检 | 7分 |
| | **编辑主控** | 汇总质检结论，形成统一退稿单 | — |
| **运营** | 陈排版 | 平台版式适配、配图插入 | — |
| | 章上线 | 平台元数据（标题/标签/摘要/封面） | — |
| | **标题大师** | 全平台差异化标题优化 | — |
| | 严反馈 | 终审校验、评分、回流分发 | — |

---

## 流水线流程（Pipeline）

### 写手阶段（Writer Pass）

1. **张素材** 基础摸底采集 → 交付赵立意
2. **赵立意** 定调立意说明书 → 指导素材深耕
3. **张素材** 按立意定向精准补素材
4. **李文章** 撰写初稿
5. **钱人味** 去AI感真人润色
6. **刘风格** 统一IP声线调性
7. 进入编辑阶段

### 编辑阶段（Editor Pass）

- **吴查查**（2分制）：事实错误核验
- **孙风控**（1分制）：合规安全审核
- **周挑刺**（7分制）：有用性/可读性/有趣性

总分 ≥ 7 → 进入运营阶段
总分 < 7 → **编辑主控**汇总退稿单 → **写手主控**派单 → 写手侧局部整改 → 重新编辑评分
最多5轮，超过则标记为 needs_human

### 运营阶段（Operator Pass）

1. 陈排版 → 平台差异化排版配图
2. 章上线 → 生成元数据（标题/标签/关键词/摘要/封面/置顶）
3. **标题大师** → 用专业方法论生成多版本、多角度、带卖点说明的优化标题组（替换章上线的标题）
4. 严反馈终审（10分制，≥8通过）
   - 未通过 → 派单给陈排版/章上线/标题大师整改 → 重新评审
   - 最多3轮运营侧循环，超过则 needs_human

---

## 评分体系

### 编辑侧（总分10分，≥7通过）

| 评委 | 分值 | 评分标准 |
|------|------|----------|
| 吴查查 | 0-2 | 仅检查重大事实错误（年份差2年+、编造来源等），忽略细微偏差 |
| 孙风控 | 0-1 | 仅筛查真正高风险内容（涉政/涉黄/涉暴/确定侵权） |
| 周挑刺 | 0-7 | 有用性(0-1) + 可读性(0-1) + 有趣性(0-1) + 综合提升(0-4) |

### 运营侧（总分10分，≥8通过）

| 维度 | 分值 | 说明 |
|------|------|------|
| 排版呈现 | 0-4 | 段落拆分、金句高亮、层级清晰、阅读节奏 |
| 配图配置 | 0-3 | 配图位置、匹配度、各平台达标、封面方案 |
| 元数据质量 | 0-3 | 标题吸引力、标签精准度、关键词、摘要、置顶文案 |

### 轮次规则

- 写手+编辑每循环一次加1轮（第1轮、第2轮...）
- 进入运营侧后，在写手编辑轮次基础上加小数点（如第2.1轮、第2.2轮）
- 严反馈打回重做运营侧，子轮次递增

---

## Agent 间上下文传递

- **上游上下文**：每个Agent收到的 `previousContext` 包含当前轮次之前所有Agent的输出
- **可用图片资产**：张素材采集的图片链接 → 陈排版排版插入 → 章上线封面选择
- **历史评分参考**：编辑Agent和写手Agent在第二轮起会看到上一轮的评分明细，指导改进方向
- **本轮退稿问题**：编辑侧打回时，TOp 3 阻塞性问题作为 `overrideIssues` 传入

---

## LLM 配置

### 优先级（Fallback机制）

1. **首选**：Qwen3.5-Flash（阿里百炼 DashScope），最多3次重试
2. **回退**：DeepSeek Chat（api.deepseek.com）

### 环境变量

```env
# DeepSeek（回退方案）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your_deepseek_key
LLM_MODEL=deepseek-chat
LLM_MOCK=false           # true=演示模式，不调LLM
LLM_RETRIES=2            # 重试次数
LLM_TIMEOUT_MS=120000    # 超时时间

# Qwen（首选方案）
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=your_qwen_key
QWEN_MODEL=qwen3.5-flash
QWEN_RETRIES=2

# 联网搜索（可选）
TAVILY_API_KEY=
SERPER_API_KEY=
FIRECRAWL_API_KEY=
```

### Mock 模式

`LLM_MOCK=true` 时，所有Agent返回模拟结果，适合开发调试和前端UI验证。

---

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 返回配置、Agent列表、平台标签 |
| GET | `/api/tasks` | 返回所有任务列表（按创建时间倒序） |
| POST | `/api/tasks` | 创建新任务 |
| GET | `/api/tasks/:id` | 获取单个任务详情 |
| POST | `/api/tasks/:id/run` | 运行任务流水线 |
| GET | `/api/tasks/:id/export.md` | 导出发布包Markdown |

---

## 项目结构

```
writing/
├── config/
│   └── agents.ts              # 所有14个Agent的定义（name/group/role/systemPrompt）
├── server/
│   ├── index.ts               # Express 服务器入口，API端点
│   ├── pipeline.ts            # 核心流水线调度（写手→编辑→运营）
│   ├── llm.ts                 # LLM客户端（Qwen优先→DeepSeek回退+Falback）
│   ├── store.ts               # 文件系统存储（JSON）
│   ├── search.ts              # 搜索入口
│   ├── researchSkill.ts       # 研究技能提供器管理
│   ├── imageGeneration.ts     # 平台图片生成与视觉规范
│   └── pipeline.test.ts       # 流水线集成测试
├── shared/
│   ├── types.ts               # 所有TypeScript类型定义
│   ├── scoring.ts             # 评分归一化工具
│   ├── defaults.ts            # 默认用户价值诉求
│   └── simulationInput.ts     # 默认模拟输入（张雪峰声线模型）
├── src/
│   ├── main.tsx               # React前端UI
│   └── styles.css             # 样式
├── skills/
│   ├── title-writing/         # 标题大师技能文件
│   │   └── SKILL.md           # 全平台起标题方法论
│   └── material-research/     # 素材研究技能
├── data/tasks/                # 任务数据存储（JSON）
├── scripts/
│   └── dev.mjs                # 同时启动后端+前端的开发脚本
├── .env                       # 本地环境变量
├── .env.example               # 环境变量模板
├── vite.config.ts             # Vite 配置（含API代理）
├── tsconfig.json              # TypeScript 配置
└── package.json               # 依赖与脚本
```

---

## 新增一个Agent

1. **`shared/types.ts`** — 在 `AgentId` 联合类型中添加新ID
2. **`config/agents.ts`** — 在 `AGENTS` 对象中添加定义（id/name/group/role/systemPrompt），注意 `ISSUE_OWNER_MAP` 和 `GLOBAL_GUARDRAILS`
3. **`server/pipeline.ts`** — 在对应阶段（写手/编辑/运营）的循环中加入 `generateOutput` 调用
4. **`src/main.tsx`** — 在 `agentName()` 函数中添加中文名映射
5. 如果Agent有专业技能，在 `skills/` 目录下创建 `SKILL.md`

---

## 技能文件（Skills）

项目内置两个技能文件，供Agent的systemPrompt引用：

- **`skills/title-writing/SKILL.md`** — 标题大师的技能文档，包含7种核心标题公式、三大平台差异化策略、标题质量检查清单、三层检验等，综合自Nicolas Cole、Dickie Bush、Sahil Bloom等顶级创作者方法论
- **`skills/material-research/`** — 素材研究技能

---

## 数据存储

- 所有任务数据存储在 `data/tasks/{taskId}/` 目录下
- 每个任务一个文件夹，包含 `state.json`、`input.json`、`final-package.json`、`final-package.md`
- 每轮输出存储在 `round-{n}/` 子目录下
- 存储目录可通过 `DATA_DIR` 环境变量自定义

---

## 测试

```bash
# 运行流水线集成测试
npm test
# 或
tsx server/pipeline.test.ts
```

测试基于 Mock LLM 模式，不依赖真实API调用。

---

## 常见问题

### 前端白屏或报错
检查后端是否启动：`lsof -ti:8788`。前后端端口可通过 `PORT` 和 `--port` 参数调整。
前端代理配置在 `vite.config.ts` 中：`"/api" → "http://localhost:{port}"`

### LLM调用失败
- 检查 `.env` 中 `LLM_API_KEY` 是否正确
- 检查网络代理是否影响API请求
- 设置 `LLM_MOCK=true` 进入演示模式

### 运行卡在某个Agent
刷新页面后，任务状态为 `running` 的不一定能恢复。在 `data/tasks/{taskId}/state.json` 中将状态改为 `needs_human` 或 `failed`，然后重新运行。

### 端口冲突
前后端端口可通过环境变量和命令行参数自定义：
- 后端：`PORT=8789 npx tsx server/index.ts`
- 前端：`npx vite --port 5177`
- 记得同步更新 `vite.config.ts` 中的API代理地址
