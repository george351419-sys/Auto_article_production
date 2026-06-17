"""Scheduler — the main orchestration entry point.

This is the primary API that callers use:

    from autopublish import execute_publish, PublishInput

    result = execute_publish(PublishInput(
        article_id="my-article-1",
        title=...,
        body=...,
        tags=["AI", "科技"],
        keywords=["人工智能", "大模型"],
        cover_path="/path/to/cover.png",
        image_paths=["/path/to/img1.png"],
        account_label="my-account",
        platforms=[Platform.WECHAT_OFFICIAL, Platform.TOUTIAO, Platform.XIAOHONGSHU],
    ))

Supports three publisher backends:
- stub (default, safe): logs only
- playwright: real browser automation via Playwright
- social: bridge to social-auto-upload CLI tool
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from autopublish.base import (
    MAX_PUBLISH_RETRIES,
    PublishResult,
    PublishStatus,
    backoff_delay,
    build_idempotent_key,
    should_retry,
)
from autopublish.models import (
    Platform,
    PublishAttempt,
    PublishInput,
    PublishOutput,
    build_publish_plan,
    build_readiness,
)
from autopublish.stub import StubPublisher

# ── In-memory idempotency store ─────────────────────────────

_published_plans: set[str] = set()
_publish_attempts: list[PublishAttempt] = []

# ── Cookie sync ──────────────────────────────────────────────

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_ACCOUNTS_FILE = _PROJECT_DIR / ".data" / "accounts.json"
_COOKIES_DIR = _PROJECT_DIR / ".cookies"

_PLATFORM_ORIGIN_URLS = {
    "toutiao": "https://mp.toutiao.com/",
    "xiaohongshu": "https://creator.xiaohongshu.com/",
    "wechat_official": "https://mp.weixin.qq.com/",
}


def _parse_cookie_to_playwright(raw: str, origin_url: str) -> list[dict]:
    """Parse cookie string (JSON array or key=val; format) into Playwright-compatible list."""
    raw = raw.strip()

    # Format A: JSON array from browser DevTools export
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
            result = []
            for c in arr:
                entry: dict = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                }
                if c.get("secure") is not None:
                    entry["secure"] = bool(c["secure"])
                if c.get("httpOnly") is not None:
                    entry["httpOnly"] = bool(c["httpOnly"])
                same_site = c.get("sameSite", "")
                if same_site == "no_restriction":
                    entry["sameSite"] = "None"
                elif same_site in ("strict", "lax"):
                    entry["sameSite"] = same_site.capitalize()
                # "unspecified" and others → omit, let Playwright default
                if "expirationDate" in c:
                    entry["expires"] = int(c["expirationDate"])
                result.append(entry)
            return result
        except (json.JSONDecodeError, KeyError):
            pass

    # Format B: simple text — key=value; key=value
    result = []
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            result.append({
                "name": k.strip(), "value": v.strip(),
                "domain": "", "path": "/", "url": origin_url,
            })
    return result


def _sync_cookies_for_playwright(platform: str) -> bool:
    """Sync cookie from accounts.json → .cookies/{platform}_cookies.json for PlaywrightPublisher.

    Returns True if cookies were synced, False if unavailable.
    """
    if not _ACCOUNTS_FILE.exists():
        return False

    try:
        accounts = json.loads(_ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False

    acct = accounts.get(platform, {})
    mode = acct.get("mode", "cookie")
    if mode == "api":
        return False  # API mode doesn't use browser cookies

    raw = (acct.get("cookie") or "").strip()
    if not raw:
        print(f"[autopublish] No cookie configured for {platform}")
        return False

    origin_url = _PLATFORM_ORIGIN_URLS.get(platform, "")
    cookies = _parse_cookie_to_playwright(raw, origin_url)
    if not cookies:
        print(f"[autopublish] Could not parse cookies for {platform}")
        return False

    _COOKIES_DIR.mkdir(exist_ok=True)
    cookie_file = _COOKIES_DIR / f"{platform}_cookies.json"
    cookie_file.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[autopublish] Synced {len(cookies)} cookies for {platform} → {cookie_file.name}")
    return True


# ── Publisher factory ────────────────────────────────────────

def _get_publisher(platform: str, publisher_type: str = "stub"):
    """Get the appropriate publisher implementation.

    For wechat_official: uses WechatApiPublisher (API mode) when credentials are configured.
    For toutiao/xiaohongshu: syncs cookies from accounts.json before launching Playwright.
    """
    # WeChat: prefer API publisher over browser
    if platform == "wechat_official" and publisher_type == "playwright":
        try:
            from autopublish.wechat_api import WechatApiPublisher
            pub = WechatApiPublisher.from_accounts_json()
            print(f"[autopublish] Using WechatApiPublisher for {platform}")
            return pub
        except Exception as e:
            print(f"[autopublish] WechatApiPublisher unavailable ({e}), falling back to Playwright")
            _sync_cookies_for_playwright(platform)
            try:
                from autopublish.playwright_publisher import PlaywrightPublisher
                return PlaywrightPublisher(platform)
            except Exception as e2:
                return PublishResult(
                    status=PublishStatus.FAILED,
                    error_message=f"Playwright 不可用: {e2}",
                )

    if publisher_type == "social":
        try:
            from autopublish.social_auto_upload import SocialAutoUploadPublisher
            return SocialAutoUploadPublisher(platform)
        except Exception:
            return StubPublisher(platform)
    elif publisher_type == "playwright":
        # Sync cookies from accounts.json → .cookies/ before launching browser
        synced = _sync_cookies_for_playwright(platform)
        if not synced:
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"{platform} 未配置 Cookie，请先在账号管理中保存 Cookie 后再使用 Playwright 模式",
            )
        try:
            from autopublish.playwright_publisher import PlaywrightPublisher
            return PlaywrightPublisher(platform)
        except Exception as e:
            return PublishResult(
                status=PublishStatus.FAILED,
                error_message=f"Playwright 启动失败: {e}",
            )
    else:
        return StubPublisher(platform)


def _build_publish_kwargs(plan) -> dict:
    """Build the full keyword-argument dict for any publisher.publish() call."""
    return dict(
        title=plan.title,
        body=plan.body,
        summary=plan.summary,
        tags=plan.tags,
        cover_path=plan.metadata.cover_path,
        image_paths=plan.metadata.image_paths,
        account_name=plan.metadata.account_label,
        author=plan.metadata.author,
        location=plan.metadata.location,
        topic_title=plan.metadata.topic_title,
        keywords=plan.metadata.keywords,
    )


async def _publish_async(publisher, plan, publisher_type: str) -> PublishResult:
    """Execute publish via a publisher that may be async (Playwright) or sync.
    Closes the publisher within the same event loop to avoid hanging on asyncio.run(close()).
    """
    kwargs = _build_publish_kwargs(plan)
    try:
        import inspect
        if hasattr(publisher, "publish") and inspect.iscoroutinefunction(publisher.publish):
            result = await publisher.publish(**kwargs)
        else:
            result = publisher.publish(**kwargs)
    finally:
        if hasattr(publisher, "close"):
            import inspect as _i
            try:
                if _i.iscoroutinefunction(publisher.close):
                    await publisher.close()
                else:
                    publisher.close()
            except Exception:
                pass
    return result


def execute_publish_plan(
    plan,
    publisher_type: str = "stub",
    max_retries: int = MAX_PUBLISH_RETRIES,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a single PublishPlan with retry + idempotency.

    Args:
        plan: PublishPlan to execute.
        publisher_type: 'stub' | 'social' | 'playwright'.
        max_retries: Max retry attempts.
        dry_run: If True, skip actual publishing (returns stub result).

    Returns:
        Dict with status and result details.
    """
    platform_str = plan.platform.value if hasattr(plan.platform, "value") else str(plan.platform)

    # Idempotency: key = article_id + platform (stable across repeated button clicks)
    dedup_key = f"{plan.article_id}:{platform_str}"
    idempotency_key = build_idempotent_key(dedup_key)

    # Fast path: in-memory check (same server session)
    if dedup_key in _published_plans:
        return {
            "status": "duplicate",
            "plan_id": plan.id,
            "platform": platform_str,
            "idempotency_key": idempotency_key,
            "publisher_type": publisher_type if not dry_run else "dry_run",
            "real_publish": False,
            "result": {"status": "duplicate", "platform_url": "", "error_message": "已发布过相同文章，跳过重复发布", "retry_count": 0, "trace_id": ""},
        }

    # Persistent check: scan log file for successful publish of same article+platform
    # (catches duplicates across server restarts)
    if not dry_run and publisher_type != "stub":
        log_path = _PROJECT_DIR / ".data" / "publish_log.json"
        if log_path.exists():
            try:
                log_entries = json.loads(log_path.read_text(encoding="utf-8"))
                for entry in reversed(log_entries[-50:]):  # check last 50 entries
                    if (entry.get("article_id") == plan.article_id
                            and entry.get("platform") == platform_str
                            and entry.get("status") == "success"
                            and entry.get("publisher_type") != "stub"):
                        return {
                            "status": "duplicate",
                            "plan_id": plan.id,
                            "platform": platform_str,
                            "idempotency_key": idempotency_key,
                            "publisher_type": publisher_type,
                            "real_publish": False,
                            "result": {
                                "status": "duplicate",
                                "platform_url": entry.get("url", ""),
                                "error_message": f"已在 {entry.get('time','')[:19]} 成功发布过，跳过重复发布",
                                "retry_count": 0,
                                "trace_id": "",
                            },
                        }
            except Exception:
                pass

    # Readiness check
    readiness = plan.readiness_report
    if not readiness.passed and not dry_run:
        error_msg = f"Publish plan not ready: {readiness.blocking_reasons}"
        return {
            "status": "error",
            "error": error_msg,
            "plan_id": plan.id,
            "platform": platform_str,
            "idempotency_key": idempotency_key,
            "real_publish": False,
            "result": {
                "status": "failed",
                "error_message": error_msg,
                "platform_url": "",
                "platform_msg_id": "",
                "retry_count": 0,
                "trace_id": "",
            },
        }

    # WeChat draft creation is non-idempotent: each retry creates a new draft article.
    # Force max_retries=0 for wechat_official to prevent duplicate articles.
    if platform_str == "wechat_official" and publisher_type != "stub":
        max_retries = 0

    # Retry loop
    last_result: PublishResult | None = None
    attempt = 0

    while attempt <= max_retries:
        if dry_run:
            publisher = StubPublisher(platform_str)
        else:
            publisher = _get_publisher(platform_str, publisher_type)

        # _get_publisher returns a PublishResult directly when setup fails (no retry needed)
        if isinstance(publisher, PublishResult):
            result = publisher
            result.retry_count = attempt
            last_result = result
            break

        if attempt > 0:
            delay = backoff_delay(attempt - 1)
            print(f"[autopublish] Retry {attempt} for {plan.id} in {delay:.1f}s")
            time.sleep(delay)

        import inspect
        import asyncio

        if inspect.iscoroutinefunction(publisher.publish):
            result = asyncio.run(_publish_async(publisher, plan, publisher_type))
        else:
            result = publisher.publish(**_build_publish_kwargs(plan))

        result.retry_count = attempt
        last_result = result

        print(f"[autopublish] {plan.id} {platform_str}: {result.status.value} (attempt {attempt})")

        att = PublishAttempt(
            plan_id=plan.id,
            platform=platform_str,
            publisher_type="dry_run" if dry_run else publisher_type,
            status=result.status.value,
            trace_id=result.trace_id,
            retry_count=attempt,
            platform_url=result.platform_url,
            error_message=result.error_message,
        )
        _publish_attempts.append(att)

        if not should_retry(result):
            break
        attempt += 1

    if last_result and last_result.status == PublishStatus.SUCCESS:
        _published_plans.add(dedup_key)

    # NOTE: async publishers (Playwright) are closed inside _publish_async/the same
    # event loop. Do NOT call asyncio.run(publisher.close()) here — that creates a new
    # event loop which hangs trying to close a browser from the old loop, blocking all
    # subsequent platform publishes.
    if hasattr(publisher, "close") and not dry_run:
        import inspect as _inspect
        if not _inspect.iscoroutinefunction(publisher.close):
            try:
                publisher.close()
            except Exception:
                pass

    return {
        "plan_id": plan.id,
        "platform": platform_str,
        "article_id": plan.article_id,
        "publisher_type": "dry_run" if dry_run else publisher_type,
        "real_publish": publisher_type != "stub" and not dry_run,
        "result": {
            "status": last_result.status.value if last_result else "unknown",
            "platform_url": last_result.platform_url if last_result else "",
            "error_message": last_result.error_message if last_result else "",
            "retry_count": attempt,
            "trace_id": last_result.trace_id if last_result else "",
        },
    }


def execute_publish(
    input_data: PublishInput,
    publisher_type: str = "stub",
    max_retries: int = MAX_PUBLISH_RETRIES,
    dry_run: bool = False,
    platforms: list[Platform] | None = None,
) -> PublishOutput:
    """Publish an article to one or more platforms.

    This is the main entry point. Given a PublishInput (article + metadata),
    it builds platform-specific plans, checks readiness, and publishes each.

    Args:
        input_data: The article content and metadata.
        publisher_type: 'stub' (safe default), 'social', or 'playwright'.
        max_retries: Max retries per platform.
        dry_run: If True, use StubPublisher regardless of publisher_type.
        platforms: Override platforms from input_data. If None, uses input_data.platforms.

    Returns:
        PublishOutput with per-platform results.
    """
    targets = platforms or input_data.platforms or [Platform.WECHAT_OFFICIAL, Platform.TOUTIAO, Platform.XIAOHONGSHU]

    plans_output: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for platform in targets:
        try:
            plan = build_publish_plan(input_data, platform)
            result = execute_publish_plan(
                plan,
                publisher_type=publisher_type,
                max_retries=max_retries,
                dry_run=dry_run,
            )
            plans_output.append(result)
            if result.get("status") == "error":
                errors.append({"platform": platform.value, "error": result.get("error", "unknown")})
        except Exception as exc:
            err = {"platform": platform.value, "error": str(exc)}
            errors.append(err)
            plans_output.append({"status": "error", "platform": platform.value, "error": str(exc)})

    return PublishOutput(article_id=input_data.article_id, plans=plans_output, errors=errors)


def list_attempts(plan_id: str | None = None) -> list[PublishAttempt]:
    if plan_id:
        return [a for a in _publish_attempts if a.plan_id == plan_id]
    return list(_publish_attempts)
