#!/usr/bin/env python3
"""Demo: auto-publish an article to WeChat, Toutiao, and Xiaohongshu.

This demo uses the StubPublisher (safe, logs only). For real publishing:
1. Set AUTOPUBLISH_MODE=playwright in env, or
2. Pass publisher_type="playwright" to execute_publish()
3. Install: pip install autopublish[playwright] && playwright install chromium

Usage:
    python demo.py
"""

from autopublish import (
    Platform,
    PublishInput,
    execute_publish,
    execute_publish_plan,
    build_publish_plan,
    StubPublisher,
    list_attempts,
)

# ── 1. Build the input ──────────────────────────────────────

article = PublishInput(
    article_id="demo-article-001",
    title="AI大模型正在改变普通人的工作方式",
    body="""过去一年，AI大模型从实验室走进了每个人的日常办公场景。

第一层变化：信息获取方式的改变

以前我们搜索信息，需要自己在搜索引擎里输入关键词、打开多个网页逐一阅读、对比、整理。现在，你只需要用自然语言提问，AI就能给你一个结构化的回答。这不是搜索工具的升级，而是信息消费方式的根本变化。

第二层变化：内容创作门槛的降低

写报告、做PPT、画图、剪视频——这些原本需要专业技能的事情，现在通过简单的文字描述就能完成。这意味着"会使用AI"比"会某项技能"更重要。

第三层变化：决策方式的升级

当AI能帮你分析数据、总结趋势、给出建议时，"拍脑袋决策"正在变成"数据+AI辅助决策"。普通人也第一次拥有了以前只有大公司才有的分析能力。

普通人应该怎么应对这三层变化？答案是：把AI当作"思考的伙伴"，而不是"替代品"。它擅长信息整理和模式识别，但判断力、创造力、共情能力——这些人类独有的能力，仍然是不可替代的。""",
    summary="AI大模型带来的三层变化：信息获取、内容创作、决策方式，以及普通人如何应对。",
    tags=["AI", "大模型", "效率提升", "职场"],
    keywords=["人工智能", "大模型", "工作效率", "AI工具"],
    author="AI观察员",
    location="北京",
    cover_path="",
    image_paths=[],
    account_label="my-wechat-account",
    topic_title="AI大模型改变工作方式",
)

# ── 2. Publish to all three platforms ───────────────────────

print("=" * 60)
print("AutoPublish Demo — StubPublisher (safe mode)")
print("=" * 60)

result = execute_publish(
    article,
    publisher_type="stub",  # safe: logs only
    # publisher_type="playwright",  # real: browser automation
    dry_run=False,
)

print("\n" + "=" * 60)
print("Results:")
print("=" * 60)

for plan in result.plans:
    print(f"\n  Platform: {plan['platform']}")
    print(f"  Status: {plan['result']['status']}")
    print(f"  URL: {plan['result']['platform_url']}")
    if plan["result"].get("error_message"):
        print(f"  Error: {plan['result']['error_message']}")

print(f"\nAll succeeded: {result.all_succeeded}")

# ── 3. Also demonstrate building a single plan ──────────────

print("\n" + "=" * 60)
print("Single Plan Demo — Xiaohongshu")
print("=" * 60)

plan = build_publish_plan(article, Platform.XIAOHONGSHU)
print(f"\n  Plan ID: {plan.id}")
print(f"  Platform: {plan.platform.value}")
print(f"  Title: {plan.title}")
print(f"  Tags: {plan.tags}")
print(f"  Readiness: passed={plan.readiness_report.passed}, score={plan.readiness_report.score}")
print(f"  Blocking reasons: {plan.readiness_report.blocking_reasons}")

single_result = execute_publish_plan(plan, publisher_type="stub")
print(f"\n  Publish result: {single_result['result']['status']}")
