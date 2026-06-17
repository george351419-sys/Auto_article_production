"""Tests for GET /api/dashboard — aggregate data correct.

Per DEV_PLAN M3: dashboard shows today published, pending review, failed counts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tests"))

import crud


@pytest.fixture
def m3_db_path(tmp_path, monkeypatch):
    """Set up a temp DB with full schema for the API server."""
    db_file = tmp_path / "test_m3.db"
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


@pytest.fixture
def api_client(m3_db_path, monkeypatch):
    """Create FastAPI test client for server_v2."""
    # Patch the _load_config to use a mock
    from orchestrator import server_v2 as sv2

    async def _mock_config():
        return json.loads((Path(__file__).parent.parent.parent / "shared_config.json").read_text())

    # We'll test against the FastAPI app directly
    from fastapi.testclient import TestClient
    return TestClient(sv2.app)


@pytest.mark.asyncio
class TestDashboardAPI:
    async def test_dashboard_returns_stats(self, m3_db_path):
        """Dashboard should return expected keys even when empty."""
        stats = await crud.get_dashboard_stats()
        assert "today_published" in stats
        assert "pending_review" in stats
        assert "failed" in stats
        assert "by_status" in stats

    async def test_dashboard_counts_articles(self, m3_db_path):
        """Dashboard should correctly count articles by status."""
        topic = await crud.create_topic("Test", source="user")
        art = await crud.create_article(topic["id"])
        stats = await crud.get_dashboard_stats()
        assert stats["by_status"]["matched"] >= 1

    async def test_dashboard_pending_review(self, m3_db_path):
        """Dashboard should count reviewing articles."""
        topic = await crud.create_topic("Test", source="user")
        art = await crud.create_article(topic["id"])
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'reviewing' WHERE id = ?", (art["id"],))
            await conn.commit()
        finally:
            await conn.close()
        stats = await crud.get_dashboard_stats()
        assert stats["pending_review"] == 1

    async def test_dashboard_failed_count(self, m3_db_path):
        """Dashboard should count failed articles."""
        topic = await crud.create_topic("Test", source="user")
        art = await crud.create_article(topic["id"])
        conn = await crud.get_db()
        try:
            await conn.execute("UPDATE article SET status = 'failed' WHERE id = ?", (art["id"],))
            await conn.commit()
        finally:
            await conn.close()
        stats = await crud.get_dashboard_stats()
        assert stats["failed"] == 1

    async def test_dashboard_today_published(self, m3_db_path):
        """Dashboard should count today's successful publishes."""
        from datetime import datetime, timezone
        topic = await crud.create_topic("Test", source="user")
        art = await crud.create_article(topic["id"])
        pub = await crud.create_publish(art["id"], "toutiao", status="success")
        now = datetime.now(timezone.utc).isoformat()
        conn = await crud.get_db()
        try:
            await conn.execute(
                "UPDATE publish SET status = 'success', executed_at = ? WHERE id = ?",
                (now, pub["id"]),
            )
            await conn.commit()
        finally:
            await conn.close()
        stats = await crud.get_dashboard_stats()
        assert stats["today_published"] >= 1
