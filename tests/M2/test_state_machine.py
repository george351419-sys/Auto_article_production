"""Tests for state_machine.py — 11 states, valid/invalid transitions, audit_log.

Per DEV_PLAN §5.3: uses in-memory SQLite, no real network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import state_machine as sm


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_sm.db"


async def _setup_db(db_path) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("""
        CREATE TABLE article (
            id TEXT PRIMARY KEY, topic_id TEXT, character_id TEXT,
            status TEXT NOT NULL, writing_task_id TEXT, final_package TEXT,
            retry_count INTEGER DEFAULT 0, next_retry_at TEXT,
            last_error_code TEXT, last_error_message TEXT,
            review_deadline_at TEXT, trace_id TEXT,
            created_at TEXT, updated_at TEXT
        )
    """)
    await conn.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            from_state TEXT, to_state TEXT NOT NULL,
            trigger TEXT NOT NULL, actor TEXT, payload_json TEXT,
            trace_id TEXT NOT NULL, at TEXT NOT NULL
        )
    """)
    await conn.execute(
        "INSERT INTO article (id, topic_id, status, trace_id, created_at, updated_at) "
        "VALUES ('a1', 't1', 'collected', 'tr1', '2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')"
    )
    await conn.commit()
    return conn


@pytest.mark.asyncio
async def test_collected_to_matched_valid(db_path):
    conn = await _setup_db(db_path)
    await sm.transition_article(conn, "a1", "matched", "auto")
    cursor = await conn.execute("SELECT status FROM article WHERE id = 'a1'")
    row = await cursor.fetchone()
    assert row["status"] == "matched"
    await conn.close()


@pytest.mark.asyncio
async def test_collected_to_writing_invalid(db_path):
    conn = await _setup_db(db_path)
    with pytest.raises(sm.StateMachineError, match="Illegal transition"):
        await sm.transition_article(conn, "a1", "writing", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_collected_to_scored_invalid(db_path):
    conn = await _setup_db(db_path)
    with pytest.raises(sm.StateMachineError):
        await sm.transition_article(conn, "a1", "scored", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_audit_log_written_on_transition(db_path):
    conn = await _setup_db(db_path)
    await sm.transition_article(conn, "a1", "matched", "auto")
    cursor = await conn.execute("SELECT * FROM audit_log WHERE entity_id = 'a1'")
    row = await cursor.fetchone()
    assert row is not None
    assert row["entity_type"] == "article"
    assert row["from_state"] == "collected"
    assert row["to_state"] == "matched"
    assert row["trigger"] == "auto"
    assert row["trace_id"] is not None
    await conn.close()


@pytest.mark.asyncio
async def test_unknown_from_state_raises(db_path):
    conn = await _setup_db(db_path)
    await conn.execute("UPDATE article SET status = 'bogus' WHERE id = 'a1'")
    await conn.commit()
    with pytest.raises(sm.StateMachineError, match="Unknown state"):
        await sm.transition_article(conn, "a1", "matched", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_unknown_to_state_raises(db_path):
    conn = await _setup_db(db_path)
    with pytest.raises(sm.StateMachineError, match="Unknown state"):
        await sm.transition_article(conn, "a1", "bogus", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_entity_not_found_raises(db_path):
    conn = await _setup_db(db_path)
    with pytest.raises(sm.StateMachineError, match="not found"):
        await sm.transition_article(conn, "non-existent", "matched", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_full_happy_path(db_path):
    conn = await _setup_db(db_path)
    path = ["matched", "writing", "drafted", "scored", "reviewing",
            "publishing", "published"]
    for status in path:
        await sm.transition_article(conn, "a1", status, "auto")

    cursor = await conn.execute("SELECT status FROM article WHERE id = 'a1'")
    row = await cursor.fetchone()
    assert row["status"] == "published"

    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM audit_log WHERE entity_id = 'a1'")
    row = await cursor.fetchone()
    assert row["cnt"] == 7
    await conn.close()


@pytest.mark.asyncio
async def test_published_is_terminal(db_path):
    conn = await _setup_db(db_path)
    for status in ["matched", "writing", "drafted", "scored", "reviewing",
                   "publishing", "published"]:
        await sm.transition_article(conn, "a1", status, "auto")
    with pytest.raises(sm.StateMachineError):
        await sm.transition_article(conn, "a1", "drafted", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_rejected_is_terminal(db_path):
    conn = await _setup_db(db_path)
    await conn.execute(
        "INSERT INTO article (id, topic_id, status, trace_id, created_at, updated_at) "
        "VALUES ('a2', 't2', 'rejected', 'tr2', '2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')")
    await conn.commit()
    with pytest.raises(sm.StateMachineError):
        await sm.transition_article(conn, "a2", "drafted", "auto")
    await conn.close()


@pytest.mark.asyncio
async def test_failed_can_retry_to_previous_state(db_path):
    conn = await _setup_db(db_path)
    await sm.transition_article(conn, "a1", "matched", "auto")
    await sm.transition_article(conn, "a1", "writing", "auto")
    await sm.transition_article(conn, "a1", "failed", "auto")
    await sm.transition_article(conn, "a1", "writing", "retry")
    await conn.close()


@pytest.mark.asyncio
async def test_failed_cannot_go_to_unrelated_state(db_path):
    conn = await _setup_db(db_path)
    await sm.transition_article(conn, "a1", "matched", "auto")
    await sm.transition_article(conn, "a1", "failed", "auto")
    with pytest.raises(sm.StateMachineError):
        await sm.transition_article(conn, "a1", "collected", "retry")
    await conn.close()


class TestValidationFunction:
    def test_validate_transition_known_states(self):
        sm.validate_transition("collected", "matched")
        sm.validate_transition("drafted", "scored")

    def test_validate_transition_rejects_illegal(self):
        with pytest.raises(sm.StateMachineError):
            sm.validate_transition("collected", "published")

    def test_validate_transition_rejects_unknown_from(self):
        with pytest.raises(sm.StateMachineError):
            sm.validate_transition("bogus", "matched")

    def test_validate_transition_rejects_unknown_to(self):
        with pytest.raises(sm.StateMachineError):
            sm.validate_transition("collected", "bogus")
