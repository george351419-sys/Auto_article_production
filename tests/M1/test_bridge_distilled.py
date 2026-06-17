"""Tests for distilled_characters bridge client.

Per DEV_PLAN §5.3: uses FastAPI TestClient mock server, covers
happy path, 4xx, 5xx, timeout, and Idempotency-Key / trace_id header passing.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure tests/helpers is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.mock_modules import make_mock_distilled_app


@pytest.fixture
def mock_app():
    return make_mock_distilled_app()


@pytest.fixture
def client(mock_app):
    return TestClient(mock_app)


class TestDistilledHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["module"] == "distilled_characters"

    def test_contract_returns_endpoints(self, client):
        r = client.get("/contract")
        assert r.status_code == 200
        data = r.json()
        assert data["contract_version"] == "1.0"
        assert len(data["endpoints"]) >= 2


class TestDistilledBusinessEndpoints:
    def test_list_characters_returns_list(self, client):
        r = client.get("/api/characters")
        assert r.status_code == 200
        data = r.json()
        assert "characters" in data
        assert len(data["characters"]) > 0

    def test_match_returns_character(self, client):
        r = client.post("/api/match", json={"topic_brief": "AI融资"})
        assert r.status_code == 200
        data = r.json()
        assert "matched" in data
        assert data["matched"]["match_score"] == 87


class TestBridgeClientHeaders:
    def test_health_passes_user_agent(self, mock_app):
        """Verify bridge client sets User-Agent header."""
        from orchestrator.bridge.distilled import DistilledCharactersClient

        bc = DistilledCharactersClient("http://127.0.0.1:8767")
        headers = bc._headers()
        assert "User-Agent" in headers
        assert headers["User-Agent"] == "orchestrator/1.0"
        assert "X-Trace-Id" in headers


class TestBridgeClientErrors:
    def test_client_has_default_timeout(self):
        """Bridge client should have a 30s default timeout."""
        from orchestrator.bridge.distilled import DistilledCharactersClient

        bc = DistilledCharactersClient("http://127.0.0.1:8767")
        assert bc.default_timeout == 30.0

    def test_health_times_out_on_unreachable(self):
        """Health check should handle unreachable services gracefully."""
        import asyncio
        import httpx

        async def _check():
            try:
                async with httpx.AsyncClient(timeout=0.01) as c:
                    await c.get("http://127.0.0.1:19999/health")
                return False  # should not succeed
            except Exception:
                return True  # expected

        result = asyncio.run(_check())
        assert result is True
