"""Tests for CRUD operations on topic, article, publish tables.

Per DEV_PLAN §5.3: uses in-memory SQLite via temp files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud


@pytest.fixture
def crud_db_path(tmp_path):
    """Set crud to use a temp DB, run migrations, then restore."""
    db_file = tmp_path / "test_crud.db"
    original = crud.DB_PATH
    crud.DB_PATH = db_file

    # Run migration
    import asyncio
    mig_path = Path(__file__).resolve().parent.parent.parent / "orchestrator" / "migrations" / "0001_init.sql"
    sql = mig_path.read_text()

    async def _init():
        conn = await aiosqlite.connect(str(db_file))
        conn.row_factory = aiosqlite.Row
        await conn.executescript(sql)
        await conn.commit()
        await conn.close()
    asyncio.run(_init())

    yield db_file

    crud.DB_PATH = original
    db_file.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_create_topic(crud_db_path):
    topic = await crud.create_topic("AI大模型改变世界", source="user", brief="测试选题", user_submitted=1)
    assert topic["id"] is not None
    assert topic["title"] == "AI大模型改变世界"
    assert topic["status"] == "collected"
    assert topic["user_submitted"] == 1


@pytest.mark.asyncio
async def test_create_topic_normalizes_title(crud_db_path):
    topic = await crud.create_topic("AI大模型！改变世界？", source="user")
    normalized = crud._normalize_title("AI大模型！改变世界？")
    assert topic["title_normalized"] == normalized
    assert "！" not in normalized
    assert "？" not in normalized


@pytest.mark.asyncio
async def test_get_topic(crud_db_path):
    created = await crud.create_topic("测试选题", source="user")
    fetched = await crud.get_topic(created["id"])
    assert fetched is not None
    assert fetched["title"] == "测试选题"


@pytest.mark.asyncio
async def test_get_topic_not_found(crud_db_path):
    assert await crud.get_topic("non-existent") is None


@pytest.mark.asyncio
async def test_list_topics(crud_db_path):
    await crud.create_topic("Topic 1", source="user")
    await crud.create_topic("Topic 2", source="auto")
    topics = await crud.list_topics()
    assert len(topics) == 2


@pytest.mark.asyncio
async def test_list_topics_filter_by_status(crud_db_path):
    await crud.create_topic("Topic A", source="user")
    topics = await crud.list_topics(status="collected")
    assert all(t["status"] == "collected" for t in topics)


@pytest.mark.asyncio
async def test_update_topic_status(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    updated = await crud.update_topic_status(topic["id"], "matched")
    assert updated["status"] == "matched"


@pytest.mark.asyncio
async def test_create_article(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    article = await crud.create_article(topic["id"], character_id="c1")
    assert article["id"] is not None
    assert article["status"] == "matched"
    assert article["topic_id"] == topic["id"]


@pytest.mark.asyncio
async def test_get_article(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    fetched = await crud.get_article(art["id"])
    assert fetched["id"] == art["id"]


@pytest.mark.asyncio
async def test_list_articles_filter_by_status(crud_db_path):
    topic = await crud.create_topic("T1", source="user")
    await crud.create_article(topic["id"])
    articles = await crud.list_articles(status="matched")
    assert len(articles) >= 1


@pytest.mark.asyncio
async def test_update_article(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    updated = await crud.update_article(art["id"], status="writing", writing_task_id="wt-1")
    assert updated["status"] == "writing"
    assert updated["writing_task_id"] == "wt-1"


@pytest.mark.asyncio
async def test_create_score(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    score = await crud.create_score(art["id"], "wechat", 80, "深度长文")
    assert score["score"] == 80
    assert score["platform"] == "wechat"


@pytest.mark.asyncio
async def test_multiple_generations(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    await crud.create_score(art["id"], "wechat", 80, "first", generation_n=1)
    await crud.create_score(art["id"], "wechat", 85, "second", generation_n=2)
    scores = await crud.get_scores_for_article(art["id"])
    assert len(scores) == 2


@pytest.mark.asyncio
async def test_get_latest_scores(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    await crud.create_score(art["id"], "wechat", 80, "gen1", generation_n=1)
    await crud.create_score(art["id"], "wechat", 85, "gen2", generation_n=2)
    latest = await crud.get_latest_scores_for_article(art["id"])
    assert len(latest) == 1
    assert latest[0]["score"] == 85


@pytest.mark.asyncio
async def test_create_publish(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    pub = await crud.create_publish(art["id"], "toutiao")
    assert pub["status"] == "pending"
    assert pub["platform"] == "toutiao"


@pytest.mark.asyncio
async def test_update_publish(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    pub = await crud.create_publish(art["id"], "toutiao")
    updated = await crud.update_publish(pub["id"], status="success",
                                         platform_url="https://example.com")
    assert updated["status"] == "success"
    assert updated["platform_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_dashboard_stats(crud_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    stats = await crud.get_dashboard_stats()
    assert "today_published" in stats
    assert "pending_review" in stats
    assert "failed" in stats
    assert "by_status" in stats
