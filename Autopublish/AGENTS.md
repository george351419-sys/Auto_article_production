# AutoPublish 项目说明书（Agent 接手指南）

> 最后更新：2026-06-17
> 适用于：Claude Code 等 AI Agent 接手维护

> **平台命名约定（重要）**：orchestrator / platform_scorer 内部一律用
> `wechat / xiaohongshu / toutiao`；Autopublish 的 `Platform` 枚举用
> `wechat_official / xiaohongshu / toutiao`。两者在
> `orchestrator/scheduler_v2.py:_SCORER_TO_AUTOPUBLISH` 做一次映射，调
> Autopublish 时已自动转换。手写 payload 时记得传 `wechat_official`。

> **端口**：当前 distilled_characters=8767，autopublish=8765（早期文档里
> 提到的 "8765 冲突 / 改 8769" 已废弃，无需 PORT 覆盖）。

---

## 一、系统概述

多平台自动发布系统，支持将文章一键发布到：
- **微信公众号**（API 模式，WechatApiPublisher）
- **今日头条**（Playwright 浏览器自动化）
- **小红书**（Playwright 浏览器自动化）

启动方式：
```bash
python3 server.py          # 启动 Web UI，访问 http://localhost:8765
```

---

## 二、文件结构

```
Autopublish/
├── server.py                    # HTTP 服务器 + 全部前端 HTML/JS（单文件）
├── autopublish/
│   ├── scheduler.py             # 核心调度入口，execute_publish()
│   ├── playwright_publisher.py  # Playwright 浏览器自动化（头条、小红书）
│   ├── wechat_api.py            # 微信公众号 API 发布
│   ├── models.py                # 数据模型、readiness check
│   ├── base.py                  # 常量、重试逻辑
│   └── stub.py                  # Stub 发布器（已从 UI 移除，内部 dry_run 仍用）
├── .data/
│   ├── accounts.json            # 各平台 Cookie / API 凭证
│   ├── publish_log.json         # 发布历史日志
│   └── uploads/                 # 用户上传的图片
└── .cookies/
    ├── toutiao_cookies.json     # 头条 Cookie（从 accounts.json 自动同步）
    └── xiaohongshu_cookies.json # 小红书 Cookie（从 accounts.json 自动同步）
```

---

## 三、核心架构

### 发布流程

```
浏览器 UI
  → POST /api/publish (publisher_type='playwright')
    → 后台线程 publish_bg()
      → execute_publish()          [scheduler.py]
        → 依次对每个平台执行：
          → execute_publish_plan()
            → _get_publisher()     # 同步 Cookie、创建 Publisher
            → asyncio.run(_publish_async())  # 在线程内新建 event loop
              → publisher.publish()
              → publisher.close()  # 必须在同一 event loop 内关闭！
            → 记录结果到 publish_log.json
```

### 关键约束：event loop 不能跨用

`PlaywrightPublisher` 的 `_browser` 和 `_playwright` 对象绑定到创建它们的 event loop。`close()` **必须在 `_publish_async` 的 `finally` 块里调用**（同一 event loop），绝不能在外层用 `asyncio.run(publisher.close())`——那会创建新 loop，尝试关闭旧 loop 的对象，永久挂死，导致后续平台永远不会启动。

---

## 四、各平台发布细节

### 4.1 微信公众号

- 使用 **API 模式**（`WechatApiPublisher`），不走 Playwright
- 需要 `cover_path`（封面图）：上传为 thumb_media_id 后创建草稿
- 凭证：AppID + AppSecret，配置在 `.data/accounts.json` 的 `wechat_official.appid/appsecret`
- **不能重试**：每次调用都创建新草稿（非幂等），`max_retries` 强制为 0
- 常见错误：
  - `40164` IP 不在白名单 → 微信公众平台后台加 IP
  - `40007` invalid media_id → 封面图上传失败，检查图片格式（JPEG/PNG）和大小

### 4.2 今日头条

Playwright 自动化，5 步流程：

1. 导航到 `https://mp.toutiao.com/` → 点击左侧导航"文章"
2. 隐藏 AI 助手抽屉（`.byte-drawer-wrapper`），否则挡住所有点击
3. 填写标题（`textarea[placeholder*="标题"]`）、正文（ProseMirror，需 `execCommand('insertText')`）
4. 点击"预览并发布" → 封面设置面板出现
5. **封面处理**（关键）：
   - 有 `cover_path` → 尝试上传封面图（`input[type="file"]`）
   - 无封面或上传失败 → 选"无封面"
   - **"无封面"是 ByteDance 自定义 radio 组件，`span.click()` 无效**，必须：
     1. JS 找到元素 bounding box 并调用 `scrollIntoView({block:'center'})`
     2. 用 `page.mouse.click(x, y)` 坐标点击
   - **条件只检查 `cover_path`**，与 `image_paths`（正文图）无关
6. 再次点击"预览并发布" → 先 `window.scrollTo(0, scrollHeight)` 确保按钮可见
7. 点击"确认发布"（timeout=8s）

**敏感词**：正文含"第一"等词会有 WARNING，不影响发布。

### 4.3 小红书

Playwright 自动化：

1. 导航到 `https://creator.xiaohongshu.com/publish/publish`
2. 切换到"上传图文"标签（需要过滤出可见的 tab 元素）
3. 上传图片：`input[type="file"][accept*="jpg"]`，用 `set_input_files()`
4. 填写标题（`input[placeholder*="填写标题"]`）
5. 填写正文：`document.execCommand('insertText')` —— 中文必须用此方式，`keyboard.type()` 不行
6. **点击发布按钮**（关键）：
   - 按钮在 `<xhs-publish-btn>` 自定义组件内，**closed shadow DOM**，JS/querySelector 完全无法访问
   - 必须用坐标点击：获取 `xhs-publish-btn` 的 bounding box，点击 `x + width*0.62, y + height*0.5`
   - 发布按钮在元素宽度 62% 处（75% 会点到外面）
7. 等待 URL 跳转到 `/publish/success?...` 确认成功（留在 `/publish/publish?from=tab_switch` 表示失败）

**Cookie 过期**：小红书 Cookie 有效期较短，定期需更新。通过浏览器 DevTools → Application → Cookies 导出后粘贴到账号管理。

---

## 五、已修复的关键 Bug（历史记录）

| Bug | 表现 | 根因 | 修复 |
|-----|------|------|------|
| 小红书发布按钮点不到 | 发布后页面没跳转 | `xhs-publish-btn` 是 closed shadow DOM，querySelector 找的是侧边栏"发布笔记"按钮 | 改为 bounding box 坐标点击，x=62% |
| 头条"无封面"选不中 | 封面面板出现但没有选中无封面，预览框不弹出 | ByteDance radio 组件，点文字 span 无效 | scrollIntoView + mouse.click 坐标点击 |
| 头条 cover_path 有值时跳过封面选择 | 同上 | `if not cover_path and not images:` 条件错误，`images` 是正文图非封面图 | 改为 `if not cover_path:` 只判断封面路径 |
| XHS 和头条顺序发布时 XHS 永不启动 | 头条成功后 XHS 无任何日志，任务永远不完成 | `asyncio.run(publisher.close())` 在新 event loop 里关闭旧 loop 的 Playwright 浏览器，永久挂死 | 把 `close()` 移到 `_publish_async` 的 `finally` 块，在同一 event loop 执行 |
| 微信重复发布 3 篇 | 同一篇文章在微信侧出现 3 个草稿 | `MAX_PUBLISH_RETRIES=3`，草稿创建非幂等 | 对 `wechat_official` 强制 `max_retries=0` |
| UI 始终用 Stub 模式 | 发布显示成功但平台上看不到文章 | `selectedPublisherMode` 每次页面加载重置为 `'stub'` | 删除 Stub 模式，改为 `const selectedPublisherMode = 'playwright'` 固定常量 |

---

## 六、运维注意事项

### 启动服务器
```bash
# 推荐：无缓冲输出，方便查日志
PYTHONUNBUFFERED=1 python3 server.py > /tmp/server_log.txt 2>&1 &
```

### 修改代码后必须重启
```bash
kill $(lsof -ti:8765) && sleep 1 && PYTHONUNBUFFERED=1 python3 server.py &
```

**不需要**刷新浏览器（已设置 `Cache-Control: no-store`）。

### 查看实时日志
```bash
tail -f /tmp/server_log.txt | grep -v "GET /api/publish/progress"
```

### Cookie 更新流程
1. 浏览器访问平台，手动登录
2. F12 → Application → Cookies → 全选复制（JSON 格式）
3. 粘贴到 UI 的"账号管理"页面 → 保存
4. 系统自动同步到 `.cookies/{platform}_cookies.json`

### 发布日志
```bash
python3 -c "
import json
from pathlib import Path
data = json.loads(Path('.data/publish_log.json').read_text())
for e in data[-10:]:
    print(f\"{e['time'][:19]} | {e['platform']:15} | {e['status']:8} | {e['publisher_type']} | {e.get('error','')[:60]}\")
"
```

### 去重机制
- **内存去重**：同一 server 进程内，`article_id + platform` 已成功则跳过（防止按钮连击）
- **日志去重**：扫描 `publish_log.json` 最近 50 条，若同 `article_id + platform` 已 playwright 成功则返回 `duplicate`
- 测试时用不同 `article_id` 可绕过

---

## 七、后端直接测试

不经过 UI，直接跑后端验证某平台：

```python
# 头条
import asyncio, sys
sys.path.insert(0, '/Users/bessie/cursor/Auto_content_production/Autopublish')
from autopublish.playwright_publisher import PlaywrightPublisher

async def test():
    pub = PlaywrightPublisher('toutiao')  # or 'xiaohongshu'
    result = await pub.publish(
        title='测试标题',
        body='测试正文内容' * 10,
        summary='', tags=['测试'], keywords=[],
        cover_path='', image_paths=['/path/to/img.png'],
        account_name='', author='', location='北京', topic_title='',
    )
    print(result.status.value, result.error_message)

asyncio.run(test())
```

```python
# 三平台顺序发布
from autopublish import execute_publish, PublishInput, Platform

result = execute_publish(
    PublishInput(
        article_id='test-001',
        title='...', body='...', summary='...',
        tags=['AI'], keywords=['人工智能'],
        author='AI观察员', location='北京',
        account_label='my-main-account',
        cover_path='/path/to/cover.png',
        image_paths=['/path/to/img.png'],
        platforms=[Platform.TOUTIAO, Platform.XIAOHONGSHU],
    ),
    publisher_type='playwright',
)
for p in result.plans:
    print(p['platform'], p['result']['status'], p['result'].get('error_message',''))
```

---

## 八、Readiness Check（发布前校验）

`autopublish/models.py` 的 `build_readiness()` 对每个平台做 7 项检查：

| 字段 | 阻塞？ | 说明 |
|------|--------|------|
| 标题 | ✅ | 所有平台必填 |
| 正文 | ✅ | 所有平台必填 |
| 摘要 | ❌ | 建议填 |
| 标签 | ❌ | 建议填 |
| 封面图 | **仅微信** ✅ | 微信 API 必须有 thumb_media_id |
| 账号标签 | ✅ | 所有平台必填 |
| 发布地点 | ❌ | 小红书建议填 |

头条和小红书**不阻塞**封面图缺失，代码层面自动处理（头条选"无封面"，小红书不需要封面）。
