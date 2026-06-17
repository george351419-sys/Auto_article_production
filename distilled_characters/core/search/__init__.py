"""Search package."""
from core.search.base import AbstractSearchBackend, SearchResult
from core.search.duckduckgo import DuckDuckGoSearch
from core.search.fetcher import WebFetcher

__all__ = [
    "AbstractSearchBackend",
    "SearchResult",
    "DuckDuckGoSearch",
    "WebFetcher",
]
