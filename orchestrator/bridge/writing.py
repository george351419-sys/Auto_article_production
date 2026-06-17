"""Bridge client for writing module (port 8788).

Per LLD §3.6: handles task creation, execution, and status polling.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class WritingClient:
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

    async def create_task(
        self,
        topic: str,
        topic_brief: str,
        celebrity_voice_model: str,
        platforms: list[str] | None = None,
        source_materials: list[dict] | None = None,
        promotion_goal: str = "吸引用户阅读、关注和转发，提升账号专业影响力",
        search_enabled: bool = True,
        *,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """POST /api/tasks — create a writing task.

        The writing module's normalizeTaskInput requires camelCase keys
        and rejects requests missing topic / celebrityVoiceModel /
        promotionGoal with 400. Keep payload aligned with
        writing/server/index.ts:normalizeTaskInput.

        Returns: {"task_id": "uuid", ...}
        """
        if platforms is None:
            platforms = ["wechat", "xiaohongshu", "toutiao"]

        payload: dict[str, Any] = {
            "topic": topic,
            "topicBrief": topic_brief,
            "celebrityVoiceModel": celebrity_voice_model,
            "promotionGoal": promotion_goal,
            "targetPlatforms": platforms,
            "searchEnabled": bool(search_enabled),
        }
        if source_materials:
            payload["sourceMaterials"] = source_materials

        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/tasks",
                json=payload,
                headers=self._headers(trace_id, idempotency_key),
            )
            r.raise_for_status()
            data = r.json()
            # Writing module wraps in 'task' key
            return data.get("task", data)

    async def run_task(
        self,
        task_id: str,
        *,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """POST /api/tasks/{id}/run — start task execution."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/tasks/{task_id}/run",
                json={},
                headers=self._headers(trace_id, idempotency_key),
            )
            r.raise_for_status()
            data = r.json()
            return data.get("task", data)

    async def force_approve(
        self, task_id: str, *, trace_id: str | None = None,
    ) -> dict:
        """POST /api/tasks/{id}/force-approve — accept current outputs."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/tasks/{task_id}/force-approve",
                json={}, headers=self._headers(trace_id),
            )
            r.raise_for_status()
            return r.json().get("task", {})

    async def reset_task(
        self, task_id: str, *, trace_id: str | None = None,
    ) -> dict:
        """POST /api/tasks/{id}/reset — clear rounds and rerun from scratch."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/tasks/{task_id}/reset",
                json={}, headers=self._headers(trace_id),
            )
            r.raise_for_status()
            return r.json().get("task", {})

    async def discard_task(
        self, task_id: str, *, trace_id: str | None = None,
    ) -> dict:
        """POST /api/tasks/{id}/discard — mark task as permanently discarded."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.post(
                f"{self.base_url}/api/tasks/{task_id}/discard",
                json={}, headers=self._headers(trace_id),
            )
            r.raise_for_status()
            return r.json().get("task", {})

    async def get_task(
        self,
        task_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict:
        """GET /api/tasks/{id} — poll task status including final_package."""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{self.base_url}/api/tasks/{task_id}",
                headers=self._headers(trace_id),
            )
            r.raise_for_status()
            data = r.json()
            return data.get("task", data)

    async def list_tasks(self) -> list[dict]:
        """GET /api/tasks — list all tasks."""
        async with httpx.AsyncClient(timeout=self.default_timeout) as c:
            r = await c.get(
                f"{self.base_url}/api/tasks",
                headers=self._headers(),
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return data
            return data.get("tasks", data.get("items", []))

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _headers(
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Outbound request headers.

        - trace_id: pass the *article*'s trace_id when calling from the
          scheduler so the whole pipeline shares one trace. Falls back to
          a fresh UUID for one-off calls (UI, smoke scripts).
        - idempotency_key: pass a deterministic value
          (`bridge.make_idempotency_key`) when calling from the scheduler
          so a retry hits the same downstream slot. Random UUID otherwise.
        """
        return {
            "X-Trace-Id": trace_id or str(uuid.uuid4()),
            "Idempotency-Key": idempotency_key or str(uuid.uuid4()),
            "User-Agent": "orchestrator/1.0",
        }
