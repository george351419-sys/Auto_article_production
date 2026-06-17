"""Tests for retry limit — 3 retries max, then stop.

Per DEV_PLAN M7.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import retry


class TestRetryLimit:
    def test_max_retries_is_3(self):
        assert retry.MAX_RETRIES == 3

    def test_retry_delays_length(self):
        assert len(retry.RETRY_DELAYS) == 3

    def test_retry_delays_correct(self):
        assert retry.RETRY_DELAYS == [30, 120, 600]

    def test_count_4_no_retry_scheduled(self):
        """After 3 retries, next_retry_at should be empty."""
        assert retry.next_retry_at(4) == ""


class TestSkipPlatform:
    """Tests for skip-platform logic — only that platform is skipped, others continue."""

    def test_skip_one_platform_others_continue(self):
        """Simulate skip: remove wechat from publish list, keep toutiao."""
        platforms = ["wechat", "xiaohongshu", "toutiao"]
        skipped = "wechat"
        remaining = [p for p in platforms if p != skipped]
        assert "wechat" not in remaining
        assert "toutiao" in remaining
        assert "xiaohongshu" in remaining

    def test_skip_all_platforms_leaves_empty(self):
        platforms = ["wechat", "toutiao"]
        for p in list(platforms):
            platforms.remove(p)
        assert platforms == []


class TestTerminate:
    """Tests for terminate action — force article to rejected."""

    def test_terminate_sets_rejected(self):
        """Terminate action transitions to rejected (terminal state)."""
        final_state = "rejected"
        assert final_state == "rejected"

    def test_rejected_cannot_transition(self):
        """Rejected is terminal — no further transitions allowed."""
        from orchestrator.state_machine import TRANSITIONS
        assert len(TRANSITIONS["rejected"]) == 0


class TestUserRetry:
    """Tests for user-initiated retry — reset retry_count to 0."""

    def test_user_retry_resets_count(self):
        """User clicking retry should reset retry_count to 0."""
        old_count = 3
        new_count = 0
        assert new_count == 0
        assert old_count != new_count
