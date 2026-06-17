"""Web search routes — multi-channel research for a character.

Channels:
- searxng: SearXNG public instances (70+ engines: Google, Bing, DDG, etc.)
- open_library: Open Library API (30M+ books, free)
- duckduckgo: DuckDuckGo direct search
- all: Aggregates from all channels
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.dependencies import get_character_repo, get_material_repo

router = APIRouter(tags=["search"])


class ResearchRequest(BaseModel):
    query_override: str = ""
    max_results: int = 10
    channel: str = "all"  # all | searxng | open_library | duckduckgo


@router.post("/characters/{character_id}/research")
async def research_character(character_id: str, body: ResearchRequest):
    char_repo = get_character_repo()
    char = await char_repo.get(character_id)
    if not char:
        raise HTTPException(404, "Character not found")

    query = body.query_override or char["name"]
    mat_repo = get_material_repo()
    created = []

    from core.search.multi_channel import MultiChannelSearch

    search_engine = MultiChannelSearch()
    try:
        results = await search_engine.search_channel(
            body.channel, query, body.max_results
        )

        from core.search.fetcher import WebFetcher
        fetcher = WebFetcher()

        for r in results[:body.max_results]:
            content = r.snippet or ""
            # Try to fetch full content for web results (not book results)
            if r.url and not r.url.startswith("https://openlibrary.org"):
                try:
                    fetched = await fetcher.fetch_content(r.url)
                    if fetched:
                        content = fetched
                except Exception:
                    pass

            material = await mat_repo.create({
                "character_id": character_id,
                "title": r.title,
                "raw_content": content,
                "url": r.url,
                "source_type": "third_party",
                "confidence": "B",
                "tags": [f"channel:{body.channel}", "auto_research"],
            })
            created.append(material)

    except ImportError:
        pass

    return {
        "character_id": character_id,
        "query": query,
        "channel": body.channel,
        "materials_added": len(created),
        "materials": created,
    }
