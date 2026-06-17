"""Scoring routes."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from core.models import ScoreRequest
from core.scoring_engine import score_topic
from server.database import get_db

logger = logging.getLogger("scoring")
router = APIRouter(prefix="/topics", tags=["scoring"])


@router.post("/{topic_id}/score")
async def score_topic_route(topic_id: str, body: ScoreRequest = ScoreRequest()):
    db = await get_db()
    row = await db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
    topic = await row.fetchone()
    if not topic:
        await db.close()
        raise HTTPException(404, "Topic not found")
    topic = dict(topic)

    # Run scoring engine
    result = score_topic(
        title=topic["title"],
        content=topic.get("raw_content", ""),
        weight_mode=body.weight_mode,
        platform=body.platform,
        positioning=body.positioning,
        use_llm=body.use_llm,
    )
    result.topic_id = topic_id

    # Upsert score result
    now = datetime.now().isoformat()
    await db.execute(
        """INSERT INTO score_results (id, topic_id, relevance_score, timeliness_score,
           value_score, compliance_score, competition_score, total_score, grade,
           bonus_details, weight_mode, platform, positioning, scoring_version, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(topic_id) DO UPDATE SET
           relevance_score=excluded.relevance_score, timeliness_score=excluded.timeliness_score,
           value_score=excluded.value_score, compliance_score=excluded.compliance_score,
           competition_score=excluded.competition_score, total_score=excluded.total_score,
           grade=excluded.grade, bonus_details=excluded.bonus_details,
           weight_mode=excluded.weight_mode, platform=excluded.platform,
           positioning=excluded.positioning,
           created_at=excluded.created_at""",
        (result.id, topic_id, result.relevance_score, result.timeliness_score,
         result.value_score, result.compliance_score, result.competition_score,
         result.total_score, result.grade, result.bonus_details,
         result.weight_mode, result.platform, result.positioning,
         result.scoring_version, now),
    )

    # Update topic status
    await db.execute(
        "UPDATE topics SET status = ?, updated_at = ? WHERE id = ?",
        ("scored", now, topic_id),
    )
    await db.commit()
    await db.close()

    logger.info("Topic %s scored: %.1f (%s)", topic_id[:8], result.total_score, result.grade)
    return {"topic_id": topic_id, "score": result.model_dump()}
