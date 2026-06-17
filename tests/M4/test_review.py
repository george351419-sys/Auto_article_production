"""Tests for POST /api/articles/{id}/review — approve, reject, modifications.

Per DEV_PLAN M4.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud
import state_machine as sm


@pytest.fixture
def m4_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m4.db"
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


async def _create_reviewing_article():
    topic = await crud.create_topic("Review Test", source="user")
    art = await crud.create_article(topic["id"])
    fp = json.dumps({"platforms": [
        {"platform": "wechat", "titles": ["原标题"], "formattedArticle": "原正文",
         "formatted_article": "原正文", "tags": ["AI"]}
    ]}, ensure_ascii=False)
    conn = await crud.get_db()
    try:
        await conn.execute(
            "UPDATE article SET status = 'reviewing', final_package = ?, "
            "review_deadline_at = ?, updated_at = ? WHERE id = ?",
            (fp, "2026-06-16T14:00:00Z", crud._now(), art["id"]),
        )
        await conn.commit()
    finally:
        await conn.close()
    return art


async def _get_article_status(aid: str) -> str:
    art = await crud.get_article(aid)
    return art["status"] if art else "not-found"


@pytest.mark.asyncio
class TestReviewApprove:
    async def test_approve_transitions_to_publishing(self, m4_db_path):
        art = await _create_reviewing_article()
        conn = await crud.get_db()
        try:
            await sm.transition_article(conn, art["id"], "publishing", "user",
                                        actor="reviewer", payload={"action": "approve"})
            await conn.commit()
        finally:
            await conn.close()
        assert await _get_article_status(art["id"]) == "publishing"

    async def test_approve_writes_audit_log(self, m4_db_path):
        art = await _create_reviewing_article()
        conn = await crud.get_db()
        try:
            await sm.transition_article(conn, art["id"], "publishing", "user",
                                        actor="reviewer")
            await conn.commit()
            cursor = await conn.execute(
                "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY id DESC LIMIT 1",
                (art["id"],),
            )
            log = await cursor.fetchone()
            assert log["entity_type"] == "article"
            assert log["to_state"] == "publishing"
            assert log["trigger"] == "user"
        finally:
            await conn.close()


@pytest.mark.asyncio
class TestReviewReject:
    async def test_reject_transitions_to_rejected(self, m4_db_path):
        art = await _create_reviewing_article()
        conn = await crud.get_db()
        try:
            await sm.transition_article(conn, art["id"], "rejected", "user",
                                        actor="reviewer")
            await conn.commit()
        finally:
            await conn.close()
        assert await _get_article_status(art["id"]) == "rejected"

    async def test_rejected_is_terminal(self, m4_db_path):
        art = await _create_reviewing_article()
        conn = await crud.get_db()
        try:
            await sm.transition_article(conn, art["id"], "rejected", "user")
            await conn.commit()
        finally:
            await conn.close()
        conn = await crud.get_db()
        try:
            with pytest.raises(sm.StateMachineError):
                await sm.transition_article(conn, art["id"], "publishing", "auto")
        finally:
            await conn.close()


@pytest.mark.asyncio
class TestReviewModifications:
    async def test_modifications_applied_to_final_package(self, m4_db_path):
        art = await _create_reviewing_article()
        # Re-fetch to ensure final_package is parsed
        art = await crud.get_article(art["id"])
        fp = art.get("final_package") or {}
        if isinstance(fp, str):
            fp = json.loads(fp)

        # Apply modification
        for pp in fp.get("platforms", []):
            if pp.get("platform") == "wechat":
                pp["titles"][0] = "修改后的标题"
                pp["formattedArticle"] = "修改后的正文"
                pp["formatted_article"] = "修改后的正文"

        conn = await crud.get_db()
        try:
            await conn.execute(
                "UPDATE article SET final_package = ?, updated_at = ? WHERE id = ?",
                (json.dumps(fp, ensure_ascii=False), crud._now(), art["id"]),
            )
            await conn.commit()
        finally:
            await conn.close()

        updated = await crud.get_article(art["id"])
        updated_fp = json.loads(updated["final_package"]) if isinstance(updated["final_package"], str) else updated["final_package"]
        wechat_pkg = [p for p in updated_fp["platforms"] if p["platform"] == "wechat"][0]
        assert wechat_pkg["titles"][0] == "修改后的标题"


@pytest.mark.asyncio
class TestReviewInvalidActions:
    async def test_review_on_non_reviewing_article(self, m4_db_path):
        topic = await crud.create_topic("Test", source="user")
        art = await crud.create_article(topic["id"])
        assert art["status"] == "matched"  # not reviewing
        conn = await crud.get_db()
        try:
            with pytest.raises(sm.StateMachineError):
                await sm.transition_article(conn, art["id"], "publishing", "user")
        finally:
            await conn.close()
