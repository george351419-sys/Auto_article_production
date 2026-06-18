"""M2 Scheduler — drives state machine transitions without human intervention.

For M2 (minimal path): polls writing, calls mock scorer, triggers autopublish.
Jumps from collected → matched → writing → drafted → scored → reviewing → publishing → published.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any  # noqa: F401 — used in dynamic type annotations

import aiosqlite
import httpx

import assets as assets_mod
import crud
import dedup
import dispatch
import final_package_validator as fp_validate
import retry as retry_mod
import state_machine as sm
from bridge import (
    AutopublishClient,
    ScorerClient,
    WritingClient,
    make_idempotency_key,
)

logger = logging.getLogger("scheduler_v2")

THIS_DIR = Path(__file__).parent

# Maximum time a writing task may stay in "running" without progress before we auto-fail it
WRITING_TASK_STUCK_TIMEOUT_SECONDS = 60 * 30  # 30 minutes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fail_with_retry(
    db: aiosqlite.Connection,
    article_id: str,
    from_state: str,
    error: str,
    *,
    trigger: str = "auto",
) -> None:
    """Move an article to `failed` and arm the next retry timer.

    Always written through the state machine so audit_log is consistent.
    The next-retry timestamp is computed from the article's *current*
    retry_count (i.e. attempts so far); see retry.next_retry_at.
    """
    # Read current retry_count BEFORE transitioning so we backoff against
    # the right slot. The transition writes audit_log; the retry helper
    # then updates retry_count + next_retry_at on its own connection.
    cursor = await db.execute("SELECT retry_count FROM article WHERE id = ?", (article_id,))
    row = await cursor.fetchone()
    current_retries = row["retry_count"] if row else 0

    await db.execute(
        "UPDATE article SET last_error_message = ?, updated_at = ? WHERE id = ?",
        (error[:1000], _now(), article_id),
    )
    await sm.transition_article(db, article_id, "failed", trigger,
                                from_state=from_state, payload={"error": error[:500]})
    await db.commit()  # commit before retry_mod opens its own connection
    await retry_mod.schedule_retry(article_id, current_retries)


# ── Step runners — each steps one article through a transition ──


async def step_collected_to_matched(db: aiosqlite.Connection, article_id: str) -> None:
    """collected → matched (or → duplicated).

    PRD §11: before matching, run L1 (normalized title) + L2 (entity
    Jaccard ≥ 0.7 ∧ keyword overlap ≥ 1) dedup. If the topic is duplicate,
    mark the article duplicated and stop the pipeline for it.
    """
    cursor = await db.execute("SELECT topic_id FROM article WHERE id = ?", (article_id,))
    row = await cursor.fetchone()
    if row is None:
        return
    topic_id = row["topic_id"]

    # run_dedup opens its own connection — commit the in-flight one first
    # so it can see the most recent topic/article rows.
    await db.commit()
    dedup_result = await dedup.run_dedup(topic_id)
    if dedup_result.get("duplicated"):
        await sm.transition_article(
            db, article_id, "duplicated", "auto",
            from_state="collected",
            payload={
                "method": dedup_result.get("method"),
                "dup_of_topic_id": dedup_result.get("dup_of"),
            },
        )
        return

    # Not a duplicate → assign a (mock) character and advance to matched.
    # Real character matching via distilled_characters is left for M5/M6.
    await db.execute(
        "UPDATE article SET character_id = ?, updated_at = ? WHERE id = ?",
        ("mock-char-1", _now(), article_id),
    )
    await sm.transition_article(db, article_id, "matched", "auto",
                                from_state="collected")


async def step_matched_to_writing(db: aiosqlite.Connection, article: dict) -> None:
    """matched → writing: create and run a writing task via the writing module."""
    config = _load_config()
    topic = await crud.get_topic(article["topic_id"])
    if not topic:
        raise ValueError(f"Topic {article['topic_id']} not found")

    client = WritingClient(config["services"]["writing_url"])
    trace_id = article.get("trace_id") or ""
    retry_count = int(article.get("retry_count", 0))

    writing_cfg = config.get("writing", {}) if isinstance(config, dict) else {}
    voice_model = writing_cfg.get("default_voice_model") or (
        "一位资深内容创作者，文风冷静克制，擅长把复杂趋势拆解成读者能用的认知工具。"
    )
    promotion_goal = writing_cfg.get(
        "default_promotion_goal",
        "吸引用户阅读、关注和转发，提升账号专业影响力",
    )
    search_enabled = bool(writing_cfg.get("search_enabled", True))

    source_materials = _topic_source_materials(topic)

    task = await client.create_task(
        topic=topic["title"],
        topic_brief=topic.get("brief") or topic["title"],
        celebrity_voice_model=voice_model,
        platforms=["wechat", "xiaohongshu", "toutiao"],
        source_materials=source_materials,
        promotion_goal=promotion_goal,
        search_enabled=search_enabled,
        trace_id=trace_id,
        idempotency_key=make_idempotency_key(article["id"], "writing.create", retry_count),
    )
    task_id = task.get("task_id") or task.get("id", "")
    if not task_id:
        raise RuntimeError(f"Writing did not return task_id: {task}")

    await client.run_task(
        task_id,
        trace_id=trace_id,
        idempotency_key=make_idempotency_key(article["id"], "writing.run", retry_count),
    )

    await db.execute(
        "UPDATE article SET writing_task_id = ?, updated_at = ? WHERE id = ?",
        (task_id, _now(), article["id"]),
    )
    await sm.transition_article(db, article["id"], "writing", "auto",
                                from_state="matched")


async def step_poll_writing(db: aiosqlite.Connection, article: dict) -> bool:
    """Poll writing task status. Returns True if task completed/terminated.

    Only 'failed' status from writing module transitions to orchestrator failed.
    needs_material / needs_config / needs_human are intermediate states —
    the writing module's own supervisor will retry. We stay in 'writing'
    and store the task detail for the frontend to display progress.
    """
    config = _load_config()
    task_id = article.get("writing_task_id", "")
    if not task_id:
        return False

    client = WritingClient(config["services"]["writing_url"])
    try:
        task_obj = await client.get_task(task_id, trace_id=article.get("trace_id") or "")
    except httpx.HTTPStatusError:
        return False

    status = task_obj.get("status", "")
    current_round = task_obj.get("currentRound", task_obj.get("current_round", 0))
    outputs = task_obj.get("outputs", [])
    score_reports = task_obj.get("scoreReports", task_obj.get("score_reports", []))

    # Store live task summary for frontend progress display
    task_summary = json.dumps({
        "writing_status": status,
        "current_round": current_round,
        "output_count": len(outputs),
        "last_outputs": [
            {"agentId": o.get("agentId", o.get("agent_id", "")),
             "stage": o.get("stage", ""),
             "status": o.get("status", ""),
             "round": o.get("round", 0)}
            for o in outputs[-6:]
        ],
        "score_reports": [
            {"round": sr.get("round", 0), "totalScore": sr.get("totalScore", 0),
             "passed": sr.get("passed", False)}
            for sr in score_reports[-3:]
        ],
        "error": task_obj.get("error", ""),
    }, ensure_ascii=False)

    if status in ("completed", "approved"):
        final_package = task_obj.get("final_package", task_obj.get("finalPackage", {})) or {}

        # Catch malformed final_package early — fail the article in
        # writing→failed with a readable error, instead of letting it
        # crash later inside the publish step.
        issues = fp_validate.validate_final_package(final_package)
        if issues:
            err = "writing returned invalid final_package: " + "; ".join(issues[:3])
            await db.execute(
                "UPDATE article SET writing_task_detail = ?, updated_at = ? WHERE id = ?",
                (task_summary, _now(), article["id"]),
            )
            await _fail_with_retry(db, article["id"], from_state="writing", error=err)
            return True

        # PRD §6 / HLD ADR-3: download OSS images to local immediately, so
        # the publish phase only ever reads local paths (24h OSS expiry).
        try:
            final_package = await assets_mod.localize_final_package(
                db, article["id"], final_package,
            )
        except Exception as e:  # noqa: BLE001 — never block the pipeline on asset failure
            logger.warning("Asset localization failed for %s: %s", article["id"], e)
        await db.execute(
            "UPDATE article SET final_package = ?, last_error_message = NULL, writing_task_detail = ?, updated_at = ? WHERE id = ?",
            (json.dumps(final_package, ensure_ascii=False), task_summary, _now(), article["id"]),
        )
        await sm.transition_article(db, article["id"], "drafted", "auto",
                                    from_state="writing")
        return True
    elif status == "failed":
        await db.execute(
            "UPDATE article SET writing_task_detail = ?, updated_at = ? WHERE id = ?",
            (task_summary, _now(), article["id"]),
        )
        await _fail_with_retry(
            db, article["id"], from_state="writing",
            error=f"Writing 任务失败: {task_obj.get('error', '')}",
        )
        return True
    elif status == "discarded":
        await db.execute(
            "UPDATE article SET writing_task_detail = ?, last_error_message = ?, "
            "updated_at = ? WHERE id = ?",
            (task_summary, "人工放弃，归档", _now(), article["id"]),
        )
        await sm.transition_article(db, article["id"], "rejected", "manual",
                                    from_state="writing")
        return True
    else:
        # running / needs_material / needs_config / needs_human / draft / needs_material
        # Stay in 'writing', update detail for frontend visibility
        # ── Stuck-task detection ──────────────────────────────
        # If the task has been "running" (or "needs_material") for more than
        # WRITING_TASK_STUCK_TIMEOUT_SECONDS without making progress, it likely
        # means the writing module's in-flight promise was lost during a restart.
        # Auto-fail to trigger the retry mechanism.
        if status in ("running", "needs_material"):
            task_updated = task_obj.get("updatedAt") or task_obj.get("updated_at", "")
            if task_updated:
                try:
                    if isinstance(task_updated, str) and "T" in task_updated:
                        task_updated_dt = datetime.fromisoformat(task_updated.replace("Z", "+00:00"))
                    else:
                        task_updated_dt = datetime.fromisoformat(str(task_updated))
                    age_seconds = (datetime.now(timezone.utc) - task_updated_dt).total_seconds()
                    if age_seconds > WRITING_TASK_STUCK_TIMEOUT_SECONDS:
                        logger.warning(
                            "Writing task %s stuck in '%s' for %ds (>%ds); auto-failing for retry.",
                            task_id, status, age_seconds, WRITING_TASK_STUCK_TIMEOUT_SECONDS,
                        )
                        await _fail_with_retry(
                            db, article["id"], from_state="writing",
                            error=f"写作任务在 '{status}' 状态卡住超过 {age_seconds//60:.0f} 分钟，自动重试。",
                        )
                        return True
                except (ValueError, TypeError) as e:
                    logger.warning("Could not parse task updatedAt '%s': %s", task_updated, e)

        detail_msg = _writing_status_message(status)
        await db.execute(
            "UPDATE article SET last_error_message = ?, writing_task_detail = ?, updated_at = ? WHERE id = ?",
            (detail_msg, task_summary, _now(), article["id"]),
        )
    return False


def _topic_source_materials(topic: dict) -> list[dict]:
    """Build source_materials from the topic row so writing never starves on
    `needs_material` when web search fails. Includes brief, raw_material and
    the source URL — whichever the upstream select_topic stage filled in.
    """
    materials: list[dict] = []
    brief = (topic.get("brief") or "").strip()
    raw = (topic.get("raw_material") or "").strip()
    if brief:
        materials.append({
            "id": "topic-brief",
            "title": f"{topic.get('title','')} · 选题简述",
            "content": brief,
            "url": topic.get("source_url") or "",
        })
    if raw and raw != brief:
        materials.append({
            "id": "topic-raw",
            "title": f"{topic.get('title','')} · 原始素材",
            "content": raw,
            "url": topic.get("source_url") or "",
        })
    return materials


def _writing_status_message(status: str) -> str:
    """Human-readable message for writing intermediate states."""
    return {
        "draft": "写作任务排队中，等待执行...",
        "running": "写作 Agent 集群工作中...",
        "needs_material": "吴查查 Agent 正在核查素材真实性，可能需要联网搜索...",
        "needs_config": "写作模块缺少 LLM 配置，请检查 writing/.env",
        "needs_human": "写作审阅中，等待人工确认...",
    }.get(status, f"写作中 ({status})")


async def step_drafted_to_scored(db: aiosqlite.Connection, article: dict) -> None:
    """drafted → scored: call platform_scorer (mock or real)."""
    config = _load_config()
    article_id = article["id"]
    topic = await crud.get_topic(article["topic_id"])
    topic_brief = topic.get("brief", topic.get("title", "")) if topic else ""

    client = ScorerClient(config["services"]["platform_scorer_url"])
    score_data = await client.score(
        article_id=article_id,
        topic_brief=topic_brief,
        platforms=["wechat", "xiaohongshu", "toutiao"],
        package_summary={"platforms": []},
        trace_id=article.get("trace_id") or "",
        idempotency_key=make_idempotency_key(
            article_id, "score", int(article.get("retry_count", 0))
        ),
    )

    # Determine next generation number so retries don't collide with existing scores.
    existing_scores = await crud.get_scores_for_article(article_id)
    next_gen = max((s.get("generation_n", 0) for s in existing_scores), default=0) + 1

    scores = score_data.get("scores", {})
    for platform, s in scores.items():
        await crud.create_score(
            article_id=article_id,
            platform=platform,
            score_val=s.get("score", 0),
            reason=s.get("reason", ""),
            generation_n=next_gen,
            conn=db,
        )

    await sm.transition_article(db, article_id, "scored", "auto",
                                from_state="drafted")


async def step_scored_to_reviewing(db: aiosqlite.Connection, article_id: str) -> None:
    """scored → reviewing: set review deadline to now + 2h (M2 auto-approves immediately)."""
    from datetime import timedelta
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    await db.execute(
        "UPDATE article SET review_deadline_at = ?, updated_at = ? WHERE id = ?",
        (deadline, _now(), article_id),
    )
    await sm.transition_article(db, article_id, "reviewing", "auto",
                                from_state="scored")


async def step_reviewing_to_publishing(db: aiosqlite.Connection, article_id: str) -> None:
    """reviewing → publishing: M2 auto-approves (no human review yet)."""
    await sm.transition_article(db, article_id, "publishing", "auto",
                                from_state="reviewing",
                                payload={"note": "M2 auto-approve"})


# Orchestrator/scorer use "wechat" everywhere; Autopublish wants "wechat_official".
# Only this mapping crosses the boundary — keep it next to the code that does.
_SCORER_TO_AUTOPUBLISH = {
    "wechat": "wechat_official",
    "xiaohongshu": "xiaohongshu",
    "toutiao": "toutiao",
}
_AUTOPUBLISH_TO_SCORER = {v: k for k, v in _SCORER_TO_AUTOPUBLISH.items()}


def _decide_publish_platforms(scores: list[dict]) -> list[str]:
    """Use dispatch threshold rules to pick platforms (orchestrator naming)."""
    chosen = dispatch.decide_platforms(scores)
    # Stable order so DB/UI consistently shows wechat → xhs → toutiao.
    return [p for p in ("wechat", "xiaohongshu", "toutiao") if p in chosen]


async def _download_url_to_tmp(url: str) -> str:
    """Download an HTTP URL to a temp file using async httpx. Returns local path, '' on failure."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            sfx = ".jpg"
            if "png" in ct: sfx = ".png"
            elif "webp" in ct: sfx = ".webp"
            elif "gif" in ct: sfx = ".gif"
            fd, tmp = tempfile.mkstemp(suffix=sfx)
            with os.fdopen(fd, "wb") as f:
                f.write(r.content)
            return tmp
    except Exception as e:
        logger.warning("Failed to download %s: %s", url, e)
        return ""


async def _per_platform_payload(
    article: dict,
    final_pkg: dict,
    platform: str,
    topic_title: str,
    config: dict,
) -> dict | None:
    """Pull the platform-specific package out of final_package and build
    the JSON body the Autopublish /api/publish endpoint expects.

    Returns None if the package has no entry for this platform.
    """
    pkg_platforms = final_pkg.get("platforms", []) or []
    pp = next((p for p in pkg_platforms if p.get("platform") == platform), None)
    if pp is None:
        return None

    titles = pp.get("titles", []) or []
    title = titles[0] if titles else topic_title
    body = pp.get("formatted_article") or pp.get("formattedArticle") or ""
    summary = pp.get("summary", "")
    tags = pp.get("tags", []) or []
    keywords = pp.get("keywords", []) or []

    cover_path = pp.get("coverPath") or pp.get("cover_path") or ""

    # Download cover image from HTTP URL to temp file if not already local.
    # Uses async httpx to avoid blocking the event loop.
    if cover_path and (cover_path.startswith("http://") or cover_path.startswith("https://")):
        cover_path = await _download_url_to_tmp(cover_path)

    image_paths: list[str] = []
    for img in pp.get("images", []) or []:
        if not isinstance(img, dict):
            continue
        lp = img.get("localPath") or img.get("local_path") or ""
        if not lp:
            url = img.get("url", "")
            if url and (url.startswith("http://") or url.startswith("https://")):
                lp = await _download_url_to_tmp(url)
        if lp and lp != cover_path:
            image_paths.append(lp)

    # Fallback: extract first image URL from Markdown body as cover.
    if not cover_path and body:
        import re as _re
        m = _re.search(r'!\[([^\]]*)\]\(([^)]+)\)', body)
        if m:
            url = m.group(2)
            if url and not url.startswith("prompt://") and (url.startswith("http://") or url.startswith("https://")):
                cover_path = await _download_url_to_tmp(url)
                if cover_path:
                    logger.info("Extracted cover image from body: %s → %s", url, cover_path)

    publishing_cfg = config.get("publishing", {})
    return {
        "article_id": article["id"],
        # Autopublish takes a `platforms` list, not singular `platform`.
        "platforms": [_SCORER_TO_AUTOPUBLISH[platform]],
        "title": title,
        "body": body,
        "summary": summary,
        "tags": tags,
        "keywords": keywords,
        "author": publishing_cfg.get("author", ""),
        "location": publishing_cfg.get("location", ""),
        "account_label": publishing_cfg.get("account_label", ""),
        "topic_title": topic_title,
        "cover_path": cover_path,
        "image_paths": image_paths,
        "pinned_comment": pp.get("pinnedComment") or pp.get("pinned_comment") or "",
        "publisher_type": "playwright",
    }


async def _await_autopublish(
    client: AutopublishClient,
    task_id: str,
    *,
    trace_id: str = "",
    timeout_s: float = 600.0,
    interval_s: float = 2.0,
) -> dict:
    """Poll /api/publish/progress/{task_id} until done=True or timeout.

    Returns the final progress payload (always a dict). On timeout the
    returned dict has {"done": False, "error": "polling_timeout"}.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    last: dict = {"done": False, "status": "starting"}
    while loop.time() < deadline:
        try:
            payload = await client.get_progress(task_id, trace_id=trace_id)
            if isinstance(payload, dict):
                last = payload
                if payload.get("done"):
                    return payload
        except Exception as e:  # noqa: BLE001 — single poll failure is non-fatal
            last = {"done": False, "error": str(e)}
        await asyncio.sleep(interval_s)
    return {"done": False, "error": "polling_timeout", "last": last}


def _extract_platform_result(progress: dict, autopublish_platform: str) -> dict:
    """Pluck the per-platform result out of the PublishOutput.to_dict()
    that Autopublish stores in progress.result.

    Returns {"status": ..., "platform_url": ..., "platform_msg_id": ...,
    "error_message": ...}. Falls back to a synthetic failure if not found.
    """
    err = progress.get("error")
    if err:
        return {"status": "failed", "error_message": err}

    result = progress.get("result") or {}
    plans = result.get("plans", []) or []
    for plan in plans:
        if plan.get("platform") == autopublish_platform:
            r = plan.get("result", {}) or {}
            return {
                "status": r.get("status", "failed"),
                "platform_url": r.get("platform_url", "") or "",
                "platform_msg_id": r.get("platform_msg_id", "") or "",
                "error_message": r.get("error_message", "") or "",
            }
    return {"status": "failed", "error_message": "no plan returned by autopublish"}


async def step_publishing_to_published(
    db: aiosqlite.Connection,
    article: dict,
    forced_platforms: list[str] | None = None,
) -> bool:
    """publishing → published.

    1. Pick the list of platforms whose latest score ≥ publish threshold
       (dispatch.decide_platforms). When `forced_platforms` is supplied
       (e.g. by the 23:00 boost), it overrides the threshold check.
    2. For each platform, call Autopublish with a complete payload
       (cover/images/tags/account_label).
    3. Poll the progress endpoint until done.
    4. Mark publish row per platform.
    5. Article succeeds if ≥1 platform succeeded.
    """
    config = _load_config()
    pub_url = config["services"]["autopublish_url"]

    article_id = article["id"]
    topic = await crud.get_topic(article["topic_id"])
    topic_title = topic["title"] if topic else "(无标题)"

    final_pkg_raw = article.get("final_package")
    if isinstance(final_pkg_raw, str):
        final_pkg = json.loads(final_pkg_raw) if final_pkg_raw else {}
    else:
        final_pkg = final_pkg_raw or {}

    if forced_platforms:
        target_platforms = [p for p in forced_platforms if p in _SCORER_TO_AUTOPUBLISH]
    else:
        scores = await crud.get_latest_scores_for_article(article_id)
        target_platforms = _decide_publish_platforms(scores)
    if not target_platforms:
        # No platform scored high enough. PRD §5 says boost step handles
        # this case at 23:00; here we just fail the article so retry/boost
        # logic can pick it up.
        logger.info("Article %s has no platform ≥ threshold; deferring to boost", article_id)
        await _fail_with_retry(
            db, article_id, from_state="publishing",
            error="no platform met publish threshold",
        )
        return False

    any_success = False
    last_error = ""
    trace_id = article.get("trace_id") or ""
    retry_count = int(article.get("retry_count", 0))
    ap_client = AutopublishClient(pub_url)

    for platform in target_platforms:
        payload = await _per_platform_payload(article, final_pkg, platform, topic_title, config)
        if payload is None:
            logger.warning("final_package missing entry for platform=%s; skipping", platform)
            continue

        # Idempotent publish row: the (article_id, platform) UNIQUE
        # constraint blew up retries before this guard. Reuse an existing
        # row if any: success → skip the platform; otherwise reset to
        # pending and retry through it.
        cursor = await db.execute(
            "SELECT id, status FROM publish WHERE article_id = ? AND platform = ?",
            (article_id, platform),
        )
        existing = await cursor.fetchone()
        if existing and existing["status"] == "success":
            logger.info(
                "publish already success for %s/%s; skipping", article_id, platform,
            )
            any_success = True
            continue
        if existing:
            publish_id = existing["id"]
            await db.execute(
                "UPDATE publish SET status = 'pending', error_code = NULL, "
                "error_message = NULL, executed_at = NULL, duration_ms = NULL, "
                "scheduled_at = ?, trace_id = ? WHERE id = ?",
                (_now(), trace_id, publish_id),
            )
        else:
            # Insert directly: crud.create_publish re-reads via get_publish on a
            # fresh connection, which can't see our uncommitted INSERT in WAL
            # mode and returns None, blowing up `["id"]` below.
            publish_id = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO publish (id, article_id, platform, status, scheduled_at, trace_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (publish_id, article_id, platform, "pending", _now(), trace_id),
            )
        start_ts = datetime.now(timezone.utc)

        try:
            async with httpx.AsyncClient(timeout=30) as raw:
                # Autopublish returns task_id immediately; we then poll
                # /api/publish/progress until done=True.
                idem = make_idempotency_key(article_id, f"publish.{platform}", retry_count)
                start_resp = await raw.post(
                    f"{pub_url}/api/publish",
                    json=payload,
                    headers={
                        "X-Trace-Id": trace_id,
                        "Idempotency-Key": idem,
                        "User-Agent": "orchestrator/1.0",
                    },
                )
                if start_resp.status_code >= 400:
                    raise RuntimeError(
                        f"autopublish HTTP {start_resp.status_code}: {start_resp.text[:200]}"
                    )
                start_body = start_resp.json()
                task_id = start_body.get("task_id", "")
            if not task_id:
                raise RuntimeError(f"autopublish did not return task_id: {start_body}")

            progress = await _await_autopublish(ap_client, task_id, trace_id=trace_id)
            ap_platform = _SCORER_TO_AUTOPUBLISH[platform]
            outcome = _extract_platform_result(progress, ap_platform)

            duration_ms = int((datetime.now(timezone.utc) - start_ts).total_seconds() * 1000)
            if outcome["status"] == "success":
                any_success = True
                await crud.update_publish(
                    publish_id,
                    conn=db,
                    status="success",
                    platform_url=outcome.get("platform_url", ""),
                    platform_msg_id=outcome.get("platform_msg_id", ""),
                    executed_at=_now(),
                    duration_ms=duration_ms,
                )
            else:
                last_error = outcome.get("error_message", "") or "unknown failure"
                await crud.update_publish(
                    publish_id, conn=db, status="failed",
                    error_message=last_error,
                    executed_at=_now(),
                    duration_ms=duration_ms,
                )
        except Exception as e:  # noqa: BLE001
            logger.error("Publish failed for %s on %s: %s", article_id, platform, e)
            last_error = str(e)
            await crud.update_publish(
                publish_id, conn=db, status="failed",
                error_message=last_error, executed_at=_now(),
            )

    if any_success:
        await sm.transition_article(db, article_id, "published", "auto",
                                    from_state="publishing")
        return True

    await _fail_with_retry(
        db, article_id, from_state="publishing",
        error=last_error or "all_platforms_failed",
    )
    return False


# ── Main loop ────────────────────────────────────────────────

async def process_one_article(db: aiosqlite.Connection, article: dict) -> str:
    """Advance one article one step. Returns new status."""
    status = article["status"]

    handlers = {
        "collected":  step_collected_to_matched,
        "matched":    step_matched_to_writing,
        "writing":    step_poll_writing,
        "drafted":    step_drafted_to_scored,
        "scored":     step_scored_to_reviewing,
        "reviewing":  step_reviewing_to_publishing,
        "publishing": step_publishing_to_published,
    }

    handler = handlers.get(status)
    if handler is None:
        return status

    # Handlers that need the full article row (final_package, writing_task_id, etc.)
    if status in ("matched", "writing", "drafted", "publishing"):
        await handler(db, article)
    else:
        await handler(db, article["id"])

    # Refresh article to get new status
    cursor = await db.execute("SELECT status FROM article WHERE id = ?", (article["id"],))
    row = await cursor.fetchone()
    return row["status"] if row else status


async def run_boost_publish() -> dict:
    """PRD §5 23:00 routine. For every platform with 0 publishes today,
    find the highest-scored eligible article (score ≥ boost_min_score,
    status in scored/reviewing) and force-publish it to that single
    platform regardless of the normal ≥70 threshold.

    Returns the per-platform decision: `boosted` (with publish outcome),
    `skipped` (already has count today), `no_candidate` (none eligible).
    """
    conn = await crud.get_db()
    try:
        today_counts = await dispatch.get_today_published_counts(conn)
        platforms = ("wechat", "xiaohongshu", "toutiao")
        outcome: dict[str, Any] = {"boosted": {}, "skipped": {}, "no_candidate": []}

        for platform in platforms:
            if today_counts.get(platform, 0) > 0:
                outcome["skipped"][platform] = today_counts[platform]
                continue
            candidates = await dispatch.find_boost_candidates(conn, platform)
            if not candidates:
                outcome["no_candidate"].append(platform)
                continue

            best = candidates[0]
            article_id = best["id"]
            article_row = await crud.get_article(article_id)
            if not article_row:
                continue

            # Boost is only legal for scored/reviewing (per find_boost_candidates).
            # Transition to publishing first so the state machine remains coherent.
            try:
                await sm.transition_article(
                    conn, article_id, "publishing", "cron",
                    actor="boost_23h",
                    payload={"platform": platform, "score": best.get("score")},
                )
                await conn.commit()
            except Exception as e:  # noqa: BLE001
                logger.warning("Boost transition for %s skipped: %s", article_id, e)
                outcome["no_candidate"].append(platform)
                continue

            # Reload the article to pick up the new state + any final_package.
            refreshed = await crud.get_article(article_id) or article_row
            ok = await step_publishing_to_published(
                conn, refreshed, forced_platforms=[platform],
            )
            outcome["boosted"][platform] = {
                "article_id": article_id,
                "score": best.get("score"),
                "success": ok,
            }
        await conn.commit()
        return outcome
    finally:
        await conn.close()


async def process_due_retries() -> list[dict]:
    """Move failed articles whose next_retry_at has passed back to the
    state they were in before the failure, so the next tick picks them up.

    Reads the pre-failure state from the latest audit_log entry where
    to_state='failed'. If none is found (unexpected), the article stays
    in `failed` for human review.
    """
    due = await retry_mod.find_due_retries()
    if not due:
        return []

    results: list[dict] = []
    conn = await crud.get_db()
    try:
        for entry in due:
            article_id = entry["id"]
            prev = await retry_mod.latest_pre_failure_state(article_id)
            if not prev:
                logger.warning("No pre-failure state for %s; leaving failed", article_id)
                continue
            try:
                await sm.transition_article(
                    conn, article_id, prev, "retry",
                    from_state="failed",
                    payload={"retry_count": entry["retry_count"], "back_to": prev},
                )
                await conn.execute(
                    "UPDATE article SET next_retry_at = NULL, updated_at = ? WHERE id = ?",
                    (_now(), article_id),
                )
                results.append({"article_id": article_id, "back_to": prev,
                                "retry_count": entry["retry_count"]})
            except Exception as e:  # noqa: BLE001
                logger.error("Retry transition failed for %s → %s: %s", article_id, prev, e)
        await conn.commit()
    finally:
        await conn.close()
    return results


async def tick() -> list[dict]:
    """One scheduler tick: advance all non-terminal articles by one step."""
    conn = await crud.get_db()
    try:
        cursor = await conn.execute(
            "SELECT * FROM article WHERE status NOT IN ('published','rejected','duplicated','failed')"
        )
        rows = await cursor.fetchall()
        articles = [dict(r) for r in rows]

        results = []
        for art in articles:
            try:
                new_status = await process_one_article(conn, art)
                results.append({"article_id": art["id"], "from": art["status"],
                                "to": new_status})
            except Exception as e:
                logger.exception("Tick failed for article %s (status=%s): %s",
                                 art["id"], art["status"], e)
                try:
                    await _fail_with_retry(conn, art["id"],
                                           from_state=art["status"], error=str(e))
                except Exception:
                    pass
                results.append({"article_id": art["id"], "from": art["status"],
                                "to": "failed", "error": str(e)})

        await conn.commit()
        return results
    finally:
        await conn.close()


# ── Topic sync from select_topic ──────────────────────────────

async def trigger_select_topic_collection() -> dict:
    """Trigger the select_topic module to run a collection cycle."""
    config = _load_config()
    select_url = config["services"]["select_topic_url"]
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{select_url}/api/collect/trigger")
        if r.status_code >= 400:
            raise RuntimeError(f"Collection trigger failed: {r.status_code} {r.text}")
        return r.json()


async def get_select_topic_status() -> dict:
    """Get select_topic collection scheduler status."""
    config = _load_config()
    select_url = config["services"]["select_topic_url"]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{select_url}/api/collect/status")
        return r.json() if r.status_code < 500 else {"enabled": False}


async def sync_topics_from_select_topic(min_score: float = 80) -> list[dict]:
    """Pull high-scoring topics from select_topic and create articles in pipeline.

    For each new topic:
      1. Create topic row in orchestrator DB (source='auto')
      2. Create article row (status='matched')
      3. Optionally kick off first tick

    Returns list of synced topic dicts.
    """
    config = _load_config()
    select_url = config["services"]["select_topic_url"]

    # Fetch matched topics with score >= threshold
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{select_url}/api/topics", params={
            "status": "matched",
            "min_score": min_score,
            "source_type": "auto",
            "limit": 50,
        })
        if r.status_code >= 400:
            raise RuntimeError(f"Failed to fetch topics from select_topic: {r.status_code}")
        select_topics = r.json()

    if not select_topics:
        logger.info("No new topics from select_topic (score >= %s)", min_score)
        return []

    conn = await crud.get_db()
    synced = []

    try:
        # Get existing normalized titles for dedup (consistent with L1 dedup).
        cursor = await conn.execute("SELECT title_normalized FROM topic")
        existing_normalized = {row["title_normalized"] for row in await cursor.fetchall()}

        for st in select_topics:
            title = st.get("title", "").strip()
            title_normalized = crud._normalize_title(title)
            if not title or title_normalized in existing_normalized:
                continue

            source_url = st.get("source_url", "")
            raw_content = st.get("raw_content", "")
            source_platform = st.get("source_platform", "")
            brief = f"[{source_platform}] {raw_content[:200]}" if raw_content else ""

            # Create topic + article at `collected`, then audit-log the
            # entry and let the scheduler advance them through the state
            # machine (so dedup/match/writing all run with audit trails).
            tid = crud._uid()
            now = crud._now()
            trace_id = crud._uid()

            await conn.execute(
                """INSERT INTO topic (id, title, title_normalized, source, source_url,
                   brief, raw_material, entities, topic_keywords, status,
                   user_submitted, trace_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, title, title_normalized, "auto", source_url,
                 brief, raw_content, "[]", "[]", "collected",
                 0, trace_id, now, now),
            )

            aid = crud._uid()
            await conn.execute(
                """INSERT INTO article (id, topic_id, character_id, status,
                   retry_count, trace_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (aid, tid, "", "collected", 0, trace_id, now, now),
            )

            await conn.execute(
                """INSERT INTO audit_log
                   (entity_type, entity_id, from_state, to_state, trigger,
                    actor, payload_json, trace_id, at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("article", aid, None, "collected", "auto", "select_topic_sync",
                 json.dumps({"topic_id": tid, "source_platform": source_platform},
                            ensure_ascii=False),
                 trace_id, now),
            )

            existing_normalized.add(title_normalized)
            synced.append({"topic_id": tid, "article_id": aid, "title": title})
            logger.info("Synced topic from select_topic: %s", title[:50])

        await conn.commit()

        # Kick off one tick to advance newly synced articles
        if synced:
            await conn.commit()
            # Tick: advance collected → matched → writing etc.
            for item in synced:
                try:
                    art_cursor = await conn.execute(
                        "SELECT * FROM article WHERE id = ?", (item["article_id"],)
                    )
                    row = await art_cursor.fetchone()
                    if row:
                        art = dict(row)
                        await process_one_article(conn, art)
                except Exception as e:
                    logger.error("Initial tick failed for %s: %s", item["article_id"], e)
            await conn.commit()

    finally:
        await conn.close()

    return synced


# ── Config helper ────────────────────────────────────────────

_CACHED_CONFIG: tuple[float, dict] | None = None


def _load_config() -> dict:
    """Read shared_config.json with .env / ${VAR} substitution applied.
    Cached against the file's mtime so the scheduler doesn't re-read on
    every state advancement, but still picks up edits without a restart.
    """
    from config_loader import load_raw_config

    global _CACHED_CONFIG
    config_path = THIS_DIR.parent / "shared_config.json"
    mtime = config_path.stat().st_mtime
    if _CACHED_CONFIG is None or _CACHED_CONFIG[0] != mtime:
        _CACHED_CONFIG = (mtime, load_raw_config(config_path))
    return _CACHED_CONFIG[1]
