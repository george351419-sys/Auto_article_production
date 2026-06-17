"""Tests for LLM scorer output parsing robustness.

Per DEV_PLAN M5: handle malformed LLM JSON output.
"""
from __future__ import annotations

import json
import pytest


def parse_score_output(raw: str) -> dict:
    """Robust parser for LLM score output.

    Handles: markdown-wrapped JSON, missing fields, out-of-range scores.
    """
    # Strip markdown code blocks
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening and closing ```
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        import re
        match = re.search(r'\{[\s\S]*"scores"[\s\S]*\}', text)
        if match:
            data = json.loads(match.group())
        else:
            return _fallback_scores()

    scores = data.get("scores", {})
    result = {}
    for platform in ["wechat", "xiaohongshu", "toutiao"]:
        s = scores.get(platform, {})
        score_val = s.get("score", 0)
        # Clamp to 0-100
        score_val = max(0, min(100, score_val))
        reason = s.get("reason", "no reason")
        result[platform] = {"score": score_val, "reason": reason[:120]}
    return {"scores": result}


def _fallback_scores() -> dict:
    return {
        "scores": {
            "wechat": {"score": 50, "reason": "parse fallback"},
            "xiaohongshu": {"score": 50, "reason": "parse fallback"},
            "toutiao": {"score": 50, "reason": "parse fallback"},
        }
    }


class TestScorerParse:
    def test_valid_json(self):
        raw = '{"scores":{"wechat":{"score":88,"reason":"good"},"xiaohongshu":{"score":62,"reason":"ok"},"toutiao":{"score":75,"reason":"fine"}}}'
        data = parse_score_output(raw)
        assert data["scores"]["wechat"]["score"] == 88

    def test_markdown_wrapped_json(self):
        raw = '```json\n{"scores":{"wechat":{"score":90,"reason":"excellent"}}}\n```'
        data = parse_score_output(raw)
        assert data["scores"]["wechat"]["score"] == 90

    def test_missing_fields(self):
        raw = '{"scores":{"wechat":{"score":88}}}'
        data = parse_score_output(raw)
        assert data["scores"]["wechat"]["reason"]  # should have fallback
        # Missing platforms get default scores
        assert "toutiao" in data["scores"]

    def test_out_of_range_score_clamped(self):
        raw = '{"scores":{"wechat":{"score":150,"reason":"too high"}}}'
        data = parse_score_output(raw)
        assert data["scores"]["wechat"]["score"] == 100

    def test_negative_score_clamped(self):
        raw = '{"scores":{"wechat":{"score":-10,"reason":"negative"}}}'
        data = parse_score_output(raw)
        assert data["scores"]["wechat"]["score"] == 0

    def test_completely_invalid_input(self):
        raw = "not valid json at all"
        data = parse_score_output(raw)
        # Should return fallback scores
        assert "wechat" in data["scores"]
        assert data["scores"]["wechat"]["score"] == 50

    def test_reason_truncated_to_120_chars(self):
        long_reason = "x" * 200
        raw = f'{{"scores":{{"wechat":{{"score":80,"reason":"{long_reason}"}}}}}}'
        data = parse_score_output(raw)
        assert len(data["scores"]["wechat"]["reason"]) <= 120

    def test_json_with_extra_text(self):
        raw = 'Here is the score: {"scores":{"wechat":{"score":85,"reason":"solid"}}} Hope this helps!'
        data = parse_score_output(raw)
        assert data["scores"]["wechat"]["score"] == 85
