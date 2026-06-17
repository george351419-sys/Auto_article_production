"""Abstract search backend."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class AbstractSearchBackend(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        ...
