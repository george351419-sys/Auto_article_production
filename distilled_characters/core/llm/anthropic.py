"""Anthropic Messages API backend for Claude models."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx

from core.llm.base import AbstractLLMBackend

logger = logging.getLogger("llm.anthropic")

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class AnthropicBackend(AbstractLLMBackend):
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        timeout: float = 180.0,
        base_url: str = "https://api.anthropic.com",
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self._model = model
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries

    async def send_prompt(
        self,
        user_prompt: str,
        system_message: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        body = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system_message:
            body["system"] = system_message

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/v1/messages",
                        headers={
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for block in data.get("content", []):
                            if block["type"] == "text":
                                return block["text"]
                        return ""

                    if resp.status_code not in RETRYABLE_STATUSES:
                        detail = resp.text[:500]
                        raise RuntimeError(
                            f"API error {resp.status_code} from {self.base_url}/v1/messages: {detail}"
                        )

                    last_error = resp

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = e

            if attempt < self.max_retries:
                delay = 2 ** attempt
                logger.warning(
                    "Anthropic call attempt %d/%d failed (%s), retrying in %ds",
                    attempt + 1, self.max_retries + 1, last_error, delay,
                )
                await asyncio.sleep(delay)

        if isinstance(last_error, Exception):
            raise RuntimeError(
                f"Anthropic call failed after {self.max_retries + 1} attempts: {last_error}"
            ) from last_error
        detail = last_error.text[:500] if hasattr(last_error, 'text') else str(last_error)
        raise RuntimeError(
            f"API error after {self.max_retries + 1} attempts from {self.base_url}: {detail}"
        )

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                )
                return resp.status_code == 200
        except Exception:
            return False

    @property
    def backend_type(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model
