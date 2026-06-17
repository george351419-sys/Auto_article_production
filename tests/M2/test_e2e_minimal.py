"""End-to-end minimal path test — collected → published with all mocks.

Per DEV_PLAN §5.3: mocks all external modules, exercises the full state machine.
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
def e2e_db_path(tmp_path):
    """Set up crud with a temp DB that has full schema."""
    db_file = tmp_path / "test_e2e.db"
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
async def test_full_path_collected_to_published(e2e_db_path):
    # 1. User submits topic → collected
    topic = await crud.create_topic("DeepSeek融资500亿", source="user", brief="AI大模型融资")
    assert topic["status"] == "collected"

    # 2. Create article → matched
    article = await crud.create_article(topic["id"], character_id="c1")
    assert article["status"] == "matched"

    # 3. matched → writing
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'writing', writing_task_id = 'wt-1', updated_at = ? WHERE id = ?",
            (crud._now(), article["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # 4. writing → drafted
    conn = await crud.get_db()
    try:
        fp = {"platforms": [{"platform": "toutiao", "titles": ["测试"],
                             "formattedArticle": "# Test"}]}
        await conn.execute(
            "UPDATE article SET status = 'drafted', final_package = ?, updated_at = ? WHERE id = ?",
            (json.dumps(fp, ensure_ascii=False), crud._now(), article["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # 5. drafted → scored
    await crud.create_score(article["id"], "toutiao", 85, "时效性强", generation_n=1)
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'scored', updated_at = ? WHERE id = ?",
            (crud._now(), article["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # 6. scored → reviewing
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'reviewing', review_deadline_at = ?, updated_at = ? WHERE id = ?",
            (crud._now(), crud._now(), article["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # 7. reviewing → publishing
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'publishing', updated_at = ? WHERE id = ?",
            (crud._now(), article["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # 8. publishing → published
    await crud.create_publish(article["id"], "toutiao", status="success")
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'published', updated_at = ? WHERE id = ?",
            (crud._now(), article["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()

    # Verify
    final = await crud.get_article(article["id"])
    assert final["status"] == "published"

    scores = await crud.get_latest_scores_for_article(article["id"])
    assert len(scores) >= 1
    assert scores[0]["platform"] == "toutiao"

    pubs = await crud.get_publishes_for_article(article["id"])
    assert len(pubs) == 1


@pytest.mark.asyncio
async def test_user_submitted_topic_flag(e2e_db_path):
    topic = await crud.create_topic(
        "用户手动选题", source="user", brief="手动测试", user_submitted=1,
    )
    assert topic["user_submitted"] == 1
    article = await crud.create_article(topic["id"])
    assert article["topic_id"] == topic["id"]
    assert article["status"] == "matched"


@pytest.mark.asyncio
async def test_title_normalization_dedup(e2e_db_path):
    t1 = await crud.create_topic("AI大模型改变世界", source="auto")
    t2 = await crud.create_topic("AI大模型！改变世界？", source="auto")
    assert crud._normalize_title("AI大模型改变世界") == crud._normalize_title("AI大模型！改变世界？")
    assert t1["title_normalized"] == t2["title_normalized"]
