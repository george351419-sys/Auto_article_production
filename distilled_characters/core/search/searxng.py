"""SearXNG search backend (free, no API key needed).

Uses public SearXNG instances to aggregate results from 70+ engines
(Google, Bing, DuckDuckGo, etc.). Falls back through a list of known
public instances for reliability.

Also supports self-hosted instances via config.
"""
from __future__ import annotations

import json

import httpx

from core.search.base import AbstractSearchBackend, SearchResult

# Public SearXNG instances that support search (from searx.space)
PUBLIC_INSTANCES = [
    "https://searx.be",
    "https://searx.tiekoetter.com",
    "https://searx.si",
    "https://search.bus-hit.me",
    "https://searx.fmac.xyz",
    "https://ooglester.com",
    "https://priv.au",
    "https://opnxng.com",
    "https://metacat.online",
    "https://searx.work",
]


def _parse_html_results(html: str, max_results: int) -> list[SearchResult]:
    """Parse SearXNG HTML search results page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for article in soup.select("article.result, .result")[:max_results]:
        title_el = article.select_one("h3 a, .result-title a")
        snippet_el = article.select_one(".content, .result-content, .result-snippet, p")
        url_el = article.select_one(".result-link, .result-url, cite")

        if title_el:
            title = title_el.get_text(strip=True)
            url = ""
            if url_el:
                url = url_el.get_text(strip=True)
            if not url:
                url = title_el.get("href", "")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))
    return results


class SearXNGBackend(AbstractSearchBackend):
    """Search via public SearXNG instances — free, no API key.

    Tries JSON API first (some instances disable it),
    falls back to HTML parsing.
    """

    def __init__(self, instances: list[str] | None = None):
        self._instances = instances or PUBLIC_INSTANCES

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        for instance in self._instances:
            try:
                results = await self._try_instance(instance, query, max_results)
                if results:
                    return results
            except Exception:
                continue
        return []

    async def _try_instance(self, base_url: str, query: str, max_results: int) -> list[SearchResult]:
        """Try one SearXNG instance, JSON then HTML."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/json",
            }

            # Try JSON API first
            try:
                resp = await client.get(
                    f"{base_url}/search",
                    params={"q": query, "format": "json", "categories": "general"},
                    headers=headers,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except (json.JSONDecodeError, ValueError):
                        pass
                    else:
                        results = []
                        for item in data.get("results", [])[:max_results]:
                            results.append(SearchResult(
                                title=item.get("title", ""),
                                url=item.get("url", ""),
                                snippet=item.get("content", item.get("snippet", "")),
                            ))
                        if results:
                            return results
            except Exception:
                pass

            # Fall back to HTML parsing
            try:
                resp = await client.get(
                    f"{base_url}/search",
                    params={"q": query},
                    headers=headers,
                )
                resp.raise_for_status()
                results = _parse_html_results(resp.text, max_results)
                if results:
                    return results
            except Exception:
                pass

        return []
