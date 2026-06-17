"""OpenAI-compatible API backend.

Works with: OpenAI, any v1/completions endpoint, Ollama, vLLM,
local proxies, and third-party API gateways.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx

from core.llm.base import AbstractLLMBackend

logger = logging.getLogger("llm.openai_compatible")

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class OpenAICompatibleBackend(AbstractLLMBackend):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 180.0,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def send_prompt(
        self,
        user_prompt: str,
        system_message: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": user_prompt})

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"]

                    # Non-retryable error
                    if resp.status_code not in RETRYABLE_STATUSES:
                        detail = resp.text[:500]
                        raise RuntimeError(
                            f"API error {resp.status_code} from {self.base_url}/chat/completions: {detail}"
                        )

                    last_error = resp

            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                last_error = e

            if attempt < self.max_retries:
                delay = 2 ** attempt  # 1s, 2s
                logger.warning(
                    "LLM call attempt %d/%d failed (%s), retrying in %ds",
                    attempt + 1, self.max_retries + 1, last_error, delay,
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        if isinstance(last_error, Exception):
            raise RuntimeError(
                f"LLM call failed after {self.max_retries + 1} attempts: {last_error}"
            ) from last_error
        detail = last_error.text[:500] if hasattr(last_error, 'text') else str(last_error)
        raise RuntimeError(
            f"API error after {self.max_retries + 1} attempts from {self.base_url}: {detail}"
        )

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    @property
    def backend_type(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model
