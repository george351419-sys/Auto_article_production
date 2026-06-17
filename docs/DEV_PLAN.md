# 自动内容生产-发布系统 · 开发计划（DEV_PLAN v1）

> 状态：**草案，待评审**
> 关联：[PRD.md](./PRD.md) v1.1 · [HLD.md](./HLD.md) v1.2 · [LLD.md](./LLD.md) v1.0
> 日期：2026-06-16

---

## 1. 文档目的

把 LLD 落到**可执行的开发节奏**：
- 把工作拆成 9 个里程碑（M0 – M8），加 1 个验收 M9
- 每个里程碑结束有"可演示状态"（demo）和验收 checklist
- 测试策略、风险登记、工具链约定

**核心约束**：不要贪快，每个里程碑必须跑通端到端 demo 才能进下一个。

---

## 2. 开发哲学

### 2.1 四条原则

1. **垂直切片（Vertical Slice）优先于水平分层**
   - 每个里程碑产出一个"端到端可见的小功能"，而不是"先把所有 DB 表写完"
   - 早期 milestone 大量使用 mock，让链路尽早跑通

2. **风险驱动排序（Risk-First）**
   - 把最不确定 / 最容易踩坑的环节放在最早的 milestone
   - 顺序：现有模块契约对齐 → 端到端最小路径 → 各分支功能

3. **Demo-Driven**
   - 每个 milestone 末尾必须能向你演示一个可见行为
   - 没有 demo = milestone 没完成

4. **测试 Gate**（硬性约束）
   - 每个 milestone 必须有对应的单元测试集，且**全部通过**才能进入下一个
   - "全部通过"指：`pytest tests/M{n}/` 退出码 0、关键模块覆盖率 ≥ 80%
   - 不允许"先跑下一个，回头补测试"
   - 测试代码与功能代码一并提交，未带测试的 PR 不合入

### 2.2 不做的反模式

- ❌ 同时启动多个 milestone（并发不能加速本机调试）
- ❌ 在 M1 阶段就追求"production-ready" 错误处理（留给 M7）
- ❌ 大重构旧模块代码（违反 PRD §4.1 "原样复用"）
- ❌ 为还没接入的模块写复杂适配（YAGNI）

---

## 3. 里程碑总览

| # | 名称 | 核心目标 | 估算 | 阻塞 |
|---|---|---|---|---|
| M0 | 准备 & 基线 | 旧数据归档、新目录结构、DB schema 初始化 | 1-2 天 | — |
| M1 | 契约对齐验证 | 4 个旧模块加 `/health` + `/contract`，验证 LLD 接口和真实形态一致 | 2-3 天 | M0 |
| M2 | 端到端最小路径 | 编排器骨架 + 状态机 + mock scorer → 手动 POST topic 跑到 published | 3-4 天 | M1 |
| M3 | Web UI 骨架 | Dashboard + 列表页 + 详情页（只读），不带审稿 | 2-3 天 | M2 |
| M4 | 审稿 + 改稿 | 审稿 UI、2h 超时自动发、改稿后重新评分按钮 | 2-3 天 | M3 |
| M5 | 平台评分真实化 + 调度 | platform_scorer 真实 LLM 调用、按评分调度、23:00 保底 | 2 天 | M4 |
| M6 | 选题抓取 + 去重 | select_topic 真实抓取触发、L1+L2 去重、用户提选题 UI | 2-3 天 | M5 |
| M7 | 失败重试 + 干预 | 自动重试退避、UI 重试/跳过/终止、失败展示 | 2 天 | M6 |
| M8 | 清理 + 守护 | 3h sweep、2.5G 阈值守护、VACUUM、6 个 launchd plist 部署 | 2 天 | M7 |
| M9 | 5 天 E2E 验收 | 连续 5 天每平台 ≥1 篇成功，PRD §9 的 8 条 AC 全过 | 5+ 天 | M8 |

**预计总工时：约 3 周开发 + 5 天验收（不含意外踩坑缓冲）**

---

## 4. 详细里程碑

### M0 · 准备 & 基线（1-2 天）

**目标**：把项目从 v0 状态切到 v1 干净基线，所有后续 milestone 可在此基础上开始。

**任务清单**：
1. 把 `pipeline.db` 及各模块自带 SQLite/JSON 数据库 → `.archive/{timestamp}/`
2. 建立目标目录结构（LLD §10）：
   - `docs/` 已建
   - `platform_scorer/`、`deploy/launchd/`、`deploy/scripts/`、各模块下的 `adapters/`
3. 把 `shared_config.json` 升到 LLD §8.1 的最终形态（含 `cleanup` / `scoring` / `platform_scorer_url` 新字段）
4. 在 `orchestrator/migrations/` 写 `0001_init.sql`，包含 LLD §2 的 8 张表
5. 跑一次 init：删除老 `pipeline.db`，新建空 DB，执行迁移

**可演示状态（Demo）**：
- 终端跑 `python3 -m orchestrator.migrate` → 出现新 `pipeline.db`
- `sqlite3 pipeline.db ".tables"` 列出 8 张表
- `.archive/{timestamp}/` 里能看到所有旧 DB 文件

**单元测试集 `tests/M0/`**：
- `test_migrate.py`：跑 0001_init.sql 后，断言 8 张表 + 全部索引存在、settings 初始记录完整
- `test_config_loader.py`：shared_config.json 字段类型、必填检查、默认值
- `test_archive.py`：归档函数移动文件到 `.archive/{ts}/` 且不误删

**验收 checklist**：
- [ ] 旧 DB 已归档
- [ ] 8 张表都建出来，索引齐
- [ ] settings 表已写入初始化记录
- [ ] shared_config.json 通过 JSON schema 校验
- [ ] **`pytest tests/M0/` 全绿，覆盖率 ≥ 80%**

**风险**：低。

---

### M1 · 契约对齐验证（2-3 天）

**目标**：把 LLD §3 里写的接口与 4 个现有模块的真实形态对齐。先暴露偏差，再修 LLD 或修模块 adapter，避免后续每个 milestone 都被契约错配卡住。

**任务清单**：
1. 给 4 个现有模块（distilled_characters / select_topic / writing / Autopublish）各加 `adapters/contract.py`：
   - 实现 `GET /health`
   - 实现 `GET /contract`（返回该模块对外端点清单）
2. 在编排器 `bridge/` 下写 5 个 client（含 platform_scorer 占位 client）
3. 写一个 **契约 smoke 测试脚本** `scripts/contract_check.py`：
   - 拉起 4 个模块
   - 对每个模块发 `/health` 和 `/contract`
   - 对关键 happy path 端点发真实请求（小数据），打印偏差
4. 根据偏差结果修：要么改 LLD §3，要么在 adapter 层做转换
5. 创建 `platform_scorer/server.py` 骨架（mock 模式：固定返回 wechat=80/xhs=70/toutiao=60）

**可演示状态**：
- 6 个模块并发启动（5 业务 + 编排器，编排器只起 server，无业务逻辑）
- 跑 `scripts/contract_check.py` → 输出全绿
- 编排器 `/api/admin/services` 返回 6 个全 Up

**单元测试集 `tests/M1/`**：
- `test_bridge_distilled.py` / `test_bridge_select.py` / `test_bridge_writing.py` / `test_bridge_scorer.py` / `test_bridge_autopub.py`：每个 bridge client 用 FastAPI TestClient 起 mock server，验证 happy path、4xx、5xx、超时、Idempotency-Key、trace_id header 传递
- `test_contract_check.py`：契约校验脚本对 mock 输出的 contract 偏差检测能正确报错
- `test_scorer_mock.py`：platform_scorer mock 模式固定返回三平台分数

**验收 checklist**：
- [ ] 6 个模块都暴露 `/health` 返回 200
- [ ] 6 个模块都暴露 `/contract` 返回 LLD §3.3 形态
- [ ] 关键 happy path 请求成功（writing 真实创建 task、autopublish 真实 dry-run）
- [ ] LLD 里发现的偏差全部修订，升 LLD v1.1
- [ ] **`pytest tests/M1/` 全绿，bridge 模块覆盖率 ≥ 80%**

**风险**：**高**。这是整个项目最易踩坑的环节。要预留缓冲。

---

### M2 · 端到端最小路径（3-4 天）

**目标**：跑通"用户手动 POST 选题 → 编排器状态机推进 → 在 1 个平台 published"的最简链路。

**任务清单**：
1. 编排器：state_machine.py（11 个状态转移函数）+ DB CRUD
2. 编排器 API：`POST /api/topics`（用户提选题）+ `GET /api/articles/{id}`
3. 编排器调度：状态推进的 asyncio 任务（轮询 writing、调 scorer mock、调 autopublish）
4. **跳过的复杂性**（留给后续）：
   - 不接 select_topic 抓取（用户手动 POST）
   - 不带去重（直接进 matched）
   - mock distilled_characters 返回固定人物
   - mock platform_scorer
   - 只发 1 个平台（取评分最高那个）
   - 不做审稿（自动通过）
   - 不带重试
5. 完整 audit_log 写入

**可演示状态**：
- `curl -X POST /api/topics -d '{"title":"DeepSeek融资","brief":"..."}'`
- 用 `curl GET /api/articles/{id}` 看到 status 从 collected → matched → writing → drafted → scored → publishing → published 推进
- 1 个平台真实发布成功，平台 URL 落 DB
- `audit_log` 里能看到所有切换记录

**单元测试集 `tests/M2/`**：
- `test_state_machine.py`：11 个状态、所有合法转移、所有非法转移被拒、原子事务回滚、audit_log 自动写入
- `test_crud_topic.py` / `test_crud_article.py` / `test_crud_publish.py`：每张表 CRUD + 索引命中
- `test_recovery.py`：模拟编排器重启，未完成 article 状态恢复 + 调度续推
- `test_image_download.py`：OSS 图片立即下载落本地（HLD ADR-3），含 403 失败处理
- `test_e2e_minimal.py`：mock 所有外部模块，跑 collected → published 全链路

**验收 checklist**：
- [ ] 整个状态机链路无人工干预跑通
- [ ] 编排器崩溃后重启，能从中断状态恢复推进
- [ ] audit_log 完整（每个状态切换 1 条）
- [ ] 至少 1 个平台真实 published，DB 记录正确
- [ ] **`pytest tests/M2/` 全绿，state_machine 模块覆盖率 ≥ 90%（核心模块要求更高）**

**风险**：中。状态机持久化恢复有踩坑可能。

---

### M3 · Web UI 骨架（2-3 天）

**目标**：用最简的前端把 LLD §6 的 5 个页面搭出来（除审稿编辑外都只读）。

**任务清单**：
1. 选定前端栈：原生 HTML + fetch + 少量 vanilla JS（避免 React 等重栈，本机部署不需要）
2. 5 个页面骨架：
   - `/` Dashboard（聚合数据 + 今日发布进度）
   - `/topics` 选题列表
   - `/articles` 文章列表（含状态筛选）
   - `/articles/{id}` 文章详情（只读时间线 + 评分 + 平台 tab）
   - `/services` 服务健康（轮询 `/api/admin/services`）
3. 列表页 30s 轮询、详情页 5s 轮询
4. 主面板顶部：6 模块状态点 + 存储占用百分比

**可演示状态**：
- 浏览器打开 `http://127.0.0.1:8800/`
- 触发一次 M2 demo，UI 上能实时看到状态推进
- 服务健康页 6 个模块全绿
- Dashboard 显示今日发布数

**单元测试集 `tests/M3/`**：
- `test_api_dashboard.py`：`/api/dashboard` 聚合数据正确（今日发布数、待审数、失败数）
- `test_api_articles_list.py`：列表 + 状态/源筛选 + 分页
- `test_api_article_detail.py`：详情包含 score + publish + asset 子结构
- `test_api_services.py`：服务健康聚合（6 模块 status）
- 注：UI 自动化不测（DEV_PLAN §5.4），只测后端 API 契约

**验收 checklist**：
- [ ] 5 个路由可访问
- [ ] 数据轮询正常，不需要手动刷新
- [ ] 列表筛选生效
- [ ] 服务健康状态准确
- [ ] **`pytest tests/M3/` 全绿，API 层覆盖率 ≥ 80%**

**风险**：低。

---

### M4 · 审稿 + 改稿（2-3 天）

**目标**：完整审稿流。

**任务清单**：
1. UI 文章详情页扩展为审稿表单（LLD §6.3）：
   - 三个平台 tab，每 tab 可编辑标题/正文/封面/标签
   - 富文本编辑器（用 contenteditable + 简单工具栏）
   - localStorage 自动保存草稿
   - 倒计时显示
2. 编排器：`POST /api/articles/{id}/review` 处理 approve/reject + modifications
3. 编排器：`POST /api/articles/{id}/rescore` 手动触发重新评分（生成 generation_n+1 的 score 记录）
4. 编排器调度：reviewing 状态的超时检测（每分钟扫一次 `review_deadline_at`）
5. 超时自动发：调度器触发 → 状态切到 publishing

**可演示状态**：
- M2 的 demo 中加一个 article 停在 `reviewing`
- 浏览器进入审稿页：改标题、改正文、点"重新评分"看分数刷新、点"通过并发布"
- 另一个 article 故意不审稿，2h 后（或人工 hack 改 deadline 为 1 分钟后验证）自动发

**单元测试集 `tests/M4/`**：
- `test_review_approve.py` / `test_review_reject.py` / `test_review_modifications.py`：审稿三种动作的 DB 状态切换与 audit_log
- `test_rescore.py`：generation_n 递增，旧记录保留
- `test_review_timeout.py`：mock 时间快进 2h，自动触发 publishing；驳回不触发
- `test_review_deadline_scheduler.py`：扫描器只挑 `reviewing` 状态 + deadline 已过

**验收 checklist**：
- [ ] 改稿保存后 `final_package` 字段更新
- [ ] 重新评分生成 generation_n=2 记录，保留 generation_n=1
- [ ] 超时自动发触发 publishing
- [ ] 驳回置为 rejected 终态
- [ ] **`pytest tests/M4/` 全绿，覆盖率 ≥ 80%**

**风险**：低-中。前端富文本可能磨人，必要时简化为纯文本。

---

### M5 · 平台评分真实化 + 调度（2 天）

**目标**：去掉 M2 的 scorer mock，接真实 LLM；按评分决定推哪几个平台；实现 23:00 保底。

**任务清单**：
1. `platform_scorer/prompts/system.md` 写真实评分 prompt（参考 LLD §3.7 评分规则）
2. `platform_scorer/server.py`：调 DeepSeek/Qwen 真实评分，解析 JSON 输出
3. 编排器调度逻辑：
   - 评分 ≥ 70 → 进入该平台发布队列
   - 50-69 → 边缘候选（保底备用）
   - < 50 → 跳过
4. 23:00 cron：扫描今日 `publish` 表，若某平台 0 篇 → 取今日 scored 中该平台评分最高的强发
5. UI 审稿页"重新评分"按钮接到真实 scorer

**可演示状态**：
- 跑一次完整流程，3 个平台真实评分有差异
- 触发一篇低分文章，模拟跑到 23:00 → 保底强发触发

**单元测试集 `tests/M5/`**：
- `test_scorer_parse.py`：LLM 多种异常输出（含 markdown 包裹、缺字段、超范围分数）的 fallback 解析
- `test_dispatch_threshold.py`：阈值边界（score=69 不发、70 发）
- `test_dispatch_boost.py`：23:00 保底规则 — 某平台 0 篇 → 选当日该平台评分最高的强发；多个平台都需保底时的优先级
- `test_dispatch_boost_no_candidate.py`：当日全部稿件该平台都 < 50 → 不强发，记录告警

**验收 checklist**：
- [ ] 真实 LLM 评分返回 0-100 + reason
- [ ] 按阈值正确决定发布平台集合
- [ ] 23:00 保底逻辑可用（用临时改 cron 验证）
- [ ] 评分历史保留多代
- [ ] **`pytest tests/M5/` 全绿，scoring/dispatch 模块覆盖率 ≥ 85%**

**风险**：中。LLM 输出 JSON 解析鲁棒性。

---

### M6 · 选题抓取 + 去重（2-3 天）

**目标**：接通真实选题来源 + 落地去重。

**任务清单**：
1. 编排器调度：每日 08:00 cron 触发 `select_topic POST /api/collect/trigger`
2. 抓取完成后拉取 `GET /api/topics?status=ready` → 入编排器 topic 表
3. 入库前 L1 去重：标题归一化 + 7 天内匹配
4. 命中 L1 → 直接置 `duplicated`；未命中 → L2 实体提取（一次 LLM 调用）
5. L2：实体 Jaccard ≥ 0.7 且 keyword 重叠 ≥ 1 → `duplicated`
6. UI 提选题表单（`POST /api/topics`）
7. UI 显示"重复"标签 + 重复原因 + "仍要写"覆盖按钮

**可演示状态**：
- 08:00 cron（人工触发）抓出 N 个 topic
- 提交两次相同标题 → 第二次显示 duplicated
- 提交两次相似但不同字 → L2 命中，UI 显示"与 X 重复（实体匹配 80%）"

**单元测试集 `tests/M6/`**：
- `test_l1_normalize.py`：标题归一化（去标点、小写、停用词、Unicode 半角/全角统一）的 edge case
- `test_l1_dedup.py`：7 天窗口边界（第 6 天命中、第 8 天不命中）
- `test_l2_jaccard.py`：实体集合 Jaccard 计算 + 阈值 0.7 边界（0.69 不命中、0.70 命中）
- `test_l2_keywords.py`：topic_keywords 重叠 ≥ 1 判定
- `test_dedup_user_override.py`：用户"仍要写"覆盖去重判定
- `test_user_topic_submission.py`：用户提交 topic 时 `user_submitted=1` 落库

**验收 checklist**：
- [ ] cron 触发抓取
- [ ] L1 去重正确
- [ ] L2 实体提取存 DB + 比对正确
- [ ] UI 用户提选题入口可用
- [ ] **`pytest tests/M6/` 全绿，dedup 模块覆盖率 ≥ 90%（核心算法要求更高）**

**风险**：中。实体提取 prompt 调优。

---

### M7 · 失败重试 + 干预（2 天）

**目标**：补齐之前 milestone 跳过的错误处理和人工干预。

**任务清单**：
1. 状态机：任一环节失败 → `failed` + 写 `retry_count` + `next_retry_at`
2. 调度器：扫描 `next_retry_at ≤ now` 的 article 触发重试
3. 退避：30s → 2min → 10min，超 3 次留 failed
4. UI：失败展示（错误码 + 错误信息 + retry_count）
5. UI 按钮：`/retry`（重置 retry_count）、`/skip-platform`、`/terminate`
6. Dashboard 显示"最近失败"红色块

**可演示状态**：
- 人工 hack 让某次 publish 失败 → 看到 30s 后自动重试
- 重试满 3 次后 → 留在 failed
- 点"重试" → 重新开始
- 点"跳过此平台" → 仅该平台 skipped，其他继续

**单元测试集 `tests/M7/`**：
- `test_retry_backoff.py`：retry_count 0/1/2 对应 30s/2min/10min 的 next_retry_at 准确性
- `test_retry_limit.py`：第 4 次（retry_count=3）不再触发，留 failed
- `test_retry_total_window.py`：累计超过 15 min 不再重试
- `test_skip_platform.py`：仅该平台置 skipped，其他平台继续
- `test_terminate.py`：强制置 rejected + 不再重试
- `test_user_retry.py`：用户点重试，retry_count 重置为 0

**验收 checklist**：
- [ ] 退避间隔准确
- [ ] 重试上限触发后停止
- [ ] 3 个人工干预按钮都生效
- [ ] 失败信息清晰可读
- [ ] **`pytest tests/M7/` 全绿，retry 模块覆盖率 ≥ 85%**

**风险**：低。

---

### M8 · 清理 + 守护（2 天）

**目标**：HLD §8.5 数据清理策略落地 + launchd 守护进程化。

**任务清单**：
1. `orchestrator/cleanup.py`：实现 §8.5.2 分级保留规则
2. 调度器：3h cron + 10min 阈值守护
3. 阈值触发时执行 §8.5.3 加码规则
4. `cleanup_log` 表写入
5. UI `/cleanup` 历史页 + Dashboard 顶部存储占用条
6. VACUUM 周日 03:00 cron（独立 cron，不与 sweep 同跑）
7. 生成 6 个 launchd plist + `deploy/scripts/install.sh`
8. `launchctl load` 部署，测试崩溃自动拉起

**可演示状态**：
- 人工塞 1.5G 测试数据 → 手动触发清理 → 看到分级删除
- 人工塞 2.6G → 阈值守护触发紧急清理
- `launchctl list | grep autocontent` 看到 6 个进程
- `kill -9 {pid}` 任一进程 → 10s 后自动拉起

**单元测试集 `tests/M8/`**：
- `test_cleanup_retention.py`：每类数据的保留期边界（已发布图第 7 天不删、第 8 天删）
- `test_cleanup_scored_untouched.py`：**关键** — 任何处于 scored/reviewing 的 article 永远不被清理
- `test_cleanup_user_topic_untouched.py`：user_submitted=1 的 topic 永远不删
- `test_cleanup_audit_log_untouched.py`：audit_log 永远不删
- `test_threshold_guard.py`：mock 磁盘 1.5G → 不触发；2.6G → 触发紧急规则（保留期 7→1 / 14→3）
- `test_cleanup_dry_run.py`：单次预删 > 1000 条 → 中断 + 告警
- `test_cleanup_lock.py`：并发触发只有 1 个 sweep 运行
- `test_cleanup_skip_publishing.py`：处于 publishing 状态的 article 跳过清理
- `test_vacuum_schedule.py`：VACUUM 仅周日凌晨 3 点，不与 sweep 同跑
- `test_launchd_plist.py`：6 个 plist 模板渲染输出符合 macOS plist DTD

**验收 checklist**：
- [ ] 分级保留规则全部正确（已评分稿件不被删）
- [ ] 阈值守护准确触发紧急规则
- [ ] 6 个 plist 全部 KeepAlive 生效
- [ ] cleanup_log 记录完整
- [ ] VACUUM 不与 sweep 冲突
- [ ] **`pytest tests/M8/` 全绿，cleanup 模块覆盖率 ≥ 90%（避免误删核心数据）**

**风险**：中。launchd 配置 macOS 版本敏感。

---

### M9 · 5 天 E2E 验收（5+ 天）

**目标**：PRD §9 的 8 条 AC 全部通过。

**操作**：
1. 配 cron 让系统全自动跑 5 天
2. 每天人工检查：
   - 每个平台 ≥ 1 篇成功
   - 编排器进程没崩
   - 失败任务都有清晰错误
3. 中途至少做 1 次人工介入：手动提选题 + 审稿改稿
4. 第 5 天结束做 AC checklist 逐项打勾

**验收 checklist**（即 PRD §9 的 8 条 AC）：
- [ ] AC1: 连续 5 天每平台 ≥ 1 篇
- [ ] AC2: 编排器 uptime 全程不重启
- [ ] AC3: 失败任务都有明确 error code + message
- [ ] AC4: 任意时刻 UI 能看到任务在哪一步
- [ ] AC5: 三种人工干预按钮均测试通过
- [ ] AC6: 用户提选题 10 分钟内进入 writing
- [ ] AC7: 每篇稿都有 3 平台评分 + 理由
- [ ] AC8: 5 天发布分布满足保底规则

---

## 5. 测试策略

### 5.1 测试 Gate（硬性约束）

**每个 milestone 进入下一个之前，必须满足：**

1. `pytest tests/M{n}/` 退出码 0（所有 case 通过）
2. 关键模块覆盖率达标（见各 milestone 验收 checklist 的具体百分比）
3. 测试代码与功能代码 **同一 commit / 同一 PR** 提交
4. 不允许 `xfail` / `skip` 长期挂着 — 必须修或删除

**违反任一条 = milestone 未完成 = 不进下一个。**

### 5.2 覆盖率工具与阈值

工具：`pytest-cov`

```bash
# 单个 milestone 测试 + 覆盖率
pytest tests/M{n}/ --cov=orchestrator --cov-report=term-missing --cov-fail-under={threshold}
```

各模块默认覆盖率门槛：
| 模块类型 | 阈值 | 理由 |
|---|---|---|
| 核心算法（state_machine / dedup / cleanup） | **≥ 90%** | 误差代价高 |
| 业务调度（scorer dispatch / retry） | ≥ 85% | 主流程关键 |
| Bridge clients | ≥ 80% | HTTP 边界值 |
| API 层 | ≥ 80% | 外部接口 |
| 工具/辅助代码 | ≥ 70% | 非关键 |

### 5.3 单元测试组织约定

```
tests/
├── M0/
│   ├── test_migrate.py
│   ├── test_config_loader.py
│   └── ...
├── M1/
│   └── ...
├── ...
├── conftest.py              ← 全局 fixture（mock LLM、mock DB、mock time）
└── helpers/
    ├── mock_modules.py      ← FastAPI mock servers for 5 业务模块
    └── factories.py         ← 测试数据工厂（topic / article / score）
```

**约定**：
- 测试不依赖真实网络（mock 所有 HTTP）
- 测试不依赖真实 LLM（mock 响应）
- 测试不依赖真实时间（用 freezegun）
- 测试不依赖真实 SQLite 文件（用 in-memory `:memory:` + temp dir）
- 单个 test 函数 < 30 行，超过就拆

### 5.4 集成测试

每个 milestone 完成后跑一次跨 M 的集成 smoke：

```bash
pytest tests/integration/ -k "M0_to_M{current}"
```

集成测试用：真实 6 个进程（业务模块 mock 模式启动），编排器调度真实执行，但 LLM 仍 mock。

### 5.5 E2E 测试（手动）

每个 milestone 末尾的"可演示状态"就是 E2E 测试脚本。M9 验收期间每天执行一遍。

### 5.6 不做的测试

- ❌ UI 自动化测试（Selenium / Playwright）— 投入产出比低，UI 用人工 demo 验证
- ❌ 性能压测 — MVP 不优化性能
- ❌ 安全渗透测试 — 本机部署 127.0.0.1 不暴露
- ❌ Mutation testing — 过度

---

## 6. 风险登记册

| 风险 | 概率 | 影响 | 触发 milestone | 应对 |
|---|---|---|---|---|
| 现有模块真实 API 与 LLD 偏差大 | 高 | 高 | M1 | M1 缓冲 1 天，必要时回滚改 LLD |
| Playwright Cookie 失效导致 5 天验收中断 | 高 | 高 | M9 | UI 加 cookie 状态检测（M3 补） |
| LLM JSON 输出解析失败 | 中 | 中 | M5 / M6 | 加 fallback 解析 + 自动重试一次 |
| OSS 图片 24h 过期 | 高 | 高 | M2 | M2 必须实现"立即下载到本地" |
| launchd 在 macOS 25.5 行为变化 | 中 | 中 | M8 | M8 缓冲 0.5 天 |
| SQLite WAL 在多进程并发下死锁 | 中 | 中 | M2 | busy_timeout 5s + 限制并发数 |
| 三平台账号风控封禁 | 中 | 高 | M9 | 控制发布频率，UI 显示间隔 |

---

## 7. 工具链 & 工作约定

### 7.1 技术栈（确认）

- 后端：Python 3.11+, FastAPI, asyncio, aiosqlite, httpx
- 前端：原生 HTML + vanilla JS + CSS（不上框架）
- DB：SQLite 3 + WAL
- 部署：macOS launchd
- LLM：DeepSeek（主）+ Qwen（备）
- 测试：pytest + httpx mock

### 7.2 代码规约

- Python：遵循 PEP8，用 `ruff` 检查
- 类型：所有 public 函数加 type hints
- 日志：用 `structlog` 输出 JSON Lines（LLD §9）
- 提交：每个 milestone 1 个分支，完成后 merge 到 `main`

### 7.3 文档维护

- LLD 在 M1 / M5 / M6 / M8 各 milestone 末尾可能升版本（实际偏差导致）
- 每次 LLD 升版必须在 §12 文档版本里加 changelog
- 实现完成后，docs/ 与代码同步是硬性约束

---

## 8. 进度跟踪

- 编排器内建里程碑表 `milestone`（M0-M9），UI Settings 页展示进度
- 每个 milestone 完成后填 demo 截图到 `docs/demo/M{n}.md`
- 5 天验收期间，每日填一份 `docs/acceptance/day{n}.md`

---

## 9. 文档版本

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-06-16 | 初版，待评审 |
| v1.1 | 2026-06-16 | 加入硬性测试 Gate：每 milestone 必有 `tests/M{n}/`、覆盖率门槛分级、§5 重写测试策略章节 |
