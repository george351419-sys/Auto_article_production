"""DuckDuckGo search backend (free, no API key needed)."""
from __future__ import annotations

import httpx

from core.search.base import AbstractSearchBackend, SearchResult


class DuckDuckGoSearch(AbstractSearchBackend):
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh)"},
                )
                resp.raise_for_status()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for el in soup.select(".result"):
                    if len(results) >= max_results:
                        break
                    title_el = el.select_one(".result__title")
                    snippet_el = el.select_one(".result__snippet")
                    url_el = el.select_one(".result__url")
                    if title_el:
                        title = title_el.get_text(strip=True)
                        url = url_el.get_text(strip=True) if url_el else ""
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                        results.append(SearchResult(title=title, url=url, snippet=snippet))
        except ImportError:
            # bs4 not installed — return empty
            pass
        except Exception:
            pass
        return results
