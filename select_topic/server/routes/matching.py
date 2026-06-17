"""Matching routes."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from core.models import MatchRequest
from core.matching_engine import match_celebrities, match_celebrities_rule_based
from server.database import get_db

logger = logging.getLogger("matching")
router = APIRouter(prefix="/topics", tags=["matching"])


@router.post("/{topic_id}/match")
async def match_topic_route(topic_id: str, body: MatchRequest = MatchRequest()):
    db = await get_db()
    row = await db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
    topic = await row.fetchone()
    if not topic:
        await db.close()
        raise HTTPException(404, "Topic not found")
    topic = dict(topic)

    # Run matching engine
    if body.use_llm:
        try:
            matches = await match_celebrities(
                title=topic["title"],
                content=topic.get("raw_content", ""),
            )
        except Exception as e:
            logger.error("LLM matching failed, falling back to rules: %s", e)
            matches = await match_celebrities_rule_based(
                title=topic["title"],
                content=topic.get("raw_content", ""),
            )
    else:
        matches = await match_celebrities_rule_based(
            title=topic["title"],
            content=topic.get("raw_content", ""),
        )

    # Save match results
    now = datetime.now().isoformat()
    await db.execute("DELETE FROM match_results WHERE topic_id = ?", (topic_id,))
    for m in matches:
        m.topic_id = topic_id
        await db.execute(
            """INSERT INTO match_results (id, topic_id, celebrity_id, celebrity_name,
               match_score, match_reason, rank, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), topic_id, m.celebrity_id, m.celebrity_name,
             m.match_score, m.match_reason, m.rank, now),
        )

    # Update topic status
    await db.execute(
        "UPDATE topics SET status = ?, updated_at = ? WHERE id = ?",
        ("matched", now, topic_id),
    )
    await db.commit()
    await db.close()

    logger.info("Topic %s matched with %d celebrities", topic_id[:8], len(matches))
    return {"topic_id": topic_id, "matches": [m.model_dump() for m in matches]}
