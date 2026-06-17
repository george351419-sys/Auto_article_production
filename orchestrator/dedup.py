"""Deduplication engine per PRD §11.

L1: Title normalization match against 7-day window.
L2: Entity Jaccard ≥ 0.7 AND topic_keywords overlap ≥ 1.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any

import aiosqlite

import crud

# ── L1: Title normalization ──────────────────────────────────

# Common Chinese and English stopwords to remove during normalization
_STOPWORDS: set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "nor", "not", "so", "yet", "both", "either", "neither", "each", "every",
    "all", "any", "few", "more", "most", "other", "some", "such", "no",
    "only", "own", "same", "than", "too", "very", "just", "about",
}


def normalize_title(title: str) -> str:
    """Normalize title for L1 comparison. Delegates to crud's implementation."""
    return crud._normalize_title(title)


# ── L1 check ────────────────────────────────────────────────

async def l1_check(db: aiosqlite.Connection, normalized_title: str, exclude_id: str = "") -> str | None:
    """Check if a normalized title matches any topic in the last 7 days.

    Uses the already-normalized title from crud._normalize_title.
    Returns the dup_of_topic_id if duplicate found, None otherwise.
    """
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    if exclude_id:
        cursor = await db.execute(
            "SELECT id FROM topic WHERE title_normalized = ? AND created_at >= ? AND id != ?",
            (normalized_title, seven_days_ago, exclude_id),
        )
    else:
        cursor = await db.execute(
            "SELECT id FROM topic WHERE title_normalized = ? AND created_at >= ?",
            (normalized_title, seven_days_ago),
        )
    row = await cursor.fetchone()
    return row["id"] if row else None


# ── L2: Entity + keyword comparison ─────────────────────────

def jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity coefficient."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def check_keyword_overlap(kw_a: list[str], kw_b: list[str]) -> bool:
    """True if at least one keyword overlaps."""
    return bool(set(kw_a) & set(kw_b))


async def l2_check(
    db: aiosqlite.Connection,
    entities: list[str],
    topic_keywords: list[str],
) -> str | None:
    """Check if entities + keywords match any topic in the last 7 days.

    L2 rule: entity Jaccard ≥ 0.7 AND keyword overlap ≥ 1.

    Returns dup_of_topic_id if match found, None otherwise.
    """
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    cursor = await db.execute(
        "SELECT id, entities, topic_keywords FROM topic "
        "WHERE status != 'duplicated' AND created_at >= ?",
        (seven_days_ago,),
    )
    rows = await cursor.fetchall()

    entity_set = set(entities)
    kw_set = set(topic_keywords)

    for row in rows:
        try:
            existing_entities = json.loads(row["entities"]) if row["entities"] else []
            existing_kw = json.loads(row["topic_keywords"]) if row["topic_keywords"] else []
        except (json.JSONDecodeError, TypeError):
            continue

        ent_jaccard = jaccard(entity_set, set(existing_entities))
        kw_overlap = check_keyword_overlap(list(kw_set), existing_kw)

        if ent_jaccard >= 0.7 and kw_overlap:
            return row["id"]

    return None


# ── Combined dedup ──────────────────────────────────────────

async def run_dedup(topic_id: str) -> dict[str, Any]:
    """Run full dedup (L1 + L2) on a single topic.

    Returns: {"duplicated": bool, "dup_of": str|None, "method": str|None}
    """
    topic = await crud.get_topic(topic_id)
    if not topic:
        return {"duplicated": False, "dup_of": None, "method": None}

    # User-submitted topics never get auto-deduplicated
    if topic.get("user_submitted"):
        return {"duplicated": False, "dup_of": None, "method": None}

    conn = await crud.get_db()
    try:
        # L1: exact normalized title match (exclude self)
        normalized = normalize_title(topic["title"])
        dup_id = await l1_check(conn, normalized, exclude_id=topic_id)
        if dup_id:
            await conn.execute(
                "UPDATE topic SET status = 'duplicated', dup_of_topic_id = ?, updated_at = ? WHERE id = ?",
                (dup_id, crud._now(), topic_id),
            )
            await conn.commit()
            return {"duplicated": True, "dup_of": dup_id, "method": "L1"}

        # L2: entity + keyword check (only if entities are populated)
        entities_raw = topic.get("entities", "[]")
        kw_raw = topic.get("topic_keywords", "[]")
        try:
            entities = json.loads(entities_raw) if isinstance(entities_raw, str) else entities_raw
            keywords = json.loads(kw_raw) if isinstance(kw_raw, str) else kw_raw
        except (json.JSONDecodeError, TypeError):
            entities = []
            keywords = []

        if entities and keywords:
            dup_id = await l2_check(conn, entities, keywords)
            if dup_id:
                await conn.execute(
                    "UPDATE topic SET status = 'duplicated', dup_of_topic_id = ?, updated_at = ? WHERE id = ?",
                    (dup_id, crud._now(), topic_id),
                )
                await conn.commit()
                return {"duplicated": True, "dup_of": dup_id, "method": "L2"}

        await conn.commit()
        return {"duplicated": False, "dup_of": None, "method": None}
    finally:
        await conn.close()
