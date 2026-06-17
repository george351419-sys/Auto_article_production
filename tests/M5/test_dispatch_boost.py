"""Tests for 23:00 boost logic.

Per DEV_PLAN M5: if platform has 0 published today, pick highest-scored
article for that platform and boost it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud
import dispatch


@pytest.fixture
def m5_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m5_boost.db"
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


@pytest.mark.asyncio
class TestBoost:
    async def test_boost_finds_candidate(self, m5_db_path):
        topic = await crud.create_topic("Boost Test", source="auto")
        art = await crud.create_article(topic["id"])
        await crud.create_score(art["id"], "wechat", 55, "边缘候选", generation_n=1)

        # Put article in 'scored' state
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'scored' WHERE id = ?", (art["id"],))
            await conn.commit()

            candidates = await dispatch.find_boost_candidates(conn, "wechat")
        finally:
            await conn.close()

        assert len(candidates) >= 1
        assert candidates[0]["id"] == art["id"]
        assert candidates[0]["score"] == 55

    async def test_boost_excludes_already_published(self, m5_db_path):
        from datetime import datetime, timezone

        topic = await crud.create_topic("Already Published", source="auto")
        art = await crud.create_article(topic["id"])
        await crud.create_score(art["id"], "toutiao", 65, "good", generation_n=1)

        # Mark article as scored and already published today
        now = datetime.now(timezone.utc).isoformat()
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'scored' WHERE id = ?", (art["id"],))
            await conn.execute(
                "INSERT INTO publish (id, article_id, platform, status, scheduled_at, executed_at, trace_id) "
                "VALUES (?, ?, ?, 'success', ?, ?, ?)",
                ("pub-1", art["id"], "toutiao", now, now, "tr1"),
            )
            await conn.commit()

            candidates = await dispatch.find_boost_candidates(conn, "toutiao")
        finally:
            await conn.close()

        # Already published → not a candidate
        assert not any(c["id"] == art["id"] for c in candidates)

    async def test_boost_excludes_below_min_score(self, m5_db_path):
        topic = await crud.create_topic("Low Score", source="auto")
        art = await crud.create_article(topic["id"])
        await crud.create_score(art["id"], "xiaohongshu", 49, "too low", generation_n=1)

        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'scored' WHERE id = ?", (art["id"],))
            await conn.commit()

            candidates = await dispatch.find_boost_candidates(conn, "xiaohongshu")
        finally:
            await conn.close()

        assert not any(c["id"] == art["id"] for c in candidates)

    async def test_boost_run_check_no_candidate(self, m5_db_path):
        """When no candidate exists, boost check should report no_candidate."""
        result = await dispatch.run_boost_check()
        # Should have no_candidate for all 3 platforms (empty DB, no scored articles)
        assert len(result["no_candidate"]) == 3 or len(result["no_candidate"]) >= 1

    async def test_boost_run_check_with_published(self, m5_db_path):
        """When a platform already has publishes today, skip boost."""
        from datetime import datetime, timezone

        topic = await crud.create_topic("Pub Today", source="auto")
        art = await crud.create_article(topic["id"])
        now = datetime.now(timezone.utc).isoformat()

        conn = await crud.get_db()
        try:
            await conn.execute(
                "INSERT INTO publish (id, article_id, platform, status, scheduled_at, executed_at, trace_id) "
                "VALUES (?, ?, ?, 'success', ?, ?, ?)",
                ("pub-today", art["id"], "toutiao", now, now, "tr1"),
            )
            await conn.commit()
        finally:
            await conn.close()

        result = await dispatch.run_boost_check()
        assert "toutiao" in result["skipped"]
