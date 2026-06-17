"""Tests for GET /api/articles/{id} — detail with score + publish + asset.

Per DEV_PLAN M3.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud


@pytest.fixture
def m3_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m3_detail.db"
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
class TestArticleDetail:
    async def test_detail_includes_topic(self, m3_db_path):
        topic = await crud.create_topic("Detail Test", source="user")
        art = await crud.create_article(topic["id"])
        art_detail = await crud.get_article(art["id"])
        topic_detail = await crud.get_topic(art_detail["topic_id"])
        assert topic_detail["title"] == "Detail Test"

    async def test_detail_includes_scores(self, m3_db_path):
        topic = await crud.create_topic("Scored Article", source="user")
        art = await crud.create_article(topic["id"])
        await crud.create_score(art["id"], "wechat", 88, "Great for wechat")
        await crud.create_score(art["id"], "toutiao", 72, "OK for toutiao")

        scores = await crud.get_latest_scores_for_article(art["id"])
        platforms = {s["platform"] for s in scores}
        assert "wechat" in platforms
        assert "toutiao" in platforms

    async def test_detail_includes_publishes(self, m3_db_path):
        topic = await crud.create_topic("Published Article", source="user")
        art = await crud.create_article(topic["id"])
        await crud.create_publish(art["id"], "toutiao", status="success")
        await crud.create_publish(art["id"], "wechat", status="failed")

        pubs = await crud.get_publishes_for_article(art["id"])
        assert len(pubs) == 2
        statuses = {p["platform"]: p["status"] for p in pubs}
        assert statuses["toutiao"] == "success"
        assert statuses["wechat"] == "failed"

    async def test_detail_score_generation_n(self, m3_db_path):
        """Multiple score generations should all be retrievable."""
        topic = await crud.create_topic("Multi Gen", source="user")
        art = await crud.create_article(topic["id"])
        await crud.create_score(art["id"], "wechat", 70, "gen1", generation_n=1)
        await crud.create_score(art["id"], "wechat", 80, "gen2", generation_n=2)

        all_scores = await crud.get_scores_for_article(art["id"])
        assert len(all_scores) == 2

        latest = await crud.get_latest_scores_for_article(art["id"])
        assert len(latest) == 1
        assert latest[0]["score"] == 80
