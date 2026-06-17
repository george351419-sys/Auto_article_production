"""Multi-channel search engine that aggregates results from multiple free sources.

Channels:
1. Wikipedia (EN + ZH) — structured encyclopedia, highly reliable
2. Open Library — 30M+ books, free API
3. DuckDuckGo — web search, no key needed
4. Bing — web search, no key needed (parsing public page)
5. SearXNG — multi-engine aggregator (if public instances available)

All channels are free and require no API keys.
"""
from __future__ import annotations

import asyncio

from core.search.base import AbstractSearchBackend, SearchResult


class MultiChannelSearch(AbstractSearchBackend):
    """Search across multiple free channels in parallel."""

    def __init__(self):
        self._channels = [
            ("wikipedia", None),
            ("wikipedia_zh", None),
            ("open_library", None),
            ("duckduckgo", None),
            ("bing", None),
        ]
        self._backends = {}

    def _get_backend(self, channel: str):
        if channel not in self._backends:
            if channel == "wikipedia":
                from core.search.wikipedia import WikipediaSearch
                self._backends[channel] = WikipediaSearch()
            elif channel == "wikipedia_zh":
                from core.search.wikipedia import WikipediaZHSearch
                self._backends[channel] = WikipediaZHSearch()
            elif channel == "open_library":
                from core.search.open_library import OpenLibrarySearch
                self._backends[channel] = OpenLibrarySearch()
            elif channel == "duckduckgo":
                from core.search.duckduckgo import DuckDuckGoSearch
                self._backends[channel] = DuckDuckGoSearch()
            elif channel == "bing":
                from core.search.bing import BingSearch
                self._backends[channel] = BingSearch()
            elif channel == "searxng":
                from core.search.searxng import SearXNGBackend
                self._backends[channel] = SearXNGBackend()
            else:
                raise ValueError(f"Unknown channel: {channel}")
        return self._backends[channel]

    @property
    def channel_names(self) -> list[str]:
        return [name for name, _ in self._channels] + ["searxng"]

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return await self.search_channel("all", query, max_results)

    async def search_channel(self, channel: str, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search a specific channel (or 'all' for every channel in parallel)."""
        per_channel = max_results

        async def _run(name, backend):
            try:
                return await backend.search(query, per_channel)
            except Exception:
                return []

        if channel == "all":
            tasks = []
            for name in self.channel_names:
                be = self._get_backend(name)
                tasks.append(_run(name, be))
            all_results = []
            for results in await asyncio.gather(*tasks):
                all_results.extend(results)
            # Deduplicate by URL
            seen = set()
            deduped = []
            for r in all_results:
                if r.url and r.url not in seen:
                    seen.add(r.url)
                    deduped.append(r)
            return deduped[:max_results]

        be = self._get_backend(channel)
        return await be.search(query, max_results)
