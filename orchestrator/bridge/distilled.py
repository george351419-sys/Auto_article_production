"""Bridge client for distilled_characters module (port 8767).

Per LLD §3.4: handles character listing and topic-to-character matching.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class DistilledCharactersClient:
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

    async def list_characters(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/characters",
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("characters", data.get("items", []))

    async def match_character(self, topic_brief: str, topic_keywords: list[str] | None = None) -> dict:
        """POST /api/match — find best character for a topic."""
        payload: dict[str, Any] = {
            "topic_brief": topic_brief,
            "trace_id": str(uuid.uuid4()),
        }
        if topic_keywords:
            payload["topic_keywords"] = topic_keywords

        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/match",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def get_character(self, character_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/characters/{character_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _headers(trace_id: str | None = None) -> dict:
        return {
            "X-Trace-Id": trace_id or str(uuid.uuid4()),
            "User-Agent": "orchestrator/1.0",
        }
