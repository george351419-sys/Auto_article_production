"""Topic CRUD routes."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from core.models import TopicCreate, TopicFilter
from server.database import get_db

logger = logging.getLogger("topics")
router = APIRouter(prefix="/topics", tags=["topics"])


@router.post("")
async def create_topic(body: TopicCreate):
    topic = {
        "id": str(uuid4()),
        "title": body.title,
        "source_url": body.source_url,
        "source_type": body.source_type,
        "source_platform": body.source_platform,
        "raw_content": body.raw_content,
        "heat_level": body.heat_level or "normal",
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    db = await get_db()
    await db.execute(
        """INSERT INTO topics (id, title, source_url, source_type, source_platform,
           raw_content, heat_level, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tuple(topic.values()),
    )
    await db.commit()
    await db.close()
    logger.info("Created topic: %s", body.title[:50])
    return topic


@router.get("")
async def list_topics(
    status: str = "",
    grade: str = "",
    min_score: float = 0.0,
    search: str = "",
    source_type: str = "",
    limit: int = 50,
    offset: int = 0,
):
    db = await get_db()
    where = []
    params = []

    if status:
        where.append("t.status = ?")
        params.append(status)
    if search:
        where.append("t.title LIKE ?")
        params.append(f"%{search}%")
    if grade:
        where.append("s.grade = ?")
        params.append(grade)
    if min_score > 0:
        where.append("s.total_score >= ?")
        params.append(min_score)
    if source_type:
        where.append("t.source_type = ?")
        params.append(source_type)

    where_clause = " AND ".join(where) if where else "1=1"
    query = f"""SELECT t.*, s.total_score, s.grade
                FROM topics t
                LEFT JOIN score_results s ON t.id = s.topic_id
                WHERE {where_clause}
                ORDER BY t.created_at DESC
                LIMIT ? OFFSET ?"""
    params.extend([limit, offset])

    rows = await db.execute(query, params)
    topics = [dict(r) for r in await rows.fetchall()]

    # Get match results for each topic
    for topic in topics:
        match_rows = await db.execute(
            "SELECT * FROM match_results WHERE topic_id = ? ORDER BY rank",
            (topic["id"],),
        )
        topic["matches"] = [dict(r) for r in await match_rows.fetchall()]

    await db.close()
    return topics


@router.get("/{topic_id}")
async def get_topic(topic_id: str):
    db = await get_db()
    row = await db.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
    topic = await row.fetchone()
    if not topic:
        await db.close()
        raise HTTPException(404, "Topic not found")
    topic = dict(topic)

    # Get score
    score_row = await db.execute(
        "SELECT * FROM score_results WHERE topic_id = ?", (topic_id,)
    )
    score = await score_row.fetchone()
    topic["score"] = dict(score) if score else None

    # Get matches
    match_rows = await db.execute(
        "SELECT * FROM match_results WHERE topic_id = ? ORDER BY rank", (topic_id,)
    )
    topic["matches"] = [dict(r) for r in await match_rows.fetchall()]

    # Get review logs
    review_rows = await db.execute(
        "SELECT * FROM review_logs WHERE topic_id = ? ORDER BY created_at DESC", (topic_id,)
    )
    topic["review_logs"] = [dict(r) for r in await review_rows.fetchall()]

    await db.close()
    return topic


@router.delete("/{topic_id}")
async def delete_topic(topic_id: str):
    db = await get_db()
    await db.execute("DELETE FROM match_results WHERE topic_id = ?", (topic_id,))
    await db.execute("DELETE FROM score_results WHERE topic_id = ?", (topic_id,))
    await db.execute("DELETE FROM review_logs WHERE topic_id = ?", (topic_id,))
    await db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    await db.commit()
    await db.close()
    return {"deleted": True}
