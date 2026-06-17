"""Bridge client for platform_scorer module (port 8789).

Per LLD §3.7: handles scoring requests against the 3 target platforms.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class ScorerClient:
    def __init__(self, base_url: str, *, default_timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.default_timeout = default_timeout

    # ── health / contract ────────────────────────────────────

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{self.base_url}/health", headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def contract(self) -> dict:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{self.base_url}/contract", headers=self._headers())
            r.raise_for_status()
            return r.json()

    # ── business endpoints ───────────────────────────────────

    async def score(
        self,
        article_id: str,
        topic_brief: str,
        platforms: list[str] | None = None,
        package_summary: dict | None = None,
        *,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """POST /api/score — score an article across platforms.

        Returns per LLD §3.7:
        {
          "scores": {
            "wechat":      {"score": 88, "reason": "..."},
            "xiaohongshu": {"score": 62, "reason": "..."},
            "toutiao":     {"score": 75, "reason": "..."}
          },
          "generated_at": "iso8601",
          "model": "deepseek-chat"
        }
        """
        if platforms is None:
            platforms = ["wechat", "xiaohongshu", "toutiao"]
        if package_summary is None:
            package_summary = {}

        payload: dict[str, Any] = {
            "article_id": article_id,
            "topic_brief": topic_brief,
            "platforms": platforms,
            "package_summary": package_summary,
        }

        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{self.base_url}/api/score",
                json=payload,
                headers=self._headers(trace_id, idempotency_key),
            )
            r.raise_for_status()
            return r.json()

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _headers(
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        return {
            "X-Trace-Id": trace_id or str(uuid.uuid4()),
            "Idempotency-Key": idempotency_key or str(uuid.uuid4()),
            "User-Agent": "orchestrator/1.0",
        }
