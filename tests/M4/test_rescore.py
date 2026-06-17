"""Tests for POST /api/articles/{id}/rescore — generation_n increment.

Per DEV_PLAN M4.
"""
from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud


@pytest.fixture
def m4_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m4_rescore.db"
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


async def _create_article():
    topic = await crud.create_topic("Rescore Test", source="user")
    return await crud.create_article(topic["id"])


@pytest.mark.asyncio
class TestRescore:
    async def test_rescore_creates_higher_generation(self, m4_db_path):
        art = await _create_article()
        await crud.create_score(art["id"], "wechat", 80, "gen1", generation_n=1)
        await crud.create_score(art["id"], "wechat", 85, "gen2", generation_n=2)

        latest = await crud.get_latest_scores_for_article(art["id"])
        assert len(latest) == 1
        assert latest[0]["generation_n"] == 2
        assert latest[0]["score"] == 85

    async def test_old_generations_preserved(self, m4_db_path):
        art = await _create_article()
        await crud.create_score(art["id"], "wechat", 75, "gen1", generation_n=1)
        await crud.create_score(art["id"], "wechat", 90, "gen2", generation_n=2)

        all_scores = await crud.get_scores_for_article(art["id"])
        assert len(all_scores) == 2
        gens = {s["generation_n"] for s in all_scores}
        assert 1 in gens
        assert 2 in gens

    async def test_rescore_multiple_platforms(self, m4_db_path):
        art = await _create_article()
        for p in ["wechat", "xiaohongshu", "toutiao"]:
            await crud.create_score(art["id"], p, 70, "gen1", generation_n=1)

        latest = await crud.get_latest_scores_for_article(art["id"])
        assert len(latest) == 3
        platforms = {s["platform"] for s in latest}
        assert platforms == {"wechat", "xiaohongshu", "toutiao"}

    async def test_rescore_unique_constraint(self, m4_db_path):
        """Same article+platform+generation should be unique."""
        art = await _create_article()
        await crud.create_score(art["id"], "wechat", 80, "first", generation_n=1)

        # Second insert with same (article_id, platform, generation_n) should fail
        with pytest.raises(Exception):
            await crud.create_score(art["id"], "wechat", 85, "duplicate", generation_n=1)
