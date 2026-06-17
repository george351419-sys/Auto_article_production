"""Bridge HTTP clients for the five business modules.

Per LLD §3.1: every call carries an `X-Trace-Id` so logs can be
correlated end-to-end, and POST/PUT also carry an `Idempotency-Key`
that is stable across retries (so a downstream module can dedupe
duplicate requests if it wants to).

`make_idempotency_key(article_id, stage, retry_count)` is the canonical
way to derive the key — the same input always produces the same SHA1.
"""
from __future__ import annotations

import hashlib

from .autopublish import AutopublishClient
from .distilled import DistilledCharactersClient
from .scorer import ScorerClient
from .select_topic import SelectTopicClient
from .writing import WritingClient

__all__ = [
    "AutopublishClient",
    "DistilledCharactersClient",
    "ScorerClient",
    "SelectTopicClient",
    "WritingClient",
    "make_idempotency_key",
]


def make_idempotency_key(article_id: str, stage: str, retry_count: int = 0) -> str:
    """Stable, deterministic key for a (article_id, stage, retry) triple.

    LLD §3.1 says POSTs accept an `Idempotency-Key` header so duplicate
    requests return the same result. We use SHA1 over the triple — fast,
    short, deterministic, and changes only when one of the inputs does
    (which is the point: a retry is genuinely a new request).
    """
    raw = f"{article_id}|{stage}|{retry_count}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()
