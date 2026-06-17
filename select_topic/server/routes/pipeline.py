"""Pipeline routes — one-click import+score+match."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter

from core.models import PipelineRequest
from server.database import get_db
from core.scoring_engine import score_topic
from core.matching_engine import match_celebrities_rule_based, match_celebrities
from config import load_config

logger = logging.getLogger("pipeline")
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/run")
async def run_pipeline(body: PipelineRequest):
    db = await get_db()
    now = datetime.now().isoformat()

    # Step 1: Create topic
    topic_id = str(uuid4())
    source_material_json = json.dumps(
        [sm.model_dump() if hasattr(sm, 'model_dump') else sm for sm in body.source_material],
        ensure_ascii=False,
    ) if body.source_material else "[]"
    await db.execute(
        """INSERT INTO topics (id, title, source_url, source_type, raw_content,
           source_material, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (topic_id, body.title, body.source_url, body.source_type, body.raw_content,
         source_material_json, now, now),
    )

    # Step 2: Score
    score = score_topic(
        title=body.title,
        content=body.raw_content,
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

    # Step 3: Match (rule-based first for speed; LLM can be triggered separately)
    try:
        matches = await match_celebrities(
            title=body.title,
            content=body.raw_content,
        )
    except Exception as e:
        logger.warning("LLM matching failed, using rule-based: %s", e)
        matches = await match_celebrities_rule_based(
            title=body.title,
            content=body.raw_content,
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

    logger.info("Pipeline complete for topic %s: score=%.1f matches=%d",
                topic_id[:8], score.total_score, len(matches))

    return {
        "topic_id": topic_id,
        "score": score.model_dump(),
        "matches": [m.model_dump() for m in matches],
    }
