"""Tests for writing bridge client.

Per DEV_PLAN §5.3: uses FastAPI TestClient mock server.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.mock_modules import make_mock_writing_app


@pytest.fixture
def mock_app():
    return make_mock_writing_app()


@pytest.fixture
def client(mock_app):
    return TestClient(mock_app)


class TestWritingHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["module"] == "writing"

    def test_contract_returns_endpoints(self, client):
        r = client.get("/contract")
        assert r.status_code == 200
        data = r.json()
        endpoints = {(ep["method"], ep["path"]) for ep in data["endpoints"]}
        assert ("POST", "/api/tasks") in endpoints
        assert ("GET", "/api/tasks/{id}") in endpoints
        assert ("POST", "/api/tasks/{id}/run") in endpoints


class TestWritingBusinessEndpoints:
    def test_create_task_returns_task(self, client):
        r = client.post("/api/tasks", json={
            "topic": "AI融资",
            "topic_brief": "测试",
            "character_id": "c1",
            "platforms": ["wechat"],
            "promotion_goal": "测试",
        })
        assert r.status_code == 200
        data = r.json()
        assert "task" in data
        assert data["task"]["task_id"] == "wt-1"

    def test_run_task_returns_status(self, client):
        r = client.post("/api/tasks/wt-1/run", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["task"]["status"] == "running"

    def test_get_task_returns_final_package(self, client):
        r = client.get("/api/tasks/wt-1")
        assert r.status_code == 200
        data = r.json()
        assert data["task"]["status"] == "completed"
        fp = data["task"]["final_package"]
        assert "platforms" in fp
        assert fp["platforms"][0]["platform"] == "wechat"


class TestBridgeClientHeaders:
    def test_idempotency_key_set(self):
        from orchestrator.bridge.writing import WritingClient

        wc = WritingClient("http://127.0.0.1:8788")
        headers = wc._headers()
        assert "Idempotency-Key" in headers
        assert "X-Trace-Id" in headers

    def test_trace_id_can_be_overridden(self):
        from orchestrator.bridge.writing import WritingClient

        wc = WritingClient("http://127.0.0.1:8788")
        headers = wc._headers(trace_id="custom-trace")
        assert headers["X-Trace-Id"] == "custom-trace"
