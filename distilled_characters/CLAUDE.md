# 蒸笼阁 · 人物思维蒸馏工坊

> 根据人名+素材，自动蒸馏人物的五层思维模型：表达DNA → 思维工具 → 决策规则 → 世界观 → 边界演化。

## 启动

```bash
cd /Users/bessie/cursor/distilled_characters
python3 main.py --host 127.0.0.1 --port 8765
```

- 地址: http://127.0.0.1:8765
- API 文档: http://127.0.0.1:8765/docs
- 日志: `data/server.log`

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.14 + FastAPI + Pydantic + uvicorn |
| 前端 | 原生 HTML/CSS/JS（SPA，hash 路由，无构建步骤） |
| 存储 | JSON 文件（`data/` 目录，每记录一个文件） |
| LLM | OpenAI 兼容接口 + Anthropic Messages API |

## 项目结构

```
distilled_characters/
├── main.py                    # 入口：argparse + uvicorn，含日志配置
├── config.py                  # load_config() 读取 data/config.json
├── requirements.txt
├── core/                      # 核心逻辑（零 FastAPI 依赖）
│   ├── models/                # Pydantic 数据模型
│   │   ├── character.py       # Character, Material, 状态枚举
│   │   ├── distillation.py    # FiveLayerOutput, DistillationResult
│   │   └── pipeline.py
│   ├── pipeline/              # 6 步蒸馏引擎
│   │   ├── base.py            # BaseDistillationStep 抽象类
│   │   ├── step1_collection.py   # 素材归档与置信度分级（支持批次）
│   │   ├── step2_surface.py      # 表面层：思维三元组
│   │   ├── step3_midlayer.py     # 中间层：思维工具 + 决策规则
│   │   ├── step4_deep.py         # 深层：世界观
│   │   ├── step5_boundary.py     # 边界与演化
│   │   ├── step6_verification.py # 验证与层组装
│   │   └── orchestrator.py       # 串联 6 步，失败自动降级
│   ├── llm/                   # 可插拔 LLM 后端
│   │   ├── base.py            # AbstractLLMBackend
│   │   ├── openai_compatible.py  # 超时 180s，自动重试 2 次（指数退避）
│   │   ├── anthropic.py       # 同上重试策略
│   │   ├── registry.py        # VENDOR_PRESETS + create_backend()
│   │   └── mock.py
│   ├── search/                # 网络搜索（多渠道路由）
│   └── prompts/               # Prompt 模板
│       ├── templates.py
│       └── builder.py
├── storage/                   # 持久化层
│   ├── base.py                # AbstractStorage CRUD
│   ├── file_storage.py        # JSON 文件实现
│   └── repository.py          # CharacterRepository, DistillationRepository, MaterialRepository
├── server/                    # FastAPI 层
│   ├── app.py                 # app 工厂，含 startup 事件（恢复孤儿任务）
│   ├── dependencies.py        # get_llm_backend() 等 DI
│   └── routes/
│       ├── characters.py      # /api/characters — CRUD，删除时级联清理
│       ├── materials.py       # /api/characters/{id}/materials
│       ├── distillation.py    # /api/distillations — 启动/取消/查看/状态切换
│       ├── config.py          # /api/config + /api/config/llm/vendors
│       ├── pipeline.py        # 独立步骤执行
│       ├── modules.py         # 模块注册表
│       └── search.py
├── static/                    # 前端（原生 JS SPA）
│   ├── index.html             # 入口，script 标签加 ?v=N 防缓存
│   ├── css/
│   │   ├── main.css           # 全局变量、布局、卡片、按钮、表单、toast
│   │   └── components.css     # 组件样式
│   └── js/
│       ├── app.js             # 路由、Modal、Toast、状态徽章映射
│       ├── api.js             # fetch 封装，按领域分组
│       ├── state.js           # 响应式状态
│       └── components/
│           ├── character-list.js    # 人物卡片列表（含失效/恢复/删除）
│           ├── character-detail.js  # 详情页：素材管理 / 蒸馏历史 / 结果查看
│           ├── material-upload.js   # 素材上传（粘贴/文件/URL）
│           ├── distillation-run.js  # WebSocket 实时进度
│           ├── result-viewer.js     # 五层结果渲染
│           ├── search-panel.js      # 网络调研面板
│           └── settings.js          # LLM 后端配置（常见类型/自己填写）
└── data/                      # 运行时数据（自动创建）
    ├── characters/            # 每个角色一个 {id}.json
    ├── materials/             # 每个素材一个 {id}.json
    ├── distillations/         # 每个蒸馏记录一个 {id}.json
    ├── config.json            # LLM 后端、搜索配置
    └── server.log             # 结构化日志
```

## 关键设计

### 蒸馏管道

6 步顺序执行：collection → surface → midlayer → deep → boundary → verification。
每一步失败后自动回退到降级数据（fallback），下游步骤可继续。结果中 `_step_success_rate` 字段记录成功率。

### 人物状态机

```
created → materials_ready → distilling → completed
                          → distilling → failed
                expired（手动设为失效 ←→ 恢复生效）
```

失效角色：卡片半透明灰显，蒸馏历史保留但结果选择器中标记"已失效"。

### 蒸馏记录管理

- `completed` / `failed` → 可"设为失效"（`expired`）→ 可"恢复生效"（`completed`）→ 可"删除"
- `expired` 记录可批量清理（`DELETE /api/characters/:id/distillations/expired`）

### LLM 后端

- 超时默认 180s，`config.json` 中可配 `timeout` 字段
- 5xx/429/超时/连接错误自动重试 2 次（间隔 1s, 2s）
- 厂商预设（`VENDOR_PRESETS`）在前端"常见类型"下拉中展示，选厂商后自动填充模型列表和 API 地址
- DeepSeek 当前为默认后端，base_url 需带 `/v1`

### 启动恢复

服务器启动时 (`app.on_event("startup")`) 自动扫描 `in_progress` 状态的蒸馏记录，重置为 `failed`，对应角色从 `distilling` 重置为 `materials_ready`。防止服务器重启导致记录永久卡死。

## 常见操作

### 添加后端
1. 打开 http://127.0.0.1:8765/#/settings
2. 点 "+ 添加后端"
3. 选择"常见类型 (推荐)" → 选厂商 → 选模型 → 填入 API Key → 确认

### 蒸馏人物
1. 人物列表 → 点卡片 → 添加素材 → 点"开始蒸馏"
2. 查看进度：蒸馏历史 Tab，支持 WebSocket 实时推送
3. 结果查看：结果查看 Tab，按五层展开

### 管理人物
- 人物卡片上：设为失效 / 恢复生效 / 删除（含所有素材和蒸馏记录）
- 蒸馏历史中：每条记录可独立设为失效 / 恢复 / 删除

## 前端缓存

修改 `static/` 下任何 JS/CSS 后，需同步更新 `index.html` 中的 `?v=N` 版本号（当前 N=13），否则浏览器可能使用旧缓存。
