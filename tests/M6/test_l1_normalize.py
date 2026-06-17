"""Tests for L1 title normalization — edge cases.

Per DEV_PLAN M6.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import dedup


class TestL1Normalize:
    def test_strips_punctuation(self):
        result = dedup.normalize_title("AI大模型！改变世界？")
        assert "！" not in result
        assert "？" not in result

    def test_lowercase_english(self):
        result = dedup.normalize_title("DeepSeek Raises $500M")
        assert result == "deepseekraises500m"

    def test_removes_whitespace(self):
        result = dedup.normalize_title("  AI  大模型  改变  世界  ")
        assert " " not in result

    def test_unicode_normalization(self):
        """Full-width and half-width characters should be treated the same."""
        # Chinese punctuation: full-width ！vs half-width !
        t1 = dedup.normalize_title("AI大模型！改变世界")
        t2 = dedup.normalize_title("AI大模型!改变世界")
        assert t1 == t2

    def test_identical_titles_match(self):
        t = "AI大模型改变世界"
        assert dedup.normalize_title(t) == dedup.normalize_title(t)

    def test_different_punctuation_match(self):
        """Titles differing only in punctuation should match."""
        t1 = dedup.normalize_title("DeepSeek完成500亿融资的背后逻辑")
        t2 = dedup.normalize_title("DeepSeek完成500亿融资，的背后逻辑")
        # They differ only by a comma vs empty — should not be equal
        # (punctuation is stripped so they should be equal)
        no_punc_t1 = ''.join(c for c in t1 if c.isalnum() or '一' <= c <= '鿿')
        no_punc_t2 = ''.join(c for c in t2 if c.isalnum() or '一' <= c <= '鿿')
        # Both strip punctuation via normalize_title already
        assert t1 == t2

    def test_empty_title(self):
        result = dedup.normalize_title("")
        assert result == ""

    def test_numbers_preserved(self):
        result = dedup.normalize_title("2026年AI市场报告")
        assert "2026" in result


class TestJaccard:
    def test_identical_sets(self):
        assert dedup.jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert dedup.jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        assert dedup.jaccard({"a", "b", "c"}, {"b", "c", "d"}) == 2 / 4

    def test_jaccard_threshold_boundary(self):
        """Jaccard ≥ 0.7 is the L2 threshold."""
        # 3/4 = 0.75 ≥ 0.7 → match
        assert dedup.jaccard({"a", "b", "c", "d"}, {"a", "b", "c"}) == 0.75
        # 2/3 ≈ 0.67 < 0.7 → no match
        val = dedup.jaccard({"a", "b", "c"}, {"a", "b"})
        assert val < 0.7

    def test_both_empty(self):
        assert dedup.jaccard(set(), set()) == 0.0
