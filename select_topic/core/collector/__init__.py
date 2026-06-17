"""Collector package — public API surface.

Usage:
    from core.collector import try_scrape_all, distill_batch, deduplicate
"""
from core.collector.base import HotItem, DistilledTopic
from core.collector.direct_scraper import (
    try_scrape_all, scrape_all, fetch_url_content,
    TrendRadarClient, scrape_via_trendradar, SCRAPERS, DEFAULT_PLATFORMS,
)
from core.collector.topic_distiller import distill_batch, distill_single_url
from core.collector.dedup import deduplicate, compute_title_similarity
