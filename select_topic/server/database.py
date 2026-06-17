"""Database connection and query helpers."""
from __future__ import annotations

import aiosqlite
from pathlib import Path

from config import load_config

_db_path: str | None = None


def get_db_path() -> str:
    global _db_path
    if _db_path is None:
        config = load_config()
        _db_path = config.get("db_path", "data/select_topic.db")
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    return _db_path


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_db_path())
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    """Ensure schema exists on startup."""
    from init_db import SCHEMA
    db = await aiosqlite.connect(get_db_path())
    await db.executescript(SCHEMA)
    await db.commit()
    await db.close()
