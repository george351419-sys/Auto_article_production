"""Data models for autopublish — standalone, no FastAPI/Repository dependencies."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ── Platform Enum ────────────────────────────────────────────


class Platform(StrEnum):
    WECHAT_OFFICIAL = "wechat_official"
    TOUTIAO = "toutiao"
    XIAOHONGSHU = "xiaohongshu"


# ── Status Enums ─────────────────────────────────────────────


class PublishStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    DUPLICATE = "duplicate"


class PublishPlanStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_METADATA = "needs_metadata"
    NEEDS_REVIEW = "needs_review"
    READY = "ready"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class ChecklistStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


# ── Core Publishing Models ───────────────────────────────────


class PublishMetadata:
    """Metadata for a publish plan."""

    def __init__(
        self,
        title: str = "",
        summary: str = "",
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
        location: str = "",
        author: str = "",
        account_label: str = "",
        cover_path: str = "",
        image_paths: list[str] | None = None,
        topic_title: str = "",
        platform_notes: str = "",
    ):
        self.title = title
        self.summary = summary
        self.tags = tags or []
        self.keywords = keywords or []
        self.location = location
        self.author = author
        self.account_label = account_label
        self.cover_path = cover_path
        self.image_paths = image_paths or []
        self.topic_title = topic_title
        self.platform_notes = platform_notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "keywords": self.keywords,
            "location": self.location,
            "author": self.author,
            "account_label": self.account_label,
            "cover_path": self.cover_path,
            "image_paths": self.image_paths,
            "topic_title": self.topic_title,
            "platform_notes": self.platform_notes,
        }


class PublishChecklistItem:
    def __init__(self, key: str, label: str, status: ChecklistStatus = ChecklistStatus.FAIL, blocking: bool = True, message: str = ""):
        self.key = key
        self.label = label
        self.status = status
        self.blocking = blocking
        self.message = message


class PublishReadinessReport:
    def __init__(self, passed: bool = False, score: float = 0.0, blocking_reasons: list[str] | None = None, recommendations: list[str] | None = None):
        self.passed = passed
        self.score = score
        self.blocking_reasons = blocking_reasons or []
        self.recommendations = recommendations or []


class PublishPlan:
    """A publish plan for one platform."""

    def __init__(
        self,
        article_id: str,
        platform: Platform,
        metadata: PublishMetadata | None = None,
        status: PublishPlanStatus = PublishPlanStatus.DRAFT,
        scheduled_at: datetime | None = None,
    ):
        self.id = _new_id("publish")
        self.article_id = article_id
        self.platform = platform
        self.metadata = metadata or PublishMetadata()
        self.title: str = self.metadata.title
        self.body: str = self.metadata.summary  # will be overwritten by platform formatter
        self.summary: str = self.metadata.summary
        self.tags: list[str] = self.metadata.tags
        self.cover_path: str = self.metadata.cover_path
        self.image_paths: list[str] = self.metadata.image_paths
        self.checklist: list[PublishChecklistItem] = []
        self.readiness_report: PublishReadinessReport = PublishReadinessReport()
        self.status: PublishPlanStatus = status
        self.scheduled_at: datetime | None = scheduled_at
        self.published_url: str = ""
        self.actual_published_at: datetime | None = None
        self.created_at: datetime = _utc_now()
        self.updated_at: datetime = _utc_now()


class PublishAttempt:
    def __init__(
        self,
        plan_id: str,
        platform: str = "",
        publisher_type: str = "stub",
        status: str = "pending",
        trace_id: str = "",
        retry_count: int = 0,
        platform_url: str = "",
        error_message: str = "",
    ):
        self.id = _new_id("attempt")
        self.plan_id = plan_id
        self.platform = platform
        self.publisher_type = publisher_type
        self.status = status
        self.trace_id = trace_id or f"pub_{uuid4().hex[:12]}"
        self.retry_count = retry_count
        self.platform_url = platform_url
        self.error_message = error_message
        self.created_at: datetime = _utc_now()


class PublishResult:
    def __init__(
        self,
        status: PublishStatus,
        platform_url: str = "",
        error_message: str = "",
        retry_count: int = 0,
        trace_id: str = "",
    ):
        self.status = status
        self.platform_url = platform_url
        self.error_message = error_message
        self.retry_count = retry_count
        self.trace_id = trace_id or f"pub_{uuid4().hex[:12]}"


# ── User-Facing Input / Output ───────────────────────────────


class PublishInput:
    """The input for auto-publishing: an article + its metadata.

    This is what callers construct before calling execute_publish().
    """

    def __init__(
        self,
        article_id: str,
        title: str,
        body: str,
        summary: str = "",
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
        author: str = "",
        location: str = "",
        cover_path: str = "",
        image_paths: list[str] | None = None,
        account_label: str = "",
        topic_title: str = "",
        platforms: list[Platform] | None = None,
    ):
        self.article_id = article_id
        self.title = title
        self.body = body
        self.summary = summary or body[:120]
        self.tags = tags or []
        self.keywords = keywords or []
        self.author = author
        self.location = location
        self.cover_path = cover_path
        self.image_paths = image_paths or []
        self.account_label = account_label
        self.topic_title = topic_title or title
        self.platforms = platforms or [Platform.WECHAT_OFFICIAL, Platform.TOUTIAO, Platform.XIAOHONGSHU]


class PublishOutput:
    """The result of a publish run across platforms."""

    def __init__(self, article_id: str, plans: list[dict[str, Any]] | None = None, errors: list[dict[str, Any]] | None = None):
        self.article_id = article_id
        self.plans = plans or []
        self.errors = errors or []

    @property
    def all_succeeded(self) -> bool:
        return len(self.errors) == 0 and all(p.get("result", {}).get("status") == "success" for p in self.plans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "plans": self.plans,
            "errors": self.errors,
            "all_succeeded": self.all_succeeded,
        }


# ── Helper: build publish plan ───────────────────────────────


def build_publish_plan(input_data: PublishInput, platform: Platform) -> PublishPlan:
    """Build a PublishPlan from PublishInput for a specific platform.

    The plan's title/body/summary/tags are set based on platform-specific
    formatting, while metadata carries the raw input.
    """
    from autopublish.platforms import build_platform_package_for_input

    metadata = PublishMetadata(
        title=input_data.title,
        summary=input_data.summary,
        tags=input_data.tags,
        keywords=input_data.keywords,
        location=input_data.location,
        author=input_data.author,
        account_label=input_data.account_label,
        cover_path=input_data.cover_path,
        image_paths=input_data.image_paths,
        topic_title=input_data.topic_title,
    )

    plan = PublishPlan(
        article_id=input_data.article_id,
        platform=platform,
        metadata=metadata,
    )

    # Apply platform-specific formatting
    build_platform_package_for_input(plan, input_data)

    plan.readiness_report = build_readiness(plan, input_data)
    return plan


def build_readiness(plan: PublishPlan, input_data: PublishInput) -> PublishReadinessReport:
    """Run the 7-point readiness check on a publish plan."""
    meta = plan.metadata
    checks: list[PublishChecklistItem] = []

    # 1. Title
    title_ok = bool(meta.title.strip())
    checks.append(PublishChecklistItem(
        key="title", label="标题",
        status=ChecklistStatus.PASS if title_ok else ChecklistStatus.FAIL,
        message="标题已填写" if title_ok else "需要填写标题",
    ))

    # 2. Body content
    body_ok = bool(plan.body.strip())
    checks.append(PublishChecklistItem(
        key="body", label="正文",
        status=ChecklistStatus.PASS if body_ok else ChecklistStatus.FAIL,
        message="正文已准备" if body_ok else "需要正文内容",
    ))

    # 3. Summary
    summary_ok = bool(meta.summary.strip())
    checks.append(PublishChecklistItem(
        key="summary", label="摘要",
        status=ChecklistStatus.PASS if summary_ok else ChecklistStatus.FAIL,
        message="摘要完整" if summary_ok else "需要填写摘要",
        blocking=False,
    ))

    # 4. Tags
    tags_ok = bool(meta.tags)
    checks.append(PublishChecklistItem(
        key="tags", label="标签",
        status=ChecklistStatus.PASS if tags_ok else ChecklistStatus.FAIL,
        message=f"{len(meta.tags)} 个标签" if tags_ok else "需要至少一个标签",
        blocking=False,
    ))

    # 5. Cover image (required for wechat_official API — thumb_media_id is mandatory)
    cover_ok = bool(meta.cover_path.strip())
    is_wechat = plan.platform == Platform.WECHAT_OFFICIAL
    checks.append(PublishChecklistItem(
        key="cover", label="封面图",
        status=ChecklistStatus.PASS if cover_ok else (ChecklistStatus.FAIL if is_wechat else ChecklistStatus.WARNING),
        message="封面图已设置" if cover_ok else ("微信公众号必须填写封面图路径（API 必填）" if is_wechat else "建议设置封面图"),
        blocking=is_wechat,
    ))

    # 6. Account
    account_ok = bool(meta.account_label.strip())
    checks.append(PublishChecklistItem(
        key="account", label="发布账号",
        status=ChecklistStatus.PASS if account_ok else ChecklistStatus.FAIL,
        message=f"账号: {meta.account_label}" if account_ok else "需要指定发布账号",
    ))

    # 7. Platform-specific: Xiaohongshu needs location
    if plan.platform == Platform.XIAOHONGSHU:
        loc_ok = bool(meta.location.strip())
        checks.append(PublishChecklistItem(
            key="location", label="发布地点(小红书)",
            status=ChecklistStatus.PASS if loc_ok else ChecklistStatus.WARNING,
            message="地点已设置" if loc_ok else "小红书建议填写发布地点",
            blocking=False,
        ))

    plan.checklist = checks
    blocking_reasons = [c.message for c in checks if c.blocking and c.status == ChecklistStatus.FAIL]
    score = round(10 * (len(checks) - len(blocking_reasons)) / len(checks), 2) if checks else 0.0

    return PublishReadinessReport(
        passed=len(blocking_reasons) == 0,
        score=score,
        blocking_reasons=blocking_reasons,
        recommendations=[c.message for c in checks if c.status != ChecklistStatus.PASS],
    )
