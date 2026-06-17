"""Tests for select_topic bridge client.

Per DEV_PLAN §5.3: uses FastAPI TestClient mock server.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.mock_modules import make_mock_select_app


@pytest.fixture
def mock_app():
    return make_mock_select_app()


@pytest.fixture
def client(mock_app):
    return TestClient(mock_app)


class TestSelectTopicHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["module"] == "select_topic"

    def test_contract_returns_endpoints(self, client):
        r = client.get("/contract")
        assert r.status_code == 200
        data = r.json()
        assert data["contract_version"] == "1.0"
        endpoints = {(ep["method"], ep["path"]) for ep in data["endpoints"]}
        assert ("POST", "/api/collect/trigger") in endpoints
        assert ("GET", "/api/topics") in endpoints


class TestSelectTopicBusinessEndpoints:
    def test_trigger_collect_returns_collect_id(self, client):
        r = client.post("/api/collect/trigger", json={})
        assert r.status_code == 200
        data = r.json()
        assert "collect_id" in data

    def test_list_topics_returns_topics(self, client):
        r = client.get("/api/topics?status=ready&limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "topics" in data

    def test_create_topic_returns_id(self, client):
        r = client.post("/api/topics", json={"title": "测试选题"})
        assert r.status_code == 200
        data = r.json()
        assert "id" in data

    def test_get_topic_returns_detail(self, client):
        r = client.get("/api/topics/t1")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "t1"


class TestBridgeClientHeaders:
    def test_idempotency_key_set(self):
        from orchestrator.bridge.select_topic import SelectTopicClient

        sc = SelectTopicClient("http://127.0.0.1:8766")
        headers = sc._headers()
        assert "Idempotency-Key" in headers
        assert "X-Trace-Id" in headers
        assert headers["User-Agent"] == "orchestrator/1.0"

    def test_two_calls_get_different_keys(self):
        from orchestrator.bridge.select_topic import SelectTopicClient

        sc = SelectTopicClient("http://127.0.0.1:8766")
        h1 = sc._headers()
        h2 = sc._headers()
        assert h1["Idempotency-Key"] != h2["Idempotency-Key"]
