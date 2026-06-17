"""Open Library search backend (free, no API key needed).

Open Library API: https://openlibrary.org/dev/docs/api/search
"""
from __future__ import annotations

import httpx

from core.search.base import AbstractSearchBackend, SearchResult


class OpenLibrarySearch(AbstractSearchBackend):
    """Search Open Library for books and authors.

    Free, no API key required. Covers 30M+ works.
    """

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://openlibrary.org/search.json",
                    params={"q": query, "limit": min(max_results, 100)},
                )
                resp.raise_for_status()
                data = resp.json()
                docs = data.get("docs", [])

                for doc in docs[:max_results]:
                    title = doc.get("title", "")
                    author = ", ".join(doc.get("author_name", [])[:3])
                    year = doc.get("first_publish_year", "")
                    desc = f"作者: {author}" if author else ""
                    if year:
                        desc += f" | 出版年: {year}"

                    # Build Open Library URL
                    key = doc.get("key", "")
                    url = f"https://openlibrary.org{key}" if key else ""

                    results.append(SearchResult(
                        title=f"[Open Library] {title}",
                        url=url,
                        snippet=desc,
                    ))
        except Exception:
            pass
        return results
