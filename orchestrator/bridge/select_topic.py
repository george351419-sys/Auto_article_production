"""Bridge client for select_topic module (port 8766).

Per LLD §3.5: handles topic collection triggers, listing, creation, and matching.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class SelectTopicClient:
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

    async def trigger_collect(self) -> dict:
        """POST /api/collect/trigger — trigger topic collection.

        Returns: {"collect_id": "uuid", "estimated_seconds": 60}
        """
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{self.base_url}/api/collect/trigger",
                json={},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def list_topics(self, status: str = "ready", limit: int = 30) -> list[dict]:
        """GET /api/topics — list topics by status."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/topics",
                params={"status": status, "limit": limit},
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("topics", data.get("items", []))

    async def create_topic(self, title: str, brief: str = "", source_url: str = "",
                           raw_material: str = "") -> dict:
        """POST /api/topics — user submits a topic.

        Returns: {"id": "uuid", "created_at": "iso8601"}
        """
        payload: dict[str, Any] = {"title": title}
        if brief:
            payload["brief"] = brief
        if source_url:
            payload["source_url"] = source_url
        if raw_material:
            payload["raw_material"] = raw_material

        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/topics",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def get_topic(self, topic_id: str) -> dict:
        """GET /api/topics/{id} — get topic detail."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/topics/{topic_id}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def match_topic(self, topic_id: str) -> dict:
        """POST /api/topics/{id}/match — trigger topic-to-character matching."""
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                f"{self.base_url}/api/topics/{topic_id}/match",
                json={},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _headers(trace_id: str | None = None) -> dict:
        return {
            "X-Trace-Id": trace_id or str(uuid.uuid4()),
            "Idempotency-Key": str(uuid.uuid4()),
            "User-Agent": "orchestrator/1.0",
        }
