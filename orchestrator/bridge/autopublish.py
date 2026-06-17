"""Bridge client for Autopublish module (port 8765).

Per LLD §3.8: handles publishing execution and status tracking.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class AutopublishClient:
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

    async def publish(
        self,
        article_id: str,
        platform: str,
        title: str,
        body: str,
        summary: str = "",
        tags: list[str] | None = None,
        keywords: list[str] | None = None,
        author: str = "",
        location: str = "",
        account_label: str = "",
        topic_title: str = "",
        cover_path: str | None = None,
        image_paths: list[str] | None = None,
        pinned_comment: str | None = None,
        *,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """POST /api/publish — execute a publish.

        Returns:
        {
          "plan_id": "uuid",
          "status": "success|failed|duplicate|retrying",
          "platform_url": "string|null",
          "platform_msg_id": "string|null",
          "error_message": "string|null",
          "duration_ms": 12345
        }
        """
        payload: dict[str, Any] = {
            "article_id": article_id,
            "platform": platform,
            "title": title,
            "body": body,
        }
        if summary:
            payload["summary"] = summary
        if tags:
            payload["tags"] = tags
        if keywords:
            payload["keywords"] = keywords
        if author:
            payload["author"] = author
        if location:
            payload["location"] = location
        if account_label:
            payload["account_label"] = account_label
        if topic_title:
            payload["topic_title"] = topic_title
        if cover_path:
            payload["cover_path"] = cover_path
        if image_paths:
            payload["image_paths"] = image_paths
        if pinned_comment:
            payload["pinned_comment"] = pinned_comment

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"{self.base_url}/api/publish",
                json=payload,
                headers=self._headers(trace_id, idempotency_key),
            )
            r.raise_for_status()
            return r.json()

    async def get_publish_status(
        self,
        plan_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict:
        """GET /api/publish/{plan_id} — get publish progress."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/publish/{plan_id}",
                headers=self._headers(trace_id),
            )
            r.raise_for_status()
            return r.json()

    async def get_progress(
        self,
        task_id: str,
        *,
        trace_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """GET /api/publish/progress/{task_id} — single progress poll
        against the Autopublish background-task progress map. Returns
        {"done": bool, ...}.
        """
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/publish/progress/{task_id}",
                headers=self._headers(trace_id),
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
