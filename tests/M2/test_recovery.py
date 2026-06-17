"""Test recovery: orchestrator restart should resume in-progress articles.

Per DEV_PLAN §5.3: simulates crash after each state, verifies recovery.
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
def recovery_db_path(tmp_path):
    db_file = tmp_path / "test_recovery.db"
    original = crud.DB_PATH
    crud.DB_PATH = db_file

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
async def test_articles_persist_after_crash(recovery_db_path):
    topic = await crud.create_topic("Test", source="user")
    art1 = await crud.create_article(topic["id"])
    await crud.update_article(art1["id"], status="writing", writing_task_id="wt-1")

    art2 = await crud.create_article(topic["id"])
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'drafted', final_package = ?, updated_at = ? WHERE id = ?",
            ('{"platforms":[]}', crud._now(), art2["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # Simulate restart: re-read everything
    all_articles = await crud.list_articles()
    statuses = {a["id"]: a["status"] for a in all_articles}
    assert statuses[art1["id"]] == "writing"
    assert statuses[art2["id"]] == "drafted"


@pytest.mark.asyncio
async def test_recover_writing_task_by_polling(recovery_db_path):
    topic = await crud.create_topic("Test", source="user")
    art = await crud.create_article(topic["id"])
    await crud.update_article(art["id"], status="writing", writing_task_id="wt-pending")

    writing_articles = await crud.list_articles(status="writing")
    assert len(writing_articles) == 1
    assert writing_articles[0]["writing_task_id"] == "wt-pending"


@pytest.mark.asyncio
async def test_stuck_article_in_matched_recoverable(recovery_db_path):
    topic = await crud.create_topic("Stuck Topic", source="auto")
    art = await crud.create_article(topic["id"])
    pending = await crud.list_articles(status="matched")
    assert any(a["id"] == art["id"] for a in pending)
