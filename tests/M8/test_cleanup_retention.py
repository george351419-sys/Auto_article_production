"""Tests for cleanup retention rules.

Per DEV_PLAN M8: verify each data category's retention boundary.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud
import cleanup


@pytest.fixture
def m8_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m8_cleanup.db"
    monkeypatch.setattr(crud, "DB_PATH", db_file)
    # Also redirect lock file
    monkeypatch.setattr(cleanup, "SWEEP_LOCK_FILE", tmp_path / ".cleanup_lock")

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


@pytest.mark.asyncio
class TestCleanupRetention:
    async def test_published_asset_within_7_days_preserved(self, m8_db_path):
        """Assets downloaded <7 days ago should not be expired."""
        topic = await crud.create_topic("Test", source="auto")
        art = await crud.create_article(topic["id"])
        # Set article as published
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'published' WHERE id = ?", (art["id"],))
            # Insert a recent asset
            now = crud._now()
            await conn.execute(
                "INSERT INTO asset (id, article_id, platform, kind, local_path, origin_url, bytes, sha256, downloaded_at) "
                "VALUES (?, ?, 'toutiao', 'cover', '/tmp/test.png', 'https://oss.example.com/test.png', 1024, 'abc', ?)",
                ("ast-1", art["id"], now),
            )
            await conn.commit()

            expired = await cleanup.find_expired_assets(conn, retention_days=7)
        finally:
            await conn.close()

        assert "ast-1" not in expired

    async def test_published_asset_beyond_7_days_expired(self, m8_db_path):
        """Assets downloaded >7 days ago should be expired."""
        topic = await crud.create_topic("Old", source="auto")
        art = await crud.create_article(topic["id"])
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'published' WHERE id = ?", (art["id"],))
            await conn.execute(
                "INSERT INTO asset (id, article_id, platform, kind, local_path, origin_url, bytes, sha256, downloaded_at) "
                "VALUES (?, ?, 'toutiao', 'cover', '/tmp/old.png', 'https://oss.example.com/old.png', 1024, 'abc', ?)",
                ("ast-old", art["id"], old_date),
            )
            await conn.commit()

            expired = await cleanup.find_expired_assets(conn, retention_days=7)
        finally:
            await conn.close()

        assert "ast-old" in expired

    async def test_duplicated_topic_within_7_days_preserved(self, m8_db_path):
        """Duplicated topics <7 days old are preserved."""
        topic = await crud.create_topic("Dup Recent", source="auto")
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE topic SET status = 'duplicated' WHERE id = ?", (topic["id"],))
            await conn.commit()
            expired = await cleanup.find_expired_duplicated_topics(conn)
        finally:
            await conn.close()
        assert topic["id"] not in expired


@pytest.mark.asyncio
class TestCleanupSafety:
    async def test_user_submitted_topic_not_deleted(self, m8_db_path):
        """User-submitted duplicated topics are never cleaned up."""
        topic = await crud.create_topic("User Dup", source="user", user_submitted=1)
        old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        conn = await crud.get_db()
        try:
            await conn.execute(
                "UPDATE topic SET status = 'duplicated', created_at = ? WHERE id = ?",
                (old_date, topic["id"]),
            )
            await conn.commit()
            expired = await cleanup.find_expired_duplicated_topics(conn)
        finally:
            await conn.close()
        # User-submitted topics are excluded by user_submitted=0 filter
        assert topic["id"] not in expired

    async def test_scored_article_never_cleaned(self, m8_db_path):
        """Articles in 'scored' state are permanent — never cleaned."""
        topic = await crud.create_topic("Scored Keep", source="auto")
        art = await crud.create_article(topic["id"])
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        conn = await crud.get_db()
        try:
            await conn.execute(
                "UPDATE article SET status = 'scored', created_at = ? WHERE id = ?",
                (old_date, art["id"]),
            )
            await conn.commit()
            expired = await cleanup.find_expired_rejected_articles(conn)
        finally:
            await conn.close()
        assert art["id"] not in expired
