"""Background collection scheduler.

Runs an asyncio loop that triggers collection every N seconds.
The scheduler is started during FastAPI startup and stopped during shutdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

from core.collector import DEFAULT_PLATFORMS, try_scrape_all, distill_batch, deduplicate
from core.scoring_engine import score_topic
from core.matching_engine import match_celebrities_rule_based
from server.database import get_db
from config import load_config

logger = logging.getLogger("scheduler")


class CollectionScheduler:
    """Background asyncio task for periodic hot list collection."""

    def __init__(self):
        cfg = load_config().get("collector", {})
        self.enabled = cfg.get("enabled", True)
        self.interval = cfg.get("interval_seconds", 3600)
        self.platforms = cfg.get("platforms", DEFAULT_PLATFORMS)
        self.score_threshold = cfg.get("auto_score_threshold", 80)
        self.default_positioning = cfg.get("default_positioning", "business_tech")
        self.trendradar_enabled = cfg.get("trendradar", {}).get("enabled", True)
        self.scrape_enabled = cfg.get("direct_scrape", {}).get("enabled", True)
        self.dedup_threshold = cfg.get("dedup", {}).get("title_similarity_threshold", 0.70)
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_run: str = ""
        self.last_status: str = "idle"
        self.is_collecting: bool = False

    async def start(self):
        """Start the background collection loop."""
        if not self.enabled:
            logger.info("Collector disabled in config, skipping scheduler start")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Collection scheduler started (interval=%ds, threshold=%d)",
                    self.interval, self.score_threshold)

    async def stop(self):
        """Gracefully stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Collection scheduler stopped")

    async def _loop(self):
        """Main loop: sleep, then run collection."""
        # First run: delay 30s to let server warm up
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Collection cycle failed")
            # Sleep between cycles
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                return

    async def _run_cycle(self) -> str:
        """Execute one full collection cycle across all platforms.

        Data flow (all in memory, nothing written to disk):
          1. Scrape hot lists → [HotItem]
          2. LLM distill → [DistilledTopic]
          3. Dedup against DB → [DistilledTopic] (new only)
          4. For each new valid topic: score + match + insert
          5. Invalid (entertainment/politics) items are silently dropped
        """
        batch_id = str(uuid4())
        self.is_collecting = True
        self.last_status = "running"
        started = datetime.now()
        logger.info("=== Collection cycle %s starting ===", batch_id[:8])

        db = await get_db()

        try:
            # Step 1: Scrape all platforms (try TrendRadar, fall back to direct)
            platform_results = await try_scrape_all(
                self.platforms,
                use_trendradar=self.trendradar_enabled,
                use_direct=self.scrape_enabled,
            )
            total_fetched = sum(len(v) for v in platform_results.values())

            # Step 2: Distill each platform's items
            all_distilled = []
            for plat, items in platform_results.items():
                if not items:
                    await _log_collection(db, batch_id, plat, 0, 0, "empty")
                    continue

                distilled = await distill_batch(items)
                # Raw items (items, platform_results) go out of scope here → GC
                valid = [d for d in distilled if d.is_valid]
                invalid_count = len(distilled) - len(valid)
                if invalid_count:
                    logger.info("Filtered %d invalid items from %s (entertainment/politics)",
                               invalid_count, plat)
                all_distilled.extend(valid)

            # Step 3: Dedup
            new_items = await deduplicate(db, all_distilled, title_threshold=self.dedup_threshold)
            all_distilled.clear()  # Free memory

            # Step 4: Score, match, insert for each new item
            total_inserted = 0
            now = datetime.now().isoformat()
            for item in new_items:
                try:
                    # Score
                    score = score_topic(
                        title=item.title,
                        content=item.raw_content,
                        weight_mode="new_account",
                        platform="wechat",
                        positioning=self.default_positioning,
                    )
                    # Only keep topics above threshold
                    if score.total_score < self.score_threshold:
                        continue

                    # Insert topic
                    topic_id = str(uuid4())
                    source_material_json = json.dumps(item.source_material, ensure_ascii=False)
                    await db.execute(
                        """INSERT INTO topics (id, title, source_url, source_type, source_platform,
                           raw_content, heat_level, source_material, batch_id, status, created_at, updated_at)
                           VALUES (?, ?, ?, 'auto', ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                        (topic_id, item.title, item.source_url, item.source_platform,
                         item.raw_content, item.heat_level, source_material_json, batch_id, now, now),
                    )

                    # Insert score
                    score.topic_id = topic_id
                    await db.execute(
                        """INSERT INTO score_results (id, topic_id, relevance_score, timeliness_score,
                           value_score, compliance_score, competition_score, total_score, grade,
                           bonus_details, weight_mode, platform, positioning, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (score.id, topic_id, score.relevance_score, score.timeliness_score,
                         score.value_score, score.compliance_score, score.competition_score,
                         score.total_score, score.grade, score.bonus_details,
                         score.weight_mode, score.platform, score.positioning, now),
                    )

                    # Rule-based match (fast, no LLM cost for auto-collected items)
                    matches = await match_celebrities_rule_based(
                        title=item.title, content=item.raw_content,
                    )
                    for m in matches:
                        m.topic_id = topic_id
                        await db.execute(
                            """INSERT INTO match_results (id, topic_id, celebrity_id, celebrity_name,
                               match_score, match_reason, rank, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (str(uuid4()), topic_id, m.celebrity_id, m.celebrity_name,
                             m.match_score, m.match_reason, m.rank, now),
                        )

                    # Update topic status to matched
                    await db.execute(
                        "UPDATE topics SET status = 'matched', updated_at = ? WHERE id = ?",
                        (now, topic_id),
                    )

                    total_inserted += 1
                except Exception as e:
                    logger.error("Failed to ingest item '%s': %s", item.title[:40], e)

            # Log per-platform stats
            for plat in self.platforms:
                plat_fetched = len(platform_results.get(plat, []))
                await _log_collection(db, batch_id, plat, plat_fetched, total_inserted, "success")

            await db.commit()
            elapsed = (datetime.now() - started).total_seconds()
            self.last_status = "completed"
            self.last_run = datetime.now().isoformat()
            logger.info("=== Collection cycle %s done: %d fetched → %d new in %.1fs ===",
                       batch_id[:8], total_fetched, total_inserted, elapsed)

        except Exception:
            self.last_status = "failed"
            await db.rollback()
            raise
        finally:
            self.is_collecting = False
            await db.close()

        return batch_id

    async def trigger_manual(self) -> dict:
        """Manually trigger a collection cycle. Returns summary."""
        if self.is_collecting:
            return {"status": "already_running", "message": "A collection cycle is already in progress"}

        try:
            batch_id = await self._run_cycle()
            return {
                "status": "completed",
                "batch_id": batch_id,
                "last_run": self.last_run,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": self.is_collecting,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "interval_seconds": self.interval,
        }


async def _log_collection(db, batch_id: str, source_name: str,
                          fetched: int, new: int, status: str, error: str = ""):
    """Write a collection log entry."""
    now = datetime.now().isoformat()
    await db.execute(
        """INSERT INTO collection_logs (id, batch_id, source_name, items_fetched,
           items_new, status, error_message, started_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid4()), batch_id, source_name, fetched, new, status, error, now, now),
    )
