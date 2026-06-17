"""Configuration routes."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter

from core.scoring_engine import WEIGHTS
from server.database import get_db

logger = logging.getLogger("config")
router = APIRouter(prefix="/config", tags=["config"])


@router.get("/weights")
async def get_weights():
    db = await get_db()
    row = await db.execute("SELECT value FROM config WHERE key = 'weights'")
    result = await row.fetchone()
    await db.close()
    if result:
        return json.loads(result[0])
    return WEIGHTS


@router.put("/weights")
async def update_weights(body: dict):
    db = await get_db()
    now = datetime.now().isoformat()
    await db.execute(
        "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("weights", json.dumps(body, ensure_ascii=False), now),
    )
    await db.commit()
    await db.close()
    return {"updated": True}


@router.get("/rating-thresholds")
async def get_rating_thresholds():
    db = await get_db()
    row = await db.execute("SELECT value FROM config WHERE key = 'rating_thresholds'")
    result = await row.fetchone()
    await db.close()
    if result:
        return json.loads(result[0])
    return {"S": 90, "A": 80, "B": 70, "C": 0}
