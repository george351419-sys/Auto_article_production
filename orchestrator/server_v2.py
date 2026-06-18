"""Orchestrator v2 API server for M2/M3/M4.

Provides:
  POST /api/topics                — user submits topic → creates article
  GET  /api/topics?status=        — list topics
  GET  /api/topics/{id}           — topic detail
  GET  /api/articles?status=      — list articles
  GET  /api/articles/{id}         — article detail (with scores, publishes)
  POST /api/articles/{id}/review  — approve/reject + modifications (M4)
  POST /api/articles/{id}/rescore — manual re-score (M4)
  POST /api/tick                  — advance all articles one step
  GET  /api/dashboard             — aggregate stats
  GET  /api/admin/services        — module health status
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import cleanup as cleanup_mod
import crud
import scheduler_v2 as sched

import state_machine as sm


THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("orchestrator_v2")


LOCAL_TZ = ZoneInfo("Asia/Shanghai")

# Allow disabling the in-process scheduler during tests / one-off scripts.
_DISABLE_BG = os.environ.get("ORCH_DISABLE_BG", "").lower() in ("1", "true", "yes")


def _build_background_scheduler() -> AsyncIOScheduler:
    """Wire all the recurring jobs that PRD/HLD describe.

    Each job has max_instances=1 + coalesce=True so a slow run doesn't
    stack on top of the next tick. Time-of-day jobs run in Asia/Shanghai
    so "23:00 boost" and "Sun 03:00 VACUUM" mean what the user expects.
    """
    s = AsyncIOScheduler(timezone=LOCAL_TZ)

    s.add_job(
        sched.tick, IntervalTrigger(seconds=10),
        id="pipeline_tick", max_instances=1, coalesce=True,
    )
    s.add_job(
        check_review_timeouts, IntervalTrigger(seconds=60),
        id="review_timeout", max_instances=1, coalesce=True,
    )
    s.add_job(
        sched.process_due_retries, IntervalTrigger(seconds=30),
        id="retry_scanner", max_instances=1, coalesce=True,
    )
    s.add_job(
        sched.run_boost_publish, CronTrigger(hour=23, minute=0, timezone=LOCAL_TZ),
        id="boost_23h", max_instances=1, coalesce=True,
    )
    s.add_job(
        cleanup_mod.run_sweep, CronTrigger(hour="*/3", minute=0, timezone=LOCAL_TZ),
        id="cleanup_sweep", max_instances=1, coalesce=True,
    )
    s.add_job(
        cleanup_mod.check_threshold_guard, IntervalTrigger(minutes=10),
        id="cleanup_guard", max_instances=1, coalesce=True,
    )
    return s


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Apply any pending DB migrations on boot. Failure is fatal — we
    #    refuse to serve traffic against a stale schema.
    from migrate import migrate
    try:
        applied = migrate(str(crud.DB_PATH))
        if applied:
            logger.info("Applied DB migrations: %s", applied)
    except Exception as e:  # noqa: BLE001
        logger.error("Migration failed on startup: %s", e)
        raise

    # 2. Spin up the background scheduler unless the env opts out.
    scheduler: AsyncIOScheduler | None = None
    if not _DISABLE_BG:
        scheduler = _build_background_scheduler()
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info(
            "Background scheduler started: %s",
            [j.id for j in scheduler.get_jobs()],
        )
    else:
        logger.info("Background scheduler disabled via ORCH_DISABLE_BG")

    logger.info("Orchestrator v2 ready on :8800")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("Background scheduler stopped")


app = FastAPI(title="内容生产流水线编排器 v2", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Static files
static_dir = THIS_DIR / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"ok": True, "version": "2.0", "name": "Auto Content Production"}


_BOOTED_AT = __import__("time").time()


@app.get("/health")
async def api_health():
    """LLD §3.2 contract — also lets /api/admin/services show the
    orchestrator itself as Up next to the business modules.
    """
    import time
    return {
        "ok": True,
        "module": "orchestrator",
        "version": "2.0",
        "uptime_seconds": int(time.time() - _BOOTED_AT),
        "deps_ok": True,
    }


@app.get("/contract")
async def api_contract():
    return {
        "module": "orchestrator",
        "contract_version": "1.0",
        "endpoints": [
            {"path": "/api/topics", "method": "GET",  "purpose": "list_topics"},
            {"path": "/api/topics", "method": "POST", "purpose": "create_topic"},
            {"path": "/api/articles", "method": "GET", "purpose": "list_articles"},
            {"path": "/api/articles/{id}", "method": "GET", "purpose": "get_article"},
            {"path": "/api/articles/{id}/review", "method": "POST", "purpose": "review"},
            {"path": "/api/articles/{id}/rescore", "method": "POST", "purpose": "rescore"},
            {"path": "/api/tick", "method": "POST", "purpose": "advance_tick"},
            {"path": "/api/dashboard", "method": "GET", "purpose": "stats"},
            {"path": "/api/admin/services", "method": "GET", "purpose": "module_health"},
            {"path": "/api/collect/trigger", "method": "POST", "purpose": "select_topic_collect"},
            {"path": "/api/collect/sync", "method": "POST", "purpose": "import_from_select_topic"},
        ],
    }


# ── Config ───────────────────────────────────────────────────

def _load_config() -> dict:
    """Defer to scheduler_v2._load_config so both modules share the same
    mtime-cached, env-interpolated config dict.
    """
    return sched._load_config()

def _service_urls() -> dict[str, str]:
    config = _load_config()
    svc = config["services"]
    return {
        "orchestrator": svc.get("orchestrator_url", "http://127.0.0.1:8800"),
        "distilled_characters": svc["distilled_characters_url"],
        "select_topic": svc["select_topic_url"],
        "writing": svc["writing_url"],
        "platform_scorer": svc["platform_scorer_url"],
        "autopublish": svc["autopublish_url"],
    }


# ── Topics ───────────────────────────────────────────────────

@app.get("/api/topics")
async def api_list_topics(
    status: str = "",
    source: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """List topics with optional filtering."""
    topics = await crud.list_topics(
        status=status if status else None,
        source=source if source else None,
        limit=limit,
        offset=offset,
    )
    return {"topics": topics, "total": len(topics)}


@app.get("/api/topics/{topic_id}")
async def api_get_topic(topic_id: str):
    topic = await crud.get_topic(topic_id)
    if not topic:
        raise HTTPException(404, "Topic not found")
    # Look up the article linked to this topic directly (list_articles only fetches
    # the most recent N articles globally and may miss the linked article).
    conn = await crud.get_db()
    try:
        cursor = await conn.execute(
            "SELECT * FROM article WHERE topic_id = ? ORDER BY created_at DESC LIMIT 1",
            (topic_id,),
        )
        row = await cursor.fetchone()
        topic["article"] = crud._row_to_dict(row) if row else None
    finally:
        await conn.close()
    return topic


@app.post("/api/topics")
async def api_create_topic(body: dict):
    """User submits a topic. Creates topic + article in `collected` state and
    records the initial audit_log entry. Advancement is left to the
    scheduler tick (do NOT block the request on the writing pipeline).
    """
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    brief = body.get("brief", "")
    source_url = body.get("source_url", "")

    topic = await crud.create_topic(
        title=title,
        source="user",
        brief=brief,
        source_url=source_url,
        user_submitted=1,
    )
    article = await crud.create_article(
        topic_id=topic["id"],
        character_id="",
        status="collected",
        trace_id=topic.get("trace_id"),
    )
    await crud.write_audit_entry(
        "article", article["id"], "collected",
        from_state=None, trigger="user", actor="user",
        trace_id=article.get("trace_id", ""),
        payload={"source": "user_submit", "topic_id": topic["id"]},
    )

    # Fire-and-forget the first tick so the request returns promptly;
    # the background scheduler (or subsequent /api/tick calls) will
    # continue advancing the article.
    asyncio.create_task(_safe_initial_tick(article["id"]))

    return {"topic": topic, "article": article}


async def _safe_initial_tick(article_id: str) -> None:
    """Run one tick so the user sees movement immediately after submitting.
    Errors are logged; we never let this kill the request handler.
    """
    try:
        await sched.tick()
    except Exception as e:  # noqa: BLE001
        logger.warning("Initial tick for %s warning: %s", article_id, e)


# ── Article list / detail ────────────────────────────────────

@app.get("/api/articles")
async def api_list_articles(status: str = "", limit: int = 50, offset: int = 0):
    articles = await crud.list_articles(
        status=status if status else None,
        limit=limit,
        offset=offset,
    )
    for a in articles:
        topic = await crud.get_topic(a["topic_id"])
        a["topic_title"] = topic["title"] if topic else ""
    return {"articles": articles, "total": len(articles)}


@app.get("/api/articles/{article_id}")
async def api_get_article(article_id: str):
    article = await crud.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    topic = await crud.get_topic(article["topic_id"])
    scores = await crud.get_latest_scores_for_article(article_id)
    publishes = await crud.get_publishes_for_article(article_id)

    return {
        "article": article,
        "topic": topic,
        "scores": scores,
        "publishes": publishes,
    }


# ── Review (M4) ──────────────────────────────────────────────

@app.post("/api/articles/{article_id}/review")
async def api_review_article(article_id: str, body: dict):
    """Approve, reject, or save modifications to a reviewing article.

    body: { "action": "approve"|"reject", "modifications": {...} }
    """
    action = body.get("action", "")
    modifications = body.get("modifications", body.get("changes", {}))

    article = await crud.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    if article["status"] != "reviewing":
        raise HTTPException(400, f"Article not in reviewing (status={article['status']})")

    conn = await crud.get_db()
    try:
        if action == "approve":
            # Save any modifications to final_package before publishing
            if modifications:
                fp = json.loads(article.get("final_package", "{}")) if isinstance(article.get("final_package"), str) else (article.get("final_package") or {})
                _apply_modifications(fp, modifications)
                await conn.execute(
                    "UPDATE article SET final_package = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(fp, ensure_ascii=False), crud._now(), article_id),
                )
            await sm.transition_article(conn, article_id, "publishing", "user", actor="reviewer",
                                        payload={"action": "approve"})

        elif action == "reject":
            await sm.transition_article(conn, article_id, "rejected", "user", actor="reviewer",
                                        payload={"action": "reject"})

        elif action == "save":
            # Save modifications without changing state
            if modifications:
                fp = json.loads(article.get("final_package", "{}")) if isinstance(article.get("final_package"), str) else (article.get("final_package") or {})
                _apply_modifications(fp, modifications)
                await conn.execute(
                    "UPDATE article SET final_package = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(fp, ensure_ascii=False), crud._now(), article_id),
                )
            return {"ok": True, "action": "saved"}

        else:
            raise HTTPException(400, f"Invalid action: {action}. Use approve/reject/save")

        await conn.commit()
    finally:
        await conn.close()

    return {"ok": True, "action": action}


@app.post("/api/articles/{article_id}/rescore")
async def api_rescore_article(article_id: str):
    """Manually trigger re-scoring. Creates generation_n+1 score records."""
    article = await crud.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    # Get latest generation_n
    existing = await crud.get_scores_for_article(article_id)
    max_gen = max((s.get("generation_n", 1) for s in existing), default=1)
    new_gen = max_gen + 1

    # Call scorer
    config = _load_config()
    scorer_url = config["services"]["platform_scorer_url"]
    topic = await crud.get_topic(article["topic_id"])
    topic_brief = topic.get("brief", topic.get("title", "")) if topic else ""

    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{scorer_url}/api/score", json={
                "article_id": article_id,
                "topic_brief": topic_brief,
                "platforms": ["wechat", "xiaohongshu", "toutiao"],
                "package_summary": {"platforms": []},
            })
            score_data = r.json() if r.status_code < 500 else {"scores": {}}
    except Exception as e:
        raise HTTPException(502, f"Scorer unavailable: {e}")

    scores = score_data.get("scores", {})
    new_scores = []
    for platform, s in scores.items():
        sc = await crud.create_score(
            article_id=article_id,
            platform=platform,
            score_val=s.get("score", 0),
            reason=s.get("reason", ""),
            generation_n=new_gen,
        )
        new_scores.append(sc)

    return {
        "ok": True,
        "generation_n": new_gen,
        "scores": new_scores,
    }


def _apply_modifications(final_package: dict, modifications: dict) -> None:
    """Apply per-platform modifications to a final_package dict."""
    platforms = final_package.get("platforms", [])
    for mod in modifications.get("platforms", modifications.get("platform", [])):
        target_platform = mod.get("platform", "")
        for pp in platforms:
            if pp.get("platform") == target_platform:
                if "title" in mod and pp.get("titles"):
                    pp["titles"][0] = mod["title"]
                if "body" in mod:
                    pp["formatted_article"] = mod["body"]
                    pp["formattedArticle"] = mod["body"]
                if "tags" in mod:
                    pp["tags"] = mod["tags"]
                if "cover" in mod:
                    pp["cover_plan"] = mod["cover"]
                break


# ── Review timeout check (M4) ────────────────────────────────

async def check_review_timeouts() -> list[dict]:
    """Scan for reviewing articles past their deadline, auto-approve them.
    Called by scheduler every 60s.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    conn = await crud.get_db()
    results = []
    try:
        cursor = await conn.execute(
            "SELECT * FROM article WHERE status = 'reviewing' AND review_deadline_at <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        articles = [dict(r) for r in rows]

        for art in articles:
            try:
                await sm.transition_article(conn, art["id"], "publishing", "cron",
                                            actor="review_timeout",
                                            payload={"note": "2h auto-approve"})
                results.append({"article_id": art["id"], "action": "auto_approve"})
            except Exception as e:
                logger.error("Timeout transition failed for %s: %s", art["id"], e)
        await conn.commit()
    finally:
        await conn.close()
    return results


# ── Tick (advance state machine) ─────────────────────────────

@app.post("/api/tick")
async def api_tick():
    """Advance all non-terminal articles by one state transition."""
    results = await sched.tick()
    return {"ok": True, "advanced": len(results), "results": results}


# ── Dashboard ────────────────────────────────────────────────

@app.get("/api/dashboard")
async def api_dashboard():
    stats = await crud.get_dashboard_stats()
    # Add per-platform today counts (today in Asia/Shanghai).
    conn = await crud.get_db()
    try:
        today_local_start = crud.local_today_start_utc_iso()
        cursor = await conn.execute(
            "SELECT platform, COUNT(*) as cnt FROM publish "
            "WHERE status = 'success' AND executed_at >= ? GROUP BY platform",
            (today_local_start,),
        )
        rows = await cursor.fetchall()
        stats["platform_counts"] = {r["platform"]: r["cnt"] for r in rows}
    finally:
        await conn.close()
    return stats


# ── Service health ───────────────────────────────────────────

@app.get("/api/admin/services")
async def api_services():
    urls = _service_urls()
    results = {}
    for name, url in urls.items():
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{url}/health")
                data = r.json()
                results[name] = {
                    "status": "Up" if data.get("ok") else "Down",
                    "version": data.get("version", "?"),
                    "uptime_seconds": data.get("uptime_seconds", 0),
                    "last_error": None,
                }
        except Exception as e:
            results[name] = {
                "status": "Down",
                "version": "?",
                "uptime_seconds": 0,
                "last_error": str(e),
            }
    return {"services": results}


# ── Agent management (proxies to writing module) ───────────

@app.get("/api/admin/agents")
async def api_agents():
    """Return all writing sub-agents with their system prompts from the writing module."""
    urls = _service_urls()
    writing_url = urls.get("writing", "http://127.0.0.1:8788")
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{writing_url}/api/config")
            data = r.json()
            return {
                "agents": data.get("agents", {}),
                "platforms": data.get("platforms", {}),
                "config": data.get("config", {}),
            }
    except Exception as e:
        raise HTTPException(502, "Failed to fetch agents from writing module: " + str(e))


@app.put("/api/admin/agents/{agent_id}")
async def api_update_agent(agent_id: str, body: dict):
    """Update a writing sub-agent's system prompt."""
    system_prompt = body.get("systemPrompt")
    if not system_prompt or not isinstance(system_prompt, str) or not system_prompt.strip():
        raise HTTPException(400, "systemPrompt is required and must be a non-empty string")

    urls = _service_urls()
    writing_url = urls.get("writing", "http://127.0.0.1:8788")
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.put(
                f"{writing_url}/api/config/agents/{agent_id}",
                json={"systemPrompt": system_prompt},
            )
            if r.status_code != 200:
                err_data = r.json()
                detail = err_data.get("error", "HTTP " + str(r.status_code))
                raise HTTPException(r.status_code, "Writing module error: " + str(detail))
            data = r.json()
            return {"agent": data.get("agent", {})}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, "Failed to update agent in writing module: " + str(e))


# ── Settings ─────────────────────────────────────────────────

@app.get("/api/settings")
async def api_get_settings():
    conn = await crud.get_db()
    try:
        cursor = await conn.execute("SELECT key, value, updated_at FROM settings")
        rows = await cursor.fetchall()
        return {"settings": {r["key"]: r["value"] for r in rows}}
    finally:
        await conn.close()


@app.put("/api/settings/{key}")
async def api_update_setting(key: str, body: dict):
    value = body.get("value")
    if value is None:
        raise HTTPException(400, "value is required")
    now = crud._now()
    conn = await crud.get_db()
    try:
        await conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, str(value), now),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"key": key, "value": str(value)}


# ── Entry point ──────────────────────────────────────────────

@app.post("/api/collect/trigger")
async def api_trigger_collection():
    """Trigger select_topic to run a collection cycle, then sync new topics."""
    try:
        result = await sched.trigger_select_topic_collection()
        return {"ok": True, "collect_result": result}
    except Exception as e:
        msg = str(e)
        if "connect" in msg.lower() or "refused" in msg.lower() or "timeout" in msg.lower():
            raise HTTPException(503, f"select_topic 服务 (8766端口) 未启动或无法连接")
        raise HTTPException(502, f"Collection trigger failed: {e}")


@app.post("/api/collect/sync")
async def api_sync_topics(min_score: float = Query(80, ge=0, le=100)):
    """Sync high-scoring topics from select_topic into orchestrator pipeline."""
    try:
        synced = await sched.sync_topics_from_select_topic(min_score=min_score)
        return {"ok": True, "synced": len(synced), "topics": synced}
    except Exception as e:
        msg = str(e)
        if "connect" in msg.lower() or "refused" in msg.lower() or "timeout" in msg.lower():
            raise HTTPException(503, f"select_topic 服务 (8766端口) 未启动或无法连接")
        raise HTTPException(502, f"Sync failed: {e}")


@app.get("/api/collect/status")
async def api_collect_status():
    """Get select_topic collection scheduler status."""
    try:
        status = await sched.get_select_topic_status()
        return {"ok": True, "status": status}
    except Exception as e:
        raise HTTPException(502, f"Status check failed: {e}")


@app.get("/api/articles/{article_id}/writing-status")
async def api_get_article_writing_status(article_id: str):
    """Return the writing module task detail for an article in 'writing' state.

    Polls the writing module's GET /api/tasks/{task_id} and returns
    agent outputs, score reports, current round — so the frontend can
    show internal progress.
    """
    article = await crud.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")

    task_id = article.get("writing_task_id", "")
    if not task_id:
        return {"ok": True, "writing_task": None, "message": "No writing task assigned yet"}

    config = _load_config()
    writing_url = config["services"]["writing_url"]

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{writing_url}/api/tasks/{task_id}")
            if r.status_code >= 400:
                return {"ok": True, "writing_task": None, "message": f"Writing module returned {r.status_code}"}
            task_data = r.json()
            task_obj = task_data.get("task", task_data)
    except Exception as e:
        return {"ok": True, "writing_task": None, "message": f"Writing module unreachable: {e}"}

    # Also include stored detail from last poll
    stored_detail = None
    raw = article.get("writing_task_detail")
    if raw:
        try:
            stored_detail = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "ok": True,
        "writing_task": {
            "id": task_obj.get("id", task_obj.get("task_id", task_id)),
            "status": task_obj.get("status", ""),
            "current_round": task_obj.get("currentRound", task_obj.get("current_round", 0)),
            "outputs": task_obj.get("outputs", []),
            "score_reports": task_obj.get("scoreReports", task_obj.get("score_reports", [])),
            "feedback_records": task_obj.get("feedbackRecords", task_obj.get("feedback_records", [])),
            "final_package": task_obj.get("finalPackage", task_obj.get("final_package")),
            "error": task_obj.get("error", ""),
            "created_at": task_obj.get("createdAt", task_obj.get("created_at", "")),
        },
        "stored_detail": stored_detail,
        "writing_module_url": writing_url,
    }


_WRITING_ACTIONS = {"force-approve", "reset", "discard"}


# ── Account management — credentials (LLM keys) + accounts (cookies) ──
#
# Two backing stores:
#  • .env at project root — LLM API keys (DeepSeek / Qwen). Kept out of JSON
#    per CLAUDE.md / PRD §7.4.
#  • Autopublish/.data/accounts.json — per-platform cookie / WeChat
#    AppID+AppSecret. Owned by the autopublish module, edited via proxy
#    so the UI doesn't need cross-origin requests.

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_PATH = _PROJECT_ROOT / ".env"
_CREDENTIAL_KEYS = ("DEEPSEEK_API_KEY", "QWEN_API_KEY")


def _mask_secret(value: str) -> str:
    """Return `sk-…XXXX` so the UI can show 'present' without leaking."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def _read_dotenv() -> dict[str, str]:
    if not _DOTENV_PATH.is_file():
        return {}
    result: dict[str, str] = {}
    for line in _DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        result[k.strip()] = v
    return result


def _write_dotenv(updates: dict[str, str]) -> None:
    """Rewrite .env preserving comments and unknown keys; update or append
    the keys in `updates`. Empty values delete the key entirely."""
    existing_lines: list[str] = []
    if _DOTENV_PATH.is_file():
        existing_lines = _DOTENV_PATH.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            new_val = updates[key]
            if new_val == "":
                continue  # drop line
            out.append(f"{key}={new_val}")
        else:
            out.append(raw)
    for key, val in updates.items():
        if key in seen or val == "":
            continue
        out.append(f"{key}={val}")
    _DOTENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    # Refresh in-process env so a hot reload picks them up without restart.
    for key, val in updates.items():
        if val:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)
    sched._CACHED_CONFIG = None  # force re-load on next _load_config()


@app.get("/api/credentials")
async def api_get_credentials():
    """Read LLM API keys from .env — masked values only."""
    env = _read_dotenv()
    return {
        "items": [
            {
                "key": k,
                "label": {"DEEPSEEK_API_KEY": "DeepSeek API Key",
                          "QWEN_API_KEY": "Qwen / DashScope API Key"}.get(k, k),
                "masked": _mask_secret(env.get(k, "")),
                "configured": bool(env.get(k, "").strip()),
            }
            for k in _CREDENTIAL_KEYS
        ],
        "dotenv_path": str(_DOTENV_PATH),
    }


@app.put("/api/credentials")
async def api_put_credentials(body: dict):
    """Write LLM API keys to .env. Body: {DEEPSEEK_API_KEY: '...', ...}.
    Pass empty string to delete a key. Keys not in CREDENTIAL_KEYS rejected."""
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be an object")
    updates: dict[str, str] = {}
    for k, v in body.items():
        if k not in _CREDENTIAL_KEYS:
            raise HTTPException(400, f"Unknown credential key: {k}")
        if not isinstance(v, str):
            raise HTTPException(400, f"{k} must be a string")
        updates[k] = v.strip()
    if not updates:
        raise HTTPException(400, "No credential fields supplied")
    _write_dotenv(updates)
    return await api_get_credentials()


# ── Model config (text LLM + image gen) ──────────────────────

_WRITING_DOTENV = _PROJECT_ROOT / "writing" / ".env"
_SHARED_CONFIG_PATH = _PROJECT_ROOT / "shared_config.json"


def _read_dotenv_file(path: Path) -> dict[str, str]:
    """Generic .env reader — returns key→value dict (unquoted)."""
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        result[k.strip()] = v
    return result


def _write_dotenv_file(path: Path, updates: dict[str, str]) -> None:
    """Rewrite a .env file with updated keys, preserving all other lines."""
    existing_lines: list[str] = []
    if path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            new_val = updates[key]
            if new_val == "":
                continue
            out.append(f"{key}={new_val}")
        else:
            out.append(raw)
    for key, val in updates.items():
        if key in seen or val == "":
            continue
        out.append(f"{key}={val}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _read_shared_config_raw() -> dict:
    if not _SHARED_CONFIG_PATH.is_file():
        return {}
    try:
        return json.loads(_SHARED_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_shared_config_raw(cfg: dict) -> None:
    _SHARED_CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sched._CACHED_CONFIG = None


@app.get("/api/model-config")
async def api_get_model_config():
    """Return current text LLM and image generation model config."""
    text_env = _read_dotenv_file(_WRITING_DOTENV)
    raw_cfg = _read_shared_config_raw()
    img_cfg = raw_cfg.get("image_gen", {})
    return {
        "text": {
            "base_url": text_env.get("LLM_BASE_URL", ""),
            "model": text_env.get("LLM_MODEL", ""),
            "configured": bool(text_env.get("LLM_API_KEY", "").strip()),
            "masked_key": _mask_secret(text_env.get("LLM_API_KEY", "")),
        },
        "image": {
            "provider": img_cfg.get("provider", "wanx"),
            "model": img_cfg.get("model", ""),
            "configured": bool(img_cfg.get("api_key", "").strip()),
            "masked_key": _mask_secret(img_cfg.get("api_key", "")),
        },
    }


@app.put("/api/model-config")
async def api_put_model_config(body: dict):
    """Update text LLM or image gen model config.

    For text: body = {type:'text', base_url, model, api_key (optional)}
    For image: body = {type:'image', provider, model, api_key (optional)}
    """
    model_type = body.get("type")
    if model_type == "text":
        updates: dict[str, str] = {}
        if "base_url" in body and isinstance(body["base_url"], str):
            updates["LLM_BASE_URL"] = body["base_url"].strip()
        if "model" in body and isinstance(body["model"], str):
            updates["LLM_MODEL"] = body["model"].strip()
        if body.get("api_key") and isinstance(body["api_key"], str):
            updates["LLM_API_KEY"] = body["api_key"].strip()
        if not updates:
            raise HTTPException(400, "No fields to update")
        _write_dotenv_file(_WRITING_DOTENV, updates)
    elif model_type == "image":
        raw_cfg = _read_shared_config_raw()
        if "image_gen" not in raw_cfg:
            raw_cfg["image_gen"] = {}
        if "provider" in body and isinstance(body["provider"], str):
            raw_cfg["image_gen"]["provider"] = body["provider"].strip()
        if "model" in body and isinstance(body["model"], str):
            raw_cfg["image_gen"]["model"] = body["model"].strip()
        if body.get("api_key") and isinstance(body["api_key"], str):
            raw_cfg["image_gen"]["api_key"] = body["api_key"].strip()
        _write_shared_config_raw(raw_cfg)
    else:
        raise HTTPException(400, "type must be 'text' or 'image'")
    return await api_get_model_config()


# ── Accounts proxy ────────────────────────────────────────────

def _autopublish_url() -> str:
    return _load_config()["services"]["autopublish_url"].rstrip("/")


@app.get("/api/accounts")
async def api_get_accounts():
    """Proxy GET /api/accounts on autopublish module."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{_autopublish_url()}/api/accounts")
            r.raise_for_status()
            return r.json()
    except httpx.RequestError as e:
        raise HTTPException(502, f"Autopublish unreachable: {e}")


@app.post("/api/accounts")
async def api_save_account(body: dict):
    """Proxy POST /api/accounts — body keys: platform, account_name,
    cookie, mode (cookie|api), logged_in."""
    if not isinstance(body, dict) or "platform" not in body:
        raise HTTPException(400, "Missing 'platform'")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{_autopublish_url()}/api/accounts", json=body)
            if r.status_code >= 400:
                raise HTTPException(502, f"autopublish {r.status_code}: {r.text[:200]}")
            return r.json()
    except httpx.RequestError as e:
        raise HTTPException(502, f"Autopublish unreachable: {e}")


@app.delete("/api/accounts/{platform}")
async def api_delete_account(platform: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.delete(f"{_autopublish_url()}/api/accounts/{platform}")
            if r.status_code >= 400:
                raise HTTPException(502, f"autopublish {r.status_code}: {r.text[:200]}")
            return r.json()
    except httpx.RequestError as e:
        raise HTTPException(502, f"Autopublish unreachable: {e}")


@app.post("/api/accounts/verify")
async def api_verify_account(body: dict):
    """Quick check — does the autopublish module recognise the cookie/key as valid?"""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{_autopublish_url()}/api/accounts/verify", json=body)
            return r.json()
    except httpx.RequestError as e:
        raise HTTPException(502, f"Autopublish unreachable: {e}")


@app.post("/api/articles/{article_id}/writing/{action}")
async def api_writing_action(article_id: str, action: str):
    """Proxy manual operator actions to the writing module.

    `force-approve`: accept current outputs, run operator pass once, mark approved.
    `reset`: clear all rounds and rerun from scratch.
    `discard`: mark writing task as permanently discarded → article rejected.
    """
    if action not in _WRITING_ACTIONS:
        raise HTTPException(400, f"Unknown action: {action}")
    article = await crud.get_article(article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    task_id = article.get("writing_task_id", "")
    if not task_id:
        raise HTTPException(409, "Article has no writing task")
    config = _load_config()
    writing_url = config["services"]["writing_url"]
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{writing_url}/api/tasks/{task_id}/{action}", json={},
            )
            if r.status_code >= 400:
                raise HTTPException(
                    502, f"writing returned {r.status_code}: {r.text[:200]}",
                )
            body = r.json()
            return {"ok": True, "task": body.get("task", body)}
    except httpx.RequestError as e:
        raise HTTPException(502, f"Writing module unreachable: {e}")


if __name__ == "__main__":
    config = _load_config()
    port = config["services"].get("orchestrator_port", 8800)
    uvicorn.run(app, host="127.0.0.1", port=8800)
