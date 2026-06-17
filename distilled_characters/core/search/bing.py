"""Bing search backend using the free public web interface.

No API key needed — parses Bing.com search results.
"""
from __future__ import annotations

import httpx

from core.search.base import AbstractSearchBackend, SearchResult


class BingSearch(AbstractSearchBackend):
    """Search Bing public page — free, no API key.

    Uses Bing's organic search results page.
    Note: Bing may redirect to consent page; this backend handles it.
    """

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results = []
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(
                    "https://www.bing.com/search",
                    params={"q": query, "count": min(max_results, 30)},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                )
                if resp.status_code != 200:
                    return results

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")

                # Bing uses various result containers
                for item in soup.select("li.b_algo, .b_result, ol#b_results > li")[:max_results]:
                    title_el = item.select_one("h2 a, h3 a")
                    snippet_el = item.select_one(".b_caption p, .b_lineclamp2, .b_algoSlug, p")
                    if title_el:
                        title = title_el.get_text(strip=True)
                        url = title_el.get("href", "")
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                        if title and url and len(title) > 2:
                            results.append(SearchResult(title=title, url=url, snippet=snippet))
        except Exception:
            pass
        return results
