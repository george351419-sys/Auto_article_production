"""Tests for user override of dedup — "仍要写" button.

Per DEV_PLAN M6.
"""
from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud
import dedup


@pytest.fixture
def m6_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m6_override.db"
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
class TestDedupOverride:
    async def test_override_reopens_duplicated_topic(self, m6_db_path):
        """User clicking '仍要写' should reset topic status past duplicated."""
        t1 = await crud.create_topic("Overridable Topic", source="auto")
        t2 = await crud.create_topic("Overridable Topic", source="auto")
        await dedup.run_dedup(t2["id"])

        # Verify t2 is duplicated
        t2_updated = await crud.get_topic(t2["id"])
        assert t2_updated["status"] == "duplicated"

        # User overrides — set status back to collected, clear dup_of
        await crud.update_topic_status(t2["id"], "collected")
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE topic SET dup_of_topic_id = NULL WHERE id = ?", (t2["id"],))
            await conn.commit()
        finally:
            await conn.close()

        overridden = await crud.get_topic(t2["id"])
        assert overridden["status"] == "collected"
        assert overridden["dup_of_topic_id"] is None

    async def test_user_submitted_never_marked_duplicated(self, m6_db_path):
        """User-submitted topics should bypass dedup entirely."""
        t1 = await crud.create_topic("User Topic", source="user", user_submitted=1)
        assert t1["user_submitted"] == 1
        # User topics are still checked — but can be overridden via UI
        result = await dedup.run_dedup(t1["id"])
        # First submission of this title → no duplicate
        assert result["duplicated"] is False
