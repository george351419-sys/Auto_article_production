"""Tests for review timeout — 2h auto-approve.

Per DEV_PLAN M4.
"""
from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud
import state_machine as sm


@pytest.fixture
def m4_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m4_timeout.db"
    monkeypatch.setattr(crud, "DB_PATH", db_file)

    import asyncio
    mig = Path(__file__).resolve().parent.parent.parent / "orchestrator" / "migrations" / "0001_init.sql"
    sql = mig.read_text()

    async def _init():
        conn = await aiosqlite.connect(str(db_file))
        conn.row_factory = aiosqlite.Row
        await conn.executescript(sql)
        await conn.commit()
        await conn.close()
    asyncio.run(_init())

    yield db_file
    db_file.unlink(missing_ok=True)


async def _create_article_with_deadline(status: str, deadline: str):
    topic = await crud.create_topic("Timeout Test", source="user")
    art = await crud.create_article(topic["id"])
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = ?, review_deadline_at = ?, updated_at = ? WHERE id = ?",
            (status, deadline, crud._now(), art["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()
    return art


@pytest.mark.asyncio
class TestReviewTimeout:
    async def test_past_deadline_triggers_publishing(self, m4_db_path):
        """Article with review_deadline_at in the past should be auto-approved."""
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        art = await _create_article_with_deadline("reviewing", past)

        # Simulate timeout scanner
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn = await crud.get_db()
        try:
            cursor = await conn.execute(
                "SELECT * FROM article WHERE status = 'reviewing' AND review_deadline_at <= ?",
                (now,),
            )
            rows = await cursor.fetchall()
            overdue = [dict(r) for r in rows]

            for a in overdue:
                await sm.transition_article(conn, a["id"], "publishing", "cron",
                                            actor="review_timeout")
            await conn.commit()
        finally:
            await conn.close()

        updated = await crud.get_article(art["id"])
        assert updated["status"] == "publishing"

    async def test_future_deadline_stays_reviewing(self, m4_db_path):
        """Article with deadline in the future should NOT be auto-approved."""
        from datetime import datetime, timezone, timedelta
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        art = await _create_article_with_deadline("reviewing", future)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn = await crud.get_db()
        try:
            cursor = await conn.execute(
                "SELECT * FROM article WHERE status = 'reviewing' AND review_deadline_at <= ?",
                (now,),
            )
            rows = await cursor.fetchall()
            overdue_ids = {dict(r)["id"] for r in rows}
        finally:
            await conn.close()

        # This article should NOT be in the overdue set
        assert art["id"] not in overdue_ids

    async def test_timeout_only_scans_reviewing(self, m4_db_path):
        """Only articles in 'reviewing' with expired deadline are picked up."""
        from datetime import datetime, timezone, timedelta
        past = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()

        # Create one in 'drafted' with past deadline (should be ignored)
        topic = await crud.create_topic("Drafted", source="user")
        art_drafted = await crud.create_article(topic["id"])
        conn = await crud.get_db()
        try:
            await conn.execute(
                "UPDATE article SET status = 'drafted', review_deadline_at = ?, updated_at = ? WHERE id = ?",
                (past, crud._now(), art_drafted["id"]),
            )
            await conn.commit()
        finally:
            await conn.close()

        # Create one in 'reviewing' with past deadline
        art_reviewing = await _create_article_with_deadline("reviewing", past)

        now = datetime.now(timezone.utc).isoformat()
        conn = await crud.get_db()
        try:
            cursor = await conn.execute(
                "SELECT * FROM article WHERE status = 'reviewing' AND review_deadline_at <= ?",
                (now,),
            )
            rows = await cursor.fetchall()
            overdue = [dict(r) for r in rows]
        finally:
            await conn.close()

        overdue_ids = {a["id"] for a in overdue}
        assert art_reviewing["id"] in overdue_ids
        assert art_drafted["id"] not in overdue_ids
