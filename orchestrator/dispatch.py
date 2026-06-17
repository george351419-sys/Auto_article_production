"""Dispatch logic per LLD §5.1 / PRD §5.

Rules:
  - Score ≥ 70 → push to that platform
  - Score 50-69 → edge candidate (used for 23:00 boost)
  - Score < 50 → skip
  - 23:00 cron: if a platform has 0 published today, pick the highest-scored
    article for that platform and force-publish it (boost).
"""
from __future__ import annotations

from typing import Any

import aiosqlite

import crud

PUBLISH_THRESHOLD = 70
BOOST_MIN_SCORE = 50


def should_publish(score: int) -> bool:
    """True if score meets the publish threshold."""
    return score >= PUBLISH_THRESHOLD


def is_edge_candidate(score: int) -> bool:
    """True if score is in the boost-eligible range (50-69)."""
    return BOOST_MIN_SCORE <= score < PUBLISH_THRESHOLD


def decide_platforms(scores: list[dict[str, Any]]) -> list[str]:
    """Given a list of {platform, score} dicts, return platforms to publish to."""
    result = []
    for s in scores:
        if should_publish(s.get("score", 0)):
            result.append(s["platform"])
    return result


async def get_today_published_counts(db: aiosqlite.Connection) -> dict[str, int]:
    """Return per-platform count of successful publishes today.
    'Today' is the operator's local day (Asia/Shanghai), not UTC.
    """
    today_local_start = crud.local_today_start_utc_iso()
    cursor = await db.execute(
        "SELECT platform, COUNT(*) as cnt FROM publish "
        "WHERE status = 'success' AND executed_at >= ? GROUP BY platform",
        (today_local_start,),
    )
    rows = await cursor.fetchall()
    return {r["platform"]: r["cnt"] for r in rows}


async def find_boost_candidates(
    db: aiosqlite.Connection, platform: str,
) -> list[dict[str, Any]]:
    """Find scored articles whose latest score for this platform is ≥ BOOST_MIN_SCORE.

    Returns articles ordered by score descending (best candidate first).
    Only considers articles that haven't already been published to this platform today.
    """
    today_local_start = crud.local_today_start_utc_iso()
    cursor = await db.execute(
        """SELECT a.id, a.topic_id, s.score, s.reason
           FROM article a
           INNER JOIN (
             SELECT article_id, platform, MAX(generation_n) as max_gen
             FROM score WHERE platform = ? GROUP BY article_id, platform
           ) latest ON a.id = latest.article_id
           INNER JOIN score s ON s.article_id = latest.article_id
             AND s.platform = latest.platform
             AND s.generation_n = latest.max_gen
           WHERE s.score >= ?
             AND a.status IN ('scored', 'reviewing')
             AND a.id NOT IN (
               SELECT article_id FROM publish
               WHERE platform = ? AND status = 'success'
                 AND executed_at >= ?
             )
           ORDER BY s.score DESC""",
        (platform, BOOST_MIN_SCORE, platform, today_local_start),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def run_boost_check() -> dict[str, Any]:
    """Check if any platform needs a boost publish (daily 23:00 routine).

    Returns dict with actions taken per platform.
    """
    conn = await crud.get_db()
    try:
        today_counts = await get_today_published_counts(conn)
        all_platforms = ["wechat", "xiaohongshu", "toutiao"]
        result: dict[str, Any] = {"boosted": {}, "skipped": {}, "no_candidate": []}

        for platform in all_platforms:
            count = today_counts.get(platform, 0)
            if count > 0:
                result["skipped"][platform] = f"already {count} published"
                continue

            candidates = await find_boost_candidates(conn, platform)
            if not candidates:
                result["no_candidate"].append(platform)
                continue

            best = candidates[0]
            result["boosted"][platform] = {
                "article_id": best["id"],
                "score": best["score"],
                "reason": best.get("reason", ""),
            }

        await conn.commit()
        return result
    finally:
        await conn.close()
