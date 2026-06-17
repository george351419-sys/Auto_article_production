"""Collection API routes — trigger, status, URL import, logs."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from core.collector import fetch_url_content, distill_single_url
from core.models import URLImportRequest
from core.scoring_engine import score_topic
from core.matching_engine import match_celebrities_rule_based
from server.database import get_db
from config import load_config

logger = logging.getLogger("collect")
router = APIRouter(prefix="/collect", tags=["collect"])

# Scheduler reference — set by app startup
_scheduler_ref: dict = {"instance": None}


def set_scheduler(scheduler):
    _scheduler_ref["instance"] = scheduler


def _get_scheduler():
    return _scheduler_ref.get("instance")


@router.post("/trigger")
async def trigger_collection():
    """Manually trigger a full collection cycle."""
    scheduler = _get_scheduler()
    if not scheduler:
        raise HTTPException(503, "Scheduler not available")
    result = await scheduler.trigger_manual()
    return result


@router.get("/status")
async def collection_status():
    """Return scheduler status."""
    scheduler = _get_scheduler()
    if not scheduler:
        return {"enabled": False, "running": False, "last_run": None, "last_status": "not_configured"}
    return scheduler.status()


@router.post("/import-url")
async def import_from_url(body: URLImportRequest):
    """Import a topic from a URL: fetch → distill → create topic → score → match.

    The raw page HTML is fetched in memory, topic extracted via LLM,
    and immediately discarded — only the distilled topic is stored.
    """
    db = await get_db()

    # Step 1: Fetch URL content
    try:
        page_title, page_content = await fetch_url_content(body.url)
    except Exception as e:
        await db.close()
        raise HTTPException(400, f"Failed to fetch URL: {e}")

    # Step 2: Distill via LLM (raw HTML is already out of scope)
    try:
        distilled = await distill_single_url(body.url, page_title, page_content)
    except Exception as e:
        await db.close()
        raise HTTPException(500, f"LLM distillation failed: {e}")

    if not distilled.is_valid:
        await db.close()
        return {
            "topic_id": None,
            "status": "filtered",
            "filter_reason": distilled.filter_reason,
            "title": distilled.title,
            "message": f"Topic was filtered: {distilled.filter_reason}",
        }

    # Step 3: Create topic
    import json
    topic_id = str(uuid4())
    now = datetime.now().isoformat()
    source_material_json = json.dumps(distilled.source_material, ensure_ascii=False)

    await db.execute(
        """INSERT INTO topics (id, title, source_url, source_type, raw_content,
           heat_level, source_material, status, created_at, updated_at)
           VALUES (?, ?, ?, 'manual', ?, ?, ?, 'pending', ?, ?)""",
        (topic_id, distilled.title, body.url, distilled.raw_content,
         distilled.heat_level, source_material_json, now, now),
    )

    # Step 4: Score
    score = score_topic(
        title=distilled.title,
        content=distilled.raw_content,
        weight_mode=body.weight_mode,
        platform=body.platform,
        positioning=body.positioning,
    )
    score.topic_id = topic_id
    await db.execute(
        """INSERT INTO score_results (id, topic_id, relevance_score, timeliness_score,
           value_score, compliance_score, competition_score, total_score, grade,
           bonus_details, weight_mode, platform, positioning, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (score.id, topic_id, score.relevance_score, score.timeliness_score,
         score.value_score, score.compliance_score, score.competition_score,
         score.total_score, score.grade, score.bonus_details,
         score.weight_mode, score.platform, score.positioning, now),
    )
    await db.execute("UPDATE topics SET status = 'scored', updated_at = ? WHERE id = ?", (now, topic_id))

    # Check score threshold
    threshold = load_config().get("collector", {}).get("auto_score_threshold", 80)
    if score.total_score < threshold:
        await db.execute("UPDATE topics SET status = 'discarded', updated_at = ? WHERE id = ?", (now, topic_id))
        await db.commit()
        await db.close()
        return {
            "topic_id": topic_id,
            "status": "filtered",
            "filter_reason": f"评分 {score.total_score} 未达 {threshold} 分门槛",
            "score": score.model_dump(),
        }

    # Step 5: Match (rule-based for speed)
    matches = await match_celebrities_rule_based(
        title=distilled.title, content=distilled.raw_content,
    )
    for m in matches:
        m.topic_id = topic_id
        await db.execute(
            """INSERT INTO match_results (id, topic_id, celebrity_id, celebrity_name,
               match_score, match_reason, rank, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), topic_id, m.celebrity_id, m.celebrity_name,
             m.match_score, m.match_reason, m.rank, now),
        )
    await db.execute("UPDATE topics SET status = 'matched', updated_at = ? WHERE id = ?", (now, topic_id))

    await db.commit()
    await db.close()

    return {
        "topic_id": topic_id,
        "status": "created",
        "title": distilled.title,
        "score": score.model_dump(),
        "matches": [m.model_dump() for m in matches],
    }


@router.get("/logs")
async def collection_logs(limit: int = 20):
    """Return recent collection run logs."""
    db = await get_db()
    rows = await db.execute(
        "SELECT * FROM collection_logs ORDER BY completed_at DESC LIMIT ?",
        (limit,),
    )
    logs = [dict(r) for r in await rows.fetchall()]
    await db.close()
    return logs
