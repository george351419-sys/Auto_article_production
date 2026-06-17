"""Tests for L1 dedup — 7-day window boundary.

Per DEV_PLAN M6.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import crud
import dedup


@pytest.fixture
def m6_db_path(tmp_path, monkeypatch):
    db_file = tmp_path / "test_m6_l1.db"
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
class TestL1Dedup:
    async def test_exact_match_within_7_days(self, m6_db_path):
        t1 = await crud.create_topic("AI大模型改变世界", source="auto")
        assert t1["status"] == "collected"

        # Run dedup on a second identical topic
        t2 = await crud.create_topic("AI大模型改变世界", source="auto")
        result = await dedup.run_dedup(t2["id"])
        assert result["duplicated"] is True
        assert result["dup_of"] == t1["id"]
        assert result["method"] == "L1"

    async def test_same_title_different_punctuation_matches(self, m6_db_path):
        """Titles that differ only in punctuation should L1 match."""
        await crud.create_topic("DeepSeek完成500亿融资", source="auto")
        t2 = await crud.create_topic("DeepSeek完成500亿融资！", source="auto")
        result = await dedup.run_dedup(t2["id"])
        assert result["duplicated"] is True

    async def test_different_title_no_match(self, m6_db_path):
        await crud.create_topic("AI大模型改变世界", source="auto")
        t2 = await crud.create_topic("量子计算突破进展", source="auto")
        result = await dedup.run_dedup(t2["id"])
        assert result["duplicated"] is False

    async def test_duplicate_marks_status(self, m6_db_path):
        await crud.create_topic("重复选题测试", source="auto")
        t2 = await crud.create_topic("重复选题测试", source="auto")
        await dedup.run_dedup(t2["id"])
        updated = await crud.get_topic(t2["id"])
        assert updated["status"] == "duplicated"
