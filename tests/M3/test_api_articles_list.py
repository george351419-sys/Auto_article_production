"""Tests for GET /api/articles — list + status/source filter + pagination.

Per DEV_PLAN M3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tests"))

import crud


@pytest.fixture
def m3_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m3_articles.db"
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
class TestArticlesAPI:
    async def test_list_articles_empty(self, m3_db_path):
        articles = await crud.list_articles()
        assert articles == []

    async def test_list_articles_with_data(self, m3_db_path):
        topic = await crud.create_topic("T1", source="user")
        await crud.create_article(topic["id"])
        await crud.create_article(topic["id"])
        articles = await crud.list_articles()
        assert len(articles) == 2

    async def test_list_articles_filter_by_status(self, m3_db_path):
        topic = await crud.create_topic("T1", source="user")
        art1 = await crud.create_article(topic["id"])
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'published' WHERE id = ?", (art1["id"],))
            await conn.commit()
        finally:
            await conn.close()

        matching = await crud.list_articles(status="published")
        assert all(a["status"] == "published" for a in matching)
        assert len(matching) >= 1

    async def test_list_articles_limit_offset(self, m3_db_path):
        topic = await crud.create_topic("T1", source="user")
        for i in range(5):
            await crud.create_article(topic["id"])

        page1 = await crud.list_articles(limit=3, offset=0)
        assert len(page1) == 3

        page2 = await crud.list_articles(limit=3, offset=3)
        assert len(page2) == 2

    async def test_get_article_not_found(self, m3_db_path):
        assert await crud.get_article("non-existent") is None

    async def test_get_article_detail(self, m3_db_path):
        topic = await crud.create_topic("Test Detail", source="user", brief="Test brief")
        art = await crud.create_article(topic["id"])
        await crud.create_score(art["id"], "wechat", 85, "Good")
        await crud.create_publish(art["id"], "wechat", status="success")

        fetched = await crud.get_article(art["id"])
        assert fetched["topic_id"] == topic["id"]

        scores = await crud.get_latest_scores_for_article(art["id"])
        assert len(scores) == 1
        assert scores[0]["score"] == 85

        pubs = await crud.get_publishes_for_article(art["id"])
        assert len(pubs) == 1
