"""Tests for retry backoff — 30s/2min/10min intervals.

Per DEV_PLAN M7.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import retry


class TestRetryBackoff:
    def test_retry_0_30_seconds(self):
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = retry.next_retry_at(0, now)
        assert result.endswith(":30Z") or result.endswith(":30+00:00")

    def test_retry_1_2_minutes(self):
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = retry.next_retry_at(1, now)
        expected = (now + timedelta(seconds=120)).isoformat()
        assert result == expected

    def test_retry_2_10_minutes(self):
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = retry.next_retry_at(2, now)
        expected = (now + timedelta(seconds=600)).isoformat()
        assert result == expected

    def test_retry_3_no_more(self):
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = retry.next_retry_at(3, now)
        assert result == ""

    def test_retry_10_no_more(self):
        result = retry.next_retry_at(10)
        assert result == ""


class TestShouldRetry:
    def test_retry_count_0_should_retry(self):
        assert retry.should_retry(0) is True

    def test_retry_count_2_should_retry(self):
        assert retry.should_retry(2) is True

    def test_retry_count_3_should_not_retry(self):
        assert retry.should_retry(3) is False

    def test_retry_count_5_should_not_retry(self):
        assert retry.should_retry(5) is False

    def test_within_15_minute_window_ok(self):
        first = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert retry.should_retry(1, first) is True

    def test_beyond_15_minute_window_stops(self):
        first = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        assert retry.should_retry(1, first) is False
