"""Review flow routes."""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from core.models import ReviewAction
from server.database import get_db

logger = logging.getLogger("review")
router = APIRouter(prefix="/topics", tags=["review"])

STATUS_FLOW = {
    "confirm": "confirmed",
    "discard": "discarded",
    "backup": "backup",
    "adjust": "matched",  # Return to matched state for re-matching
}


@router.post("/{topic_id}/review")
async def review_topic(topic_id: str, body: ReviewAction):
    db = await get_db()
    row = await db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
    topic = await row.fetchone()
    if not topic:
        await db.close()
        raise HTTPException(404, "Topic not found")
    topic = dict(topic)

    new_status = STATUS_FLOW.get(body.action, topic["status"])
    previous_status = topic["status"]
    now = datetime.now().isoformat()

    # Handle celebrity adjustment
    if body.action == "adjust" and body.adjust_celebrities:
        await db.execute("DELETE FROM match_results WHERE topic_id = ?", (topic_id,))
        for i, adj in enumerate(body.adjust_celebrities):
            await db.execute(
                """INSERT INTO match_results (id, topic_id, celebrity_id, celebrity_name,
                   match_score, match_reason, rank, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), topic_id,
                 adj.get("celebrity_id", ""), adj.get("celebrity_name", ""),
                 adj.get("match_score", 0), adj.get("match_reason", "人工调整"),
                 i + 1, now),
            )

    # Update topic status
    await db.execute(
        "UPDATE topics SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now, topic_id),
    )

    # Create review log
    log_id = str(uuid4())
    await db.execute(
        """INSERT INTO review_logs (id, topic_id, action, previous_status, new_status,
           operator, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (log_id, topic_id, body.action, previous_status, new_status,
         "admin", body.note, now),
    )

    await db.commit()
    await db.close()

    logger.info("Topic %s reviewed: %s -> %s", topic_id[:8], body.action, new_status)
    return {"topic_id": topic_id, "action": body.action, "status": new_status}
