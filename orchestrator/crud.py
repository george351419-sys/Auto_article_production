"""Async CRUD operations for the orchestrator's LLD §2 tables.

Replaces the old store.py which used a simpler pipeline_jobs table.
Uses aiosqlite with row_factory and JSON serialization for compound fields.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

DB_PATH = Path(__file__).parent / "data" / "pipeline.db"

# Operator lives in UTC+8; "today" in dashboard / boost / cleanup means
# the user's day, not the UTC day. Centralised so dispatch + dashboard
# stay consistent.
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def local_today_start_utc_iso() -> str:
    """Return ISO 8601 timestamp for *today at 00:00 in Asia/Shanghai*,
    expressed in UTC so it can be compared against `*_at` columns that
    store UTC ISO strings.
    """
    now_local = datetime.now(LOCAL_TZ)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(timezone.utc).isoformat()


# ── Connection helpers ───────────────────────────────────────

async def get_db() -> aiosqlite.Connection:
    """Get a connection with WAL pragmas and row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(DB_PATH))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ── Topic CRUD ───────────────────────────────────────────────

async def create_topic(
    title: str,
    source: str = "user",
    brief: str = "",
    source_url: str = "",
    raw_material: str = "",
    user_submitted: int = 0,
) -> dict[str, Any]:
    tid = _uid()
    now = _now()
    trace_id = _uid()
    title_normalized = _normalize_title(title)

    conn = await get_db()
    try:
        await conn.execute(
            """INSERT INTO topic (id, title, title_normalized, source, source_url,
               brief, raw_material, entities, topic_keywords, status,
               user_submitted, trace_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tid, title, title_normalized, source, source_url,
             brief, raw_material, "[]", "[]", "collected",
             user_submitted, trace_id, now, now),
        )
        await conn.commit()
    finally:
        await conn.close()
    return await get_topic(tid)


async def get_topic(topic_id: str) -> dict[str, Any] | None:
    conn = await get_db()
    try:
        cursor = await conn.execute("SELECT * FROM topic WHERE id = ?", (topic_id,))
        row = await cursor.fetchone()
    finally:
        await conn.close()
    return _row_to_dict(row) if row else None


async def list_topics(
    status: str | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source:
            clauses.append("source = ?")
            params.append(source)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cursor = await conn.execute(
            f"SELECT * FROM topic {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        )
        rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


async def update_topic_status(topic_id: str, status: str) -> dict[str, Any] | None:
    conn = await get_db()
    try:
        await conn.execute(
            "UPDATE topic SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), topic_id),
        )
        await conn.commit()
    finally:
        await conn.close()
    return await get_topic(topic_id)


async def update_topic_entities(
    topic_id: str, entities: list[str], topic_keywords: list[str]
) -> None:
    conn = await get_db()
    try:
        await conn.execute(
            "UPDATE topic SET entities = ?, topic_keywords = ?, updated_at = ? WHERE id = ?",
            (json.dumps(entities, ensure_ascii=False),
             json.dumps(topic_keywords, ensure_ascii=False),
             _now(), topic_id),
        )
        await conn.commit()
    finally:
        await conn.close()


# ── Article CRUD ─────────────────────────────────────────────

async def create_article(
    topic_id: str,
    character_id: str = "",
    status: str = "matched",
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Insert an article row. `status` defaults to "matched" for backward
    compatibility with M2 tests/fixtures, but the production path
    (POST /api/topics, sync_topics_from_select_topic) should pass
    status="collected" and then advance via state_machine so an audit_log
    entry is written for every transition (HLD §4.2 invariant).
    """
    aid = _uid()
    now = _now()
    tid = trace_id or _uid()

    conn = await get_db()
    try:
        await conn.execute(
            """INSERT INTO article (id, topic_id, character_id, status,
               retry_count, trace_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, topic_id, character_id, status, 0, tid, now, now),
        )
        # Initial state must be a known state (audit_log will record the
        # first transition's from_state). The status enum is enforced at
        # state_machine.STATES, but we don't validate here to keep CRUD
        # cheap — callers are responsible for passing a valid value.
        await conn.commit()
    finally:
        await conn.close()
    return await get_article(aid)


async def write_audit_entry(
    entity_type: str,
    entity_id: str,
    to_state: str,
    *,
    from_state: str | None = None,
    trigger: str = "auto",
    actor: str = "system",
    trace_id: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    """Append a single audit_log row directly (no transition).

    Use this for the *initial* state entry where there is no prior state
    to validate. For subsequent transitions, use state_machine.transition.
    """
    conn = await get_db()
    try:
        await conn.execute(
            """INSERT INTO audit_log
               (entity_type, entity_id, from_state, to_state, trigger,
                actor, payload_json, trace_id, at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entity_type, entity_id, from_state, to_state, trigger, actor,
             json.dumps(payload or {}, ensure_ascii=False), trace_id or _uid(), _now()),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_article(article_id: str) -> dict[str, Any] | None:
    conn = await get_db()
    try:
        cursor = await conn.execute("SELECT * FROM article WHERE id = ?", (article_id,))
        row = await cursor.fetchone()
    finally:
        await conn.close()
    return _row_to_dict(row) if row else None


async def list_articles(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        if status:
            cursor = await conn.execute(
                "SELECT * FROM article WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM article ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


async def update_article(article_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return await get_article(article_id)

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [article_id]

    conn = await get_db()
    try:
        await conn.execute(
            f"UPDATE article SET {set_clause} WHERE id = ?", values,
        )
        await conn.commit()
    finally:
        await conn.close()
    return await get_article(article_id)


# ── Score CRUD ───────────────────────────────────────────────

async def create_score(
    article_id: str,
    platform: str,
    score_val: int,
    reason: str,
    generation_n: int = 1,
    *,
    conn: aiosqlite.Connection | None = None,
) -> dict[str, Any]:
    """Insert a score row.

    `conn`: when the caller is mid-transaction and wants this write to
    share its connection/transaction, pass it. Otherwise we open + commit
    + close on our own (preserves the old behaviour for tests).
    """
    sid = _uid()
    now = _now()

    own = conn is None
    db = conn or await get_db()
    try:
        await db.execute(
            """INSERT INTO score (id, article_id, platform, score, reason, generation_n, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sid, article_id, platform, score_val, reason, generation_n, now),
        )
        if own:
            await db.commit()
    finally:
        if own:
            await db.close()
    return {"id": sid, "article_id": article_id, "platform": platform,
            "score": score_val, "reason": reason, "generation_n": generation_n,
            "generated_at": now}


async def get_scores_for_article(article_id: str) -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        cursor = await conn.execute(
            "SELECT * FROM score WHERE article_id = ? ORDER BY generation_n DESC, platform",
            (article_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


async def get_latest_scores_for_article(article_id: str) -> list[dict[str, Any]]:
    """Return only the latest generation_n scores per platform."""
    conn = await get_db()
    try:
        cursor = await conn.execute(
            """SELECT s.* FROM score s
               INNER JOIN (
                 SELECT platform, MAX(generation_n) as max_gen
                 FROM score WHERE article_id = ? GROUP BY platform
               ) latest ON s.platform = latest.platform AND s.generation_n = latest.max_gen
               WHERE s.article_id = ?""",
            (article_id, article_id),
        )
        rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


# ── Publish CRUD ─────────────────────────────────────────────

async def create_publish(
    article_id: str,
    platform: str,
    status: str = "pending",
    *,
    conn: aiosqlite.Connection | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Insert a publish row.

    `conn`: pass an open connection to share its transaction; otherwise
    we open + commit + close. `trace_id`: by default a fresh UUID, but
    callers should pass the article's trace_id so the full pipeline
    shares one trace.
    """
    pid = _uid()
    now = _now()
    tid = trace_id or _uid()

    own = conn is None
    db = conn or await get_db()
    try:
        await db.execute(
            """INSERT INTO publish (id, article_id, platform, status, scheduled_at, trace_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pid, article_id, platform, status, now, tid),
        )
        if own:
            await db.commit()
    finally:
        if own:
            await db.close()
    return await get_publish(pid)


async def get_publish(publish_id: str) -> dict[str, Any] | None:
    conn = await get_db()
    try:
        cursor = await conn.execute("SELECT * FROM publish WHERE id = ?", (publish_id,))
        row = await cursor.fetchone()
    finally:
        await conn.close()
    return _row_to_dict(row) if row else None


async def get_publishes_for_article(article_id: str) -> list[dict[str, Any]]:
    conn = await get_db()
    try:
        cursor = await conn.execute(
            "SELECT * FROM publish WHERE article_id = ? ORDER BY platform",
            (article_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await conn.close()
    return [_row_to_dict(r) for r in rows]


async def update_publish(
    publish_id: str,
    *,
    conn: aiosqlite.Connection | None = None,
    **fields: Any,
) -> dict[str, Any] | None:
    if not fields:
        return await get_publish(publish_id)

    # Whitelist columns that callers are allowed to update directly.
    # Anything outside this set is rejected — prevents identifier
    # injection and prevents stale callers from clobbering critical
    # columns (e.g. id, article_id).
    allowed = {
        "status", "platform_url", "platform_msg_id",
        "error_code", "error_message", "executed_at", "duration_ms",
    }
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"update_publish: disallowed columns {sorted(bad)}")

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [publish_id]

    own = conn is None
    db = conn or await get_db()
    try:
        await db.execute(f"UPDATE publish SET {set_clause} WHERE id = ?", values)
        if own:
            await db.commit()
    finally:
        if own:
            await db.close()
    return await get_publish(publish_id)


# ── Dashboard stats ──────────────────────────────────────────

async def get_dashboard_stats() -> dict[str, Any]:
    """Aggregate stats for the dashboard."""
    conn = await get_db()
    try:
        today_local_start = local_today_start_utc_iso()
        result: dict[str, Any] = {"today_published": 0, "pending_review": 0,
                                   "failed": 0, "by_status": {}}

        # Today's publishes (today = midnight in Asia/Shanghai → now)
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM publish "
            "WHERE status = 'success' AND executed_at >= ?",
            (today_local_start,),
        )
        row = await cursor.fetchone()
        result["today_published"] = row["cnt"] if row else 0

        # Pending review
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM article WHERE status = 'reviewing'",
        )
        row = await cursor.fetchone()
        result["pending_review"] = row["cnt"] if row else 0

        # Failed
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM article WHERE status = 'failed'",
        )
        row = await cursor.fetchone()
        result["failed"] = row["cnt"] if row else 0

        # Counts by article status
        for s in STATES:
            cursor = await conn.execute(
                "SELECT COUNT(*) as cnt FROM article WHERE status = ?", (s,),
            )
            row = await cursor.fetchone()
            result["by_status"][s] = row["cnt"] if row else 0

        return result
    finally:
        await conn.close()


STATES = (
    "collected", "duplicated", "matched", "writing", "drafted",
    "scored", "reviewing", "rejected", "publishing", "published", "failed",
)


# ── Helpers ──────────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Normalize title for L1 dedup: strip punctuation, lowercase, remove whitespace."""
    import re
    t = title.lower().strip()
    t = re.sub(r'[\s　]+', '', t)
    t = re.sub(r'[^\w一-鿿]', '', t)
    return t


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    # Parse JSON fields
    for key in ("entities", "topic_keywords", "final_package"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
