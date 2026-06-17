"""Platform-specific content formatters.

Generates platform-appropriate title/body/tags for:
- 微信公众号 (WeChat Official Account)
- 今日头条 (Toutiao)
- 小红书 (Xiaohongshu)
"""

from __future__ import annotations

from autopublish.models import Platform, PublishInput, PublishPlan


def make_wechat_package(plan: PublishPlan, input_data: PublishInput) -> None:
    """Format content for WeChat Official Account.

    Platform requirements:
    - title: max 64 chars (required)
    - content: HTML body (required)
    - digest/summary: max 120 chars
    - thumb_media_id: cover image permanent media_id (required — must upload cover_path first)
    - author: 原创作者署名
    - tags: keywords for discoverability (not an API field, used for internal tracking)
    - Cover ratio: 2.35:1
    """
    plan.title = input_data.title[:64]
    plan.body = input_data.body.replace("\n", "\n\n")
    plan.summary = input_data.summary[:120]
    plan.tags = list(dict.fromkeys([*input_data.keywords[:4], *input_data.tags[:2], "深度解读", "观点"]))
    # author and cover_path are passed through metadata (used directly by WechatApiPublisher)


def make_toutiao_package(plan: PublishPlan, input_data: PublishInput) -> None:
    """Format content for Toutiao.

    Platform requirements:
    - title: max 30 chars, punchy (required)
    - body: plain paragraphs, no markdown headings
    - summary/brief: max 80 chars (shown in feed card)
    - tags: up to 5 tags
    - topic_title: 选题标题，关联头条话题
    - cover images: 16:9, up to 3 images
    - author: inherited from account, not a form field
    """
    plan.title = input_data.title[:30]
    paragraphs = [line.strip() for line in input_data.body.splitlines() if line.strip() and not line.startswith("#")]
    plan.body = "\n".join(paragraphs)
    plan.summary = input_data.summary[:80]
    plan.tags = list(dict.fromkeys([*input_data.keywords[:3], *input_data.tags[:2], "热点解读"]))
    # topic_title and cover_path are passed through metadata


def make_xiaohongshu_package(plan: PublishPlan, input_data: PublishInput) -> None:
    """Format content for Xiaohongshu.

    Platform requirements:
    - title: max 20 chars (required, shown as note title)
    - body: conversational tone, max ~2000 chars per card
    - tags: #话题标签，up to 30，mix of keywords and topic tags
    - location: 发布地点 (optional but improves reach)
    - topic_title: 话题/选题，与平台话题关联
    - cover + images: 3:4 vertical, 1–9 images (required for 图文笔记)
    - author: inherited from account
    """
    topic_title = (input_data.topic_title or input_data.title)[:14]
    plan.title = f"{topic_title}: 普通人怎么看"[:20]
    plan.body = (
        f"这件事和普通人的关系是：它会影响你的选择成本。\n\n"
        f"先别急着站队，先看三个问题：\n"
        f"1. 它会不会帮你省时间、省钱或少踩坑？\n"
        f"2. 它改变的是短期热闹，还是长期习惯？\n"
        f"3. 如果明天热度没了，你还能用它做什么判断？\n\n"
        f"我的结论：{input_data.summary or input_data.body[:80]}"
    )
    plan.summary = input_data.summary[:80]
    plan.tags = list(dict.fromkeys([*input_data.keywords[:4], *input_data.tags[:2], "普通人视角", "热点解读", "自我提升"]))
    # location, cover_path, image_paths are passed through metadata


def build_platform_package_for_input(plan: PublishPlan, input_data: PublishInput) -> None:
    """Apply platform-specific formatting to a PublishPlan."""
    if plan.platform == Platform.WECHAT_OFFICIAL:
        make_wechat_package(plan, input_data)
    elif plan.platform == Platform.TOUTIAO:
        make_toutiao_package(plan, input_data)
    elif plan.platform == Platform.XIAOHONGSHU:
        make_xiaohongshu_package(plan, input_data)
    else:
        raise ValueError(f"Unsupported platform: {plan.platform}")
