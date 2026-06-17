"""Tests for L2 keyword overlap check.

Per DEV_PLAN M6.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import dedup


class TestKeywordOverlap:
    def test_overlap_exists(self):
        assert dedup.check_keyword_overlap(["AI", "大模型"], ["AI", "芯片"]) is True

    def test_no_overlap(self):
        assert dedup.check_keyword_overlap(["AI", "大模型"], ["量子", "芯片"]) is False

    def test_single_overlap(self):
        assert dedup.check_keyword_overlap(["AI"], ["AI"]) is True

    def test_empty_lists(self):
        assert dedup.check_keyword_overlap([], []) is False

    def test_one_empty(self):
        assert dedup.check_keyword_overlap(["AI"], []) is False
