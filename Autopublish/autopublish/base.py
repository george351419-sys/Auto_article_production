"""Base publisher interface, retry logic, and rate limiter.

Zero external dependencies — pure Python with typing.Protocol.
"""

from __future__ import annotations

import random
import time
import uuid
from enum import StrEnum
from typing import Protocol

# ── Retry Constants ─────────────────────────────────────────

MAX_PUBLISH_RETRIES = 3
RETRY_BASE_DELAY_S = 5.0
RETRY_MAX_DELAY_S = 120.0
PUBLISH_IDEMPOTENCY_PREFIX = "publish_plan_"


class PublishStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    DUPLICATE = "duplicate"


class RateLimiter:
    """Simple token-bucket rate limiter per account per hour."""

    def __init__(self, default_rate: int = 5):
        self._default_rate = default_rate
        self._rates: dict[str, tuple[int, float]] = {}

    def check(self, account_id: str, rate: int | None = None) -> tuple[bool, int]:
        max_rate = rate or self._default_rate
        now = time.monotonic()
        if account_id not in self._rates:
            self._rates[account_id] = (max_rate, now + 3600)
            return True, max_rate - 1
        remaining, reset_at = self._rates[account_id]
        if now >= reset_at:
            self._rates[account_id] = (max_rate, now + 3600)
            return True, max_rate - 1
        if remaining <= 0:
            return False, 0
        self._rates[account_id] = (remaining - 1, reset_at)
        return True, remaining - 1

    def reset(self, account_id: str) -> None:
        self._rates.pop(account_id, None)


rate_limiter = RateLimiter()


class PublishResult:
    def __init__(
        self,
        status: PublishStatus,
        platform_url: str = "",
        error_message: str = "",
        retry_count: int = 0,
        trace_id: str = "",
    ):
        self.status = status
        self.platform_url = platform_url
        self.error_message = error_message
        self.retry_count = retry_count
        self.trace_id = trace_id or f"pub_{uuid.uuid4().hex[:12]}"


class Publisher(Protocol):
    """Interface for platform-specific publishers.

    All implementations must be thread-safe.
    """

    def publish(
        self,
        title: str,
        body: str,
        summary: str = "",
        tags: list[str] | None = None,
        cover_path: str = "",
        image_paths: list[str] | None = None,
        account_name: str = "",
    ) -> PublishResult: ...


# ── Retry Helpers ──────────────────────────────────────────


def should_retry(result: PublishResult) -> bool:
    """Determine if a publish result should be retried."""
    if result.status in (PublishStatus.SUCCESS, PublishStatus.DUPLICATE):
        return False
    return result.retry_count < MAX_PUBLISH_RETRIES


def backoff_delay(attempt: int) -> float:
    """Exponential backoff + jitter."""
    delay = min(RETRY_BASE_DELAY_S * (2 ** attempt), RETRY_MAX_DELAY_S)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


def build_idempotent_key(plan_id: str) -> str:
    return f"{PUBLISH_IDEMPOTENCY_PREFIX}{plan_id}"
