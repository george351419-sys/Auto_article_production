"""Tests for Autopublish bridge client.

Per DEV_PLAN §5.3: uses FastAPI TestClient mock server.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpers.mock_modules import make_mock_autopublish_app


@pytest.fixture
def mock_app():
    return make_mock_autopublish_app()


@pytest.fixture
def client(mock_app):
    return TestClient(mock_app)


class TestAutopublishHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["module"] == "autopublish"

    def test_contract_returns_endpoints(self, client):
        r = client.get("/contract")
        assert r.status_code == 200
        data = r.json()
        endpoints = {(ep["method"], ep["path"]) for ep in data["endpoints"]}
        assert ("POST", "/api/publish") in endpoints


class TestAutopublishBusinessEndpoints:
    def test_publish_returns_success(self, client):
        r = client.post("/api/publish", json={
            "article_id": "art-1",
            "platform": "toutiao",
            "title": "测试标题",
            "body": "# 测试正文",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert "plan_id" in data
        assert "platform_url" in data

    def test_publish_returns_all_required_fields(self, client):
        r = client.post("/api/publish", json={
            "article_id": "art-2",
            "platform": "wechat_official",
            "title": "测试",
            "body": "正文",
        })
        data = r.json()
        assert "plan_id" in data
        assert "status" in data
        assert "platform_url" in data
        assert "platform_msg_id" in data
        assert "duration_ms" in data

    def test_get_publish_status_returns_status(self, client):
        r = client.get("/api/publish/pub-1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"


class TestBridgeClientHeaders:
    def test_headers_set(self):
        from orchestrator.bridge.autopublish import AutopublishClient

        ac = AutopublishClient("http://127.0.0.1:8765")
        headers = ac._headers()
        assert "Idempotency-Key" in headers
        assert "X-Trace-Id" in headers
        assert headers["User-Agent"] == "orchestrator/1.0"
