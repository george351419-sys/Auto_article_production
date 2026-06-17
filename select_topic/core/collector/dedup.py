"""Deduplication for collected topics.

Three-phase dedup:
  1. URL exact match against existing topic source_urls
  2. Intra-batch title similarity — if two items in the NEW batch are similar, keep only the higher-scored one
  3. Cross-DB title similarity (character 3-gram Jaccard) against recent topics
"""

from __future__ import annotations

import logging

import aiosqlite

from core.collector.base import DistilledTopic

logger = logging.getLogger("dedup")


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    """Generate character n-grams from text (no word segmentation needed for Chinese)."""
    text = text.strip().lower()
    if len(text) < n:
        return {text}
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def compute_title_similarity(title_a: str, title_b: str) -> float:
    """Jaccard similarity of character 3-grams between two titles."""
    if not title_a or not title_b:
        return 0.0
    set_a = _char_ngrams(title_a)
    set_b = _char_ngrams(title_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _dedup_intra_batch(items: list[DistilledTopic], threshold: float = 0.70) -> list[DistilledTopic]:
    """Remove near-duplicate items within the same batch.

    When LLM distillation produces multiple variants of the same hot item,
    keep only the first (most detailed) version.
    """
    if len(items) <= 1:
        return items

    kept = []
    for item in items:
        too_similar = False
        for existing in kept:
            sim = compute_title_similarity(item.title, existing.title)
            if sim >= threshold:
                too_similar = True
                logger.debug("Intra-batch dedup: '%s' ~= '%s' (%.2f)",
                           item.title[:40], existing.title[:40], sim)
                break
        if not too_similar:
            kept.append(item)

    if len(kept) < len(items):
        logger.info("Intra-batch dedup: %d → %d items", len(items), len(kept))
    return kept


async def deduplicate(
    db: aiosqlite.Connection,
    items: list[DistilledTopic],
    title_threshold: float = 0.70,
    lookback_hours: int = 72,
) -> list[DistilledTopic]:
    """Filter items that already exist in the database.

    Phase 1: URL exact match — if source_url already in topics, skip.
    Phase 2: Intra-batch dedup — remove near-duplicates within the new batch.
    Phase 3: Cross-DB title similarity — if similar title exists in last N hours, skip.

    Returns only new items (safe to insert).
    """
    if not items:
        return []

    # Phase 1: Check existing URLs
    urls = [item.source_url for item in items if item.source_url]
    existing_urls: set[str] = set()
    if urls:
        placeholders = ",".join(["?" for _ in urls])
        rows = await db.execute(
            f"SELECT source_url FROM topics WHERE source_url IN ({placeholders})",
            urls,
        )
        existing_urls = {r[0] for r in await rows.fetchall() if r[0]}

    # Phase 2: Intra-batch dedup (removes LLM distillation variants)
    items = _dedup_intra_batch(items, threshold=title_threshold)

    # Phase 3: Check recent titles for similarity
    from datetime import datetime, timedelta
    lookback_iso = (datetime.now() - timedelta(hours=lookback_hours)).isoformat()
    recent = await db.execute(
        "SELECT id, title FROM topics WHERE created_at > ?",
        (lookback_iso,),
    )
    recent_titles = [(r["id"], r["title"]) for r in await recent.fetchall()]

    new_items = []
    for item in items:
        # URL check
        if item.source_url and item.source_url in existing_urls:
            logger.debug("Dedup URL: %s", item.source_url[:80])
            continue

        # Title similarity check against DB
        too_similar = False
        for _tid, existing_title in recent_titles:
            sim = compute_title_similarity(item.title, existing_title if existing_title else "")
            if sim >= title_threshold:
                too_similar = True
                logger.debug("Dedup title '%s' ~= '%s' (%.2f)", item.title[:40], existing_title[:40], sim)
                break

        if not too_similar:
            new_items.append(item)

    logger.info("Dedup: %d in → %d new (url matches: %d)",
                len(items), len(new_items), len(existing_urls))
    return new_items
