"""Retry backoff controller per HLD §4.3 and LLD §5.

Exponential backoff: 30s, 2min, 10min. Max 3 retries.
Total retry window ≤ 15 minutes.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

# Backoff schedule per HLD §4.3:
#   retry_count=0 → 30s, retry_count=1 → 2min, retry_count=2 → 10min.
# After the third retry, the article stays in `failed` for human review.

MAX_RETRIES = 3
RETRY_DELAYS = [30, 120, 600]  # seconds: 30s, 2min, 10min


def next_retry_at(retry_count: int, now: datetime | None = None) -> str:
    """Compute the next retry ISO timestamp.

    retry_count 0 → 30s from now
    retry_count 1 → 2min from now
    retry_count 2 → 10min from now
    retry_count ≥ 3 → None (no more retries)
    """
    if retry_count >= MAX_RETRIES:
        return ""
    dt = now or datetime.now(timezone.utc)
    delay = RETRY_DELAYS[min(retry_count, len(RETRY_DELAYS) - 1)]
    return (dt + timedelta(seconds=delay)).isoformat()


def should_retry(retry_count: int, first_attempt_at: str | None = None) -> bool:
    """True if the article should be retried automatically."""
    if retry_count >= MAX_RETRIES:
        return False
    if first_attempt_at:
        # Check total window ≤ 15 minutes
        try:
            first = datetime.fromisoformat(first_attempt_at)
            elapsed = (datetime.now(timezone.utc) - first).total_seconds()
            if elapsed > 900:  # 15 minutes
                return False
        except (ValueError, TypeError):
            pass
    return True


async def schedule_retry(article_id: str, retry_count: int) -> dict:
    """Schedule a retry by updating article's next_retry_at.

    Returns dict with new retry_count and next_retry_at.
    """
    import crud

    nra = next_retry_at(retry_count)
    new_count = retry_count + 1

    if nra:
        await crud.update_article(article_id, retry_count=new_count, next_retry_at=nra)
    else:
        await crud.update_article(article_id, retry_count=new_count)

    return {"article_id": article_id, "retry_count": new_count, "next_retry_at": nra or None}


async def find_due_retries() -> list[dict]:
    """Return failed articles whose `next_retry_at` is in the past and
    whose retry_count has not exhausted the budget.

    Caller (scheduler) is responsible for moving them back to a pre-failure
    state via state_machine.transition_article.
    """
    import crud

    conn = await crud.get_db()
    try:
        cursor = await conn.execute(
            """SELECT id, retry_count, next_retry_at
                 FROM article
                WHERE status = 'failed'
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= ?
                  AND retry_count < ?
             ORDER BY next_retry_at""",
            (datetime.now(timezone.utc).isoformat(), MAX_RETRIES),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def latest_pre_failure_state(article_id: str) -> str | None:
    """Look at audit_log to find what state the article was in *before*
    it most recently transitioned to `failed`. Returns None if no such
    entry exists (article was never failed before, or audit_log was
    truncated).
    """
    import crud

    conn = await crud.get_db()
    try:
        cursor = await conn.execute(
            """SELECT from_state
                 FROM audit_log
                WHERE entity_type = 'article'
                  AND entity_id = ?
                  AND to_state = 'failed'
             ORDER BY id DESC LIMIT 1""",
            (article_id,),
        )
        row = await cursor.fetchone()
        return row["from_state"] if row else None
    finally:
        await conn.close()


async def clear_retry_timer(article_id: str) -> None:
    """Clear next_retry_at once the article has been moved out of failed.
    Keeps the retry_count so the next failure correctly picks up the
    next backoff slot.
    """
    import crud
    await crud.update_article(article_id, next_retry_at=None)
