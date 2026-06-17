"""Tests for platform_scorer bridge client and mock mode.

Per DEV_PLAN §5.3: uses FastAPI TestClient mock server.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.mock_modules import make_mock_scorer_app


@pytest.fixture
def mock_app():
    return make_mock_scorer_app()


@pytest.fixture
def client(mock_app):
    return TestClient(mock_app)


class TestScorerHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["module"] == "platform_scorer"

    def test_contract_returns_endpoints(self, client):
        r = client.get("/contract")
        assert r.status_code == 200
        data = r.json()
        endpoints = {(ep["method"], ep["path"]) for ep in data["endpoints"]}
        assert ("POST", "/api/score") in endpoints


class TestScorerMockMode:
    """Test that mock mode returns fixed scores for all 3 platforms."""

    def test_score_returns_three_platforms(self, client):
        r = client.post("/api/score", json={
            "article_id": "test-1",
            "topic_brief": "AI大模型改变工作方式",
            "platforms": ["wechat", "xiaohongshu", "toutiao"],
            "package_summary": {"platforms": []},
        })
        assert r.status_code == 200
        data = r.json()
        scores = data["scores"]
        assert "wechat" in scores
        assert "xiaohongshu" in scores
        assert "toutiao" in scores

    def test_mock_scores_are_fixed_values(self, client):
        r = client.post("/api/score", json={
            "article_id": "test-2",
            "topic_brief": "任意选题",
            "platforms": ["wechat", "xiaohongshu", "toutiao"],
            "package_summary": {"platforms": []},
        })
        assert r.status_code == 200
        scores = r.json()["scores"]
        assert scores["wechat"]["score"] == 80
        assert scores["xiaohongshu"]["score"] == 70
        assert scores["toutiao"]["score"] == 60

    def test_each_score_has_reason(self, client):
        r = client.post("/api/score", json={
            "article_id": "test-3",
            "topic_brief": "测试",
            "platforms": ["wechat"],
            "package_summary": {"platforms": []},
        })
        assert r.status_code == 200
        scores = r.json()["scores"]
        assert "reason" in scores["wechat"]
        assert len(scores["wechat"]["reason"]) > 0

    def test_score_returns_generated_at(self, client):
        r = client.post("/api/score", json={
            "article_id": "test-4",
            "topic_brief": "测试",
            "platforms": ["wechat"],
            "package_summary": {"platforms": []},
        })
        assert r.status_code == 200
        assert "generated_at" in r.json()
        assert "model" in r.json()
        assert r.json()["model"] == "mock"


class TestScorerBridgeClientHeaders:
    def test_headers_set(self):
        from orchestrator.bridge.scorer import ScorerClient

        sc = ScorerClient("http://127.0.0.1:8789")
        headers = sc._headers()
        assert "Idempotency-Key" in headers
        assert "X-Trace-Id" in headers
        assert headers["User-Agent"] == "orchestrator/1.0"


class TestScorerMissingFields:
    """Mock scorer doesn't validate — it returns 200 even without article_id.
    The real server will validate in M5. For M1 we just verify the mock works."""

    def test_scorer_accepts_request_without_article_id(self, client):
        """Mock mode is lenient; real mode validation comes in M5."""
        r = client.post("/api/score", json={
            "topic_brief": "测试",
            "package_summary": {"platforms": []},
        })
        # Mock accepts anything — verification in platform_scorer/server.py
        assert r.status_code == 200
