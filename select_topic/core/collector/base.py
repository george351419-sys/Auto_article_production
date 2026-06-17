"""Collector base data structures.

Raw hot items flow through: fetch → distill → dedup → score → store.
All raw fetched content lives only in memory; nothing is written to disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class HotItem:
    """A single raw hot list entry from any source platform."""
    title: str
    url: str = ""
    platform: str = ""         # e.g. 'toutiao', 'weibo', 'xiaohongshu', 'newrank', 'tophub'
    heat_score: float = 0.0    # 0-100, normalized across sources
    rank: int = 0


@dataclass
class DistilledTopic:
    """LLM-distilled topic ready for scoring and storage."""
    title: str
    core_topic: str = ""       # Short topic label
    raw_content: str = ""      # 2-3 sentence summary
    source_url: str = ""
    source_platform: str = ""
    source_material: list[dict] = field(default_factory=list)  # [{url, title, platform}]
    heat_level: str = "normal"  # hot | warm | normal
    is_valid: bool = True       # False if entertainment/politics filtered
    filter_reason: str = ""


@runtime_checkable
class CollectorProtocol(Protocol):
    """Protocol that all platform collectors must implement."""
    source_name: str

    async def collect(self) -> list[HotItem]:
        """Fetch hot items from this source."""
        ...

    async def health_check(self) -> bool:
        """Check if this source is reachable."""
        ...
