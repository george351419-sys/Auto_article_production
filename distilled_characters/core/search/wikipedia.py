"""Wikipedia search backend (free, no API key needed).

Uses Wikipedia's opensearch JSON API for title suggestions,
and the search API for full-text results.
"""
from __future__ import annotations

import httpx

from core.search.base import AbstractSearchBackend, SearchResult


class WikipediaSearch(AbstractSearchBackend):
    """Search Wikipedia — free, no API key, highly reliable.

    Uses Wikipedia's REST API which returns structured JSON.
    """

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "format": "json",
                        "srlimit": min(max_results, 50),
                    },
                    headers={"User-Agent": "DistilledCharacters/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("query", {}).get("search", [])[:max_results]:
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    # Clean HTML from snippet
                    import re
                    snippet = re.sub(r"<[^>]+>", "", snippet)
                    page_id = item.get("pageid", "")
                    url = f"https://en.wikipedia.org/?curid={page_id}" if page_id else ""

                    results.append(SearchResult(
                        title=f"[Wiki] {title}",
                        url=url,
                        snippet=snippet,
                    ))
        except Exception:
            pass
        return results


class WikipediaZHSearch(AbstractSearchBackend):
    """Search Chinese Wikipedia — free, no API key."""

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://zh.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "format": "json",
                        "srlimit": min(max_results, 50),
                    },
                    headers={"User-Agent": "DistilledCharacters/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                import re
                for item in data.get("query", {}).get("search", [])[:max_results]:
                    title = item.get("title", "")
                    snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                    page_id = item.get("pageid", "")
                    url = f"https://zh.wikipedia.org/?curid={page_id}" if page_id else ""

                    results.append(SearchResult(
                        title=f"[中文维基] {title}",
                        url=url,
                        snippet=snippet,
                    ))
        except Exception:
            pass
        return results
