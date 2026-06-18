"""Data cleanup engine per HLD §8.5.

Graded retention rules:
  - audit_log: permanent
  - published article DB records: permanent
  - published article images: 7 days
  - user-submitted topics: permanent
  - auto-collected duplicated topics: 7 days
  - rejected articles: 14 days
  - failed/abandoned articles (unattended 7d): → rejected
  - collected/matched stuck >48h: → failed
  - scored/reviewing (rated but unpublished): permanent
  - orchestrator logs: 14 days
  - threshold guard: >2.5GB triggers emergency cleanup

Safety:
  - single sweep lock (no concurrent cleanup)
  - dry-run: if >1000 items would be deleted → abort + alert
  - skip articles currently publishing
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

import crud
import state_machine as sm

logger = logging.getLogger("cleanup")

THRESHOLD_GB = 2.5
SWEEP_LOCK_FILE = Path(crud.DB_PATH).parent / ".cleanup_lock"
DRY_RUN_MAX = 1000

# ── Helpers ──────────────────────────────────────────────────


async def _get_data_dir_size() -> int:
    """Return size of orchestrator data directory in bytes."""
    total = 0
    data_dir = Path(crud.DB_PATH).parent
    if not data_dir.exists():
        return 0
    for f in data_dir.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


async def _get_data_dir_size_gb() -> float:
    return await _get_data_dir_size() / (1024 ** 3)


async def _count_pending_deletes(
    db: aiosqlite.Connection,
    topic_ids: list[str],
    article_ids: list[str],
    asset_ids: list[str],
) -> int:
    return len(topic_ids) + len(article_ids) + len(asset_ids)


# ── Retention rules ──────────────────────────────────────────


async def find_expired_assets(db: aiosqlite.Connection, retention_days: int = 7) -> list[str]:
    """Find asset IDs for published articles where images are older than retention_days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    cursor = await db.execute(
        """SELECT a.id FROM asset a
           INNER JOIN article ar ON a.article_id = ar.id
           WHERE ar.status = 'published'
             AND a.downloaded_at <= ?
             AND a.deleted_at IS NULL""",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    return [r["id"] for r in rows]


async def find_expired_duplicated_topics(db: aiosqlite.Connection) -> list[str]:
    """Find auto-collected duplicated topics older than 7 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    cursor = await db.execute(
        "SELECT id FROM topic WHERE status = 'duplicated' "
        "AND user_submitted = 0 AND created_at <= ?",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    return [r["id"] for r in rows]


async def find_expired_rejected_articles(db: aiosqlite.Connection) -> list[str]:
    """Find rejected articles older than 14 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    cursor = await db.execute(
        "SELECT id FROM article WHERE status = 'rejected' AND created_at <= ?",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    return [r["id"] for r in rows]


async def find_stuck_articles(db: aiosqlite.Connection, status: str, hours: int) -> list[str]:
    """Find articles stuck in a given status for more than `hours` hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cursor = await db.execute(
        "SELECT id FROM article WHERE status = ? AND updated_at <= ?",
        (status, cutoff),
    )
    rows = await cursor.fetchall()
    return [r["id"] for r in rows]


async def find_abandoned_failed_articles(db: aiosqlite.Connection) -> list[str]:
    """Find failed articles where retries are exhausted and >7 days old."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    cursor = await db.execute(
        "SELECT id FROM article WHERE status = 'failed' "
        "AND retry_count >= 3 AND created_at <= ?",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    return [r["id"] for r in rows]


# ── Sweep ────────────────────────────────────────────────────


async def run_sweep(trigger: str = "cron_3h") -> dict[str, Any]:
    """Run a full cleanup sweep. Returns summary dict."""
    lock = Path(SWEEP_LOCK_FILE)
    if lock.exists():
        return {"ok": False, "error": "Another sweep is already running"}

    lock.write_text(str(os.getpid()))
    size_before = await _get_data_dir_size()
    logger.info("Cleanup sweep started (trigger=%s)", trigger)

    result: dict[str, Any] = {
        "trigger": trigger,
        "started_at": crud._now(),
        "deleted_topics": 0,
        "deleted_articles": 0,
        "deleted_assets": 0,
        "freed_bytes": 0,
        "error": None,
    }

    try:
        conn = await crud.get_db()
        try:
            # 1. Collect candidates
            asset_ids = await find_expired_assets(conn)
            dup_topic_ids = await find_expired_duplicated_topics(conn)
            rejected_article_ids = await find_expired_rejected_articles(conn)
            stuck_collected = await find_stuck_articles(conn, "collected", 48)
            stuck_matched = await find_stuck_articles(conn, "matched", 48)
            abandoned_failed = await find_abandoned_failed_articles(conn)

            # 2. Dry-run check
            total = (len(asset_ids) + len(dup_topic_ids) + len(rejected_article_ids)
                     + len(stuck_collected) + len(stuck_matched) + len(abandoned_failed))
            if total > DRY_RUN_MAX:
                result["error"] = f"Dry-run limit: {total} items would be deleted (max {DRY_RUN_MAX})"
                await conn.commit()
                return result

            # 3. Transition stuck articles → failed via state machine (preserves audit_log).
            for aid in stuck_collected:
                try:
                    await sm.transition_article(conn, aid, "failed", "cron",
                                                from_state="collected",
                                                payload={"reason": "stuck >48h"})
                except Exception as e:
                    logger.warning("Cleanup: failed to transition stuck article %s: %s", aid, e)

            for aid in stuck_matched:
                try:
                    await sm.transition_article(conn, aid, "failed", "cron",
                                                from_state="matched",
                                                payload={"reason": "stuck >48h"})
                except Exception as e:
                    logger.warning("Cleanup: failed to transition stuck article %s: %s", aid, e)

            # 4. Transition abandoned failed → rejected via state machine.
            for aid in abandoned_failed:
                try:
                    await sm.transition_article(conn, aid, "rejected", "cron",
                                                from_state="failed",
                                                payload={"reason": "retries exhausted >7d"})
                except Exception as e:
                    logger.warning("Cleanup: failed to transition abandoned article %s: %s", aid, e)

            # 5. Delete assets (mark deleted, will physically delete files later)
            for aid in asset_ids:
                await conn.execute(
                    "UPDATE asset SET deleted_at = ? WHERE id = ?",
                    (crud._now(), aid),
                )
            result["deleted_assets"] = len(asset_ids)

            # 6. Delete duplicated topics — must delete linked articles first (FK constraint).
            for tid in dup_topic_ids:
                await conn.execute(
                    "DELETE FROM article WHERE topic_id = ? AND status = 'duplicated'", (tid,)
                )
                await conn.execute("DELETE FROM topic WHERE id = ?", (tid,))
            result["deleted_topics"] = len(dup_topic_ids)

            # 7. Delete expired rejected articles (cascades to scores/assets)
            for aid in rejected_article_ids:
                await conn.execute("DELETE FROM article WHERE id = ?", (aid,))
            result["deleted_articles"] = len(rejected_article_ids)

            # 8. Write cleanup_log
            result["ended_at"] = crud._now()
            await conn.execute(
                """INSERT INTO cleanup_log (trigger, started_at, ended_at,
                   deleted_topics, deleted_articles, deleted_assets)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (trigger, result["started_at"], result["ended_at"],
                 result["deleted_topics"], result["deleted_articles"],
                 result["deleted_assets"]),
            )
            await conn.commit()
        finally:
            await conn.close()

        # 9. Calculate freed bytes (delta against size captured before sweep).
        result["freed_bytes"] = max(0, size_before - await _get_data_dir_size())

    except Exception as e:
        logger.error("Cleanup sweep failed: %s", e)
        result["error"] = str(e)
    finally:
        lock.unlink(missing_ok=True)

    logger.info("Cleanup sweep done: topics=%d articles=%d assets=%d",
                result["deleted_topics"], result["deleted_articles"],
                result["deleted_assets"])
    return result


async def check_threshold_guard() -> dict[str, Any]:
    """Check if data directory exceeds 2.5GB threshold. If so, trigger emergency cleanup."""
    size_gb = await _get_data_dir_size_gb()
    if size_gb > THRESHOLD_GB:
        logger.warning("Threshold exceeded: %.2f GB > %.1f GB. Triggering emergency cleanup.", size_gb, THRESHOLD_GB)
        return await run_sweep(trigger="threshold_2_5g")
    return {"ok": True, "size_gb": round(size_gb, 2), "triggered": False}
