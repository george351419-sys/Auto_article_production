"""Tests for platform_scorer mock mode specifically.

Per DEV_PLAN §5.3: validates mock scoring behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.mock_modules import make_mock_scorer_app


@pytest.fixture
def scorer_app():
    return make_mock_scorer_app()


@pytest.fixture
def client(scorer_app):
    return TestClient(scorer_app)


class TestScorerMockValues:
    """Verify mock scorer returns the expected fixed values."""

    def test_wechat_score_is_80(self, client):
        r = client.post("/api/score", json={
            "article_id": "a1",
            "topic_brief": "test",
            "platforms": ["wechat"],
            "package_summary": {"platforms": []},
        })
        assert r.json()["scores"]["wechat"]["score"] == 80

    def test_xiaohongshu_score_is_70(self, client):
        r = client.post("/api/score", json={
            "article_id": "a2",
            "topic_brief": "test",
            "platforms": ["xiaohongshu"],
            "package_summary": {"platforms": []},
        })
        assert r.json()["scores"]["xiaohongshu"]["score"] == 70

    def test_toutiao_score_is_60(self, client):
        r = client.post("/api/score", json={
            "article_id": "a3",
            "topic_brief": "test",
            "platforms": ["toutiao"],
            "package_summary": {"platforms": []},
        })
        assert r.json()["scores"]["toutiao"]["score"] == 60

    def test_all_scores_in_range_0_100(self, client):
        r = client.post("/api/score", json={
            "article_id": "a4",
            "topic_brief": "test",
            "platforms": ["wechat", "xiaohongshu", "toutiao"],
            "package_summary": {"platforms": []},
        })
        scores = r.json()["scores"]
        for p, s in scores.items():
            assert 0 <= s["score"] <= 100, f"{p} score {s['score']} out of range"

    def test_all_scores_have_reason(self, client):
        r = client.post("/api/score", json={
            "article_id": "a5",
            "topic_brief": "test",
            "platforms": ["wechat", "xiaohongshu", "toutiao"],
            "package_summary": {"platforms": []},
        })
        scores = r.json()["scores"]
        for p in ["wechat", "xiaohongshu", "toutiao"]:
            assert len(scores[p]["reason"]) > 0

    def test_model_field_is_mock(self, client):
        r = client.post("/api/score", json={
            "article_id": "a6",
            "topic_brief": "test",
            "platforms": ["wechat"],
            "package_summary": {"platforms": []},
        })
        assert r.json()["model"] == "mock"

    def test_generated_at_is_iso8601(self, client):
        r = client.post("/api/score", json={
            "article_id": "a7",
            "topic_brief": "test",
            "platforms": ["wechat"],
            "package_summary": {"platforms": []},
        })
        ts = r.json()["generated_at"]
        assert "T" in ts
        assert "Z" in ts


class TestScorerIdempotency:
    """Scorer should be idempotent — same input returns same scores."""

    def test_same_input_returns_same_scores(self, client):
        payload = {
            "article_id": "a8",
            "topic_brief": "test",
            "platforms": ["wechat", "xiaohongshu", "toutiao"],
            "package_summary": {"platforms": []},
        }
        r1 = client.post("/api/score", json=payload)
        r2 = client.post("/api/score", json=payload)
        assert r1.json()["scores"] == r2.json()["scores"]
