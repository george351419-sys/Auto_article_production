"""Tests for dispatch threshold logic.

Per DEV_PLAN M5: score ≥70 publish, 50-69 edge, <50 skip.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import dispatch


class TestThreshold:
    def test_score_70_publishes(self):
        assert dispatch.should_publish(70) is True

    def test_score_69_does_not_publish(self):
        assert dispatch.should_publish(69) is False

    def test_score_100_publishes(self):
        assert dispatch.should_publish(100) is True

    def test_score_0_does_not_publish(self):
        assert dispatch.should_publish(0) is False

    def test_score_50_is_edge(self):
        assert dispatch.is_edge_candidate(50) is True

    def test_score_69_is_edge(self):
        assert dispatch.is_edge_candidate(69) is True

    def test_score_70_is_not_edge(self):
        assert dispatch.is_edge_candidate(70) is False

    def test_score_49_is_not_edge(self):
        assert dispatch.is_edge_candidate(49) is False


class TestDecidePlatforms:
    def test_all_above_threshold(self):
        scores = [
            {"platform": "wechat", "score": 85},
            {"platform": "xiaohongshu", "score": 75},
            {"platform": "toutiao", "score": 80},
        ]
        platforms = dispatch.decide_platforms(scores)
        assert set(platforms) == {"wechat", "xiaohongshu", "toutiao"}

    def test_mixed_scores(self):
        scores = [
            {"platform": "wechat", "score": 88},
            {"platform": "xiaohongshu", "score": 62},
            {"platform": "toutiao", "score": 40},
        ]
        platforms = dispatch.decide_platforms(scores)
        assert "wechat" in platforms
        assert "xiaohongshu" not in platforms
        assert "toutiao" not in platforms

    def test_all_below_threshold(self):
        scores = [
            {"platform": "wechat", "score": 30},
            {"platform": "toutiao", "score": 20},
        ]
        platforms = dispatch.decide_platforms(scores)
        assert platforms == []
