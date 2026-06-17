"""Initialize SQLite database schema and default data."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_url TEXT,
    source_type TEXT DEFAULT 'manual',
    source_platform TEXT,
    raw_content TEXT,
    heat_level TEXT,
    status TEXT DEFAULT 'pending',
    source_material TEXT DEFAULT '[]',
    batch_id TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS score_results (
    id TEXT PRIMARY KEY,
    topic_id TEXT UNIQUE,
    relevance_score REAL,
    timeliness_score REAL,
    value_score REAL,
    compliance_score REAL,
    competition_score REAL,
    total_score REAL,
    grade TEXT,
    bonus_details TEXT,
    weight_mode TEXT DEFAULT 'new_account',
    platform TEXT DEFAULT 'wechat',
    positioning TEXT DEFAULT 'business_tech',
    scoring_version TEXT DEFAULT '1.0',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS match_results (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
    celebrity_id TEXT,
    celebrity_name TEXT,
    match_score REAL,
    match_reason TEXT,
    rank INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS review_logs (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
    action TEXT,
    previous_status TEXT,
    new_status TEXT,
    operator TEXT DEFAULT 'admin',
    note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS collection_logs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    items_fetched INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS collection_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
"""

WEIGHT_CONFIG = {
    "new_account": {
        "label": "新号冷启动模式",
        "platforms": {
            "wechat": {"relevance": 0.40, "timeliness": 0.25, "value": 0.15, "compliance": 0.12, "competition": 0.08},
            "toutiao": {"relevance": 0.35, "timeliness": 0.35, "value": 0.10, "compliance": 0.15, "competition": 0.15},
            "xiaohongshu": {"relevance": 0.35, "timeliness": 0.25, "value": 0.20, "compliance": 0.12, "competition": 0.08},
        },
    },
    "old_account": {
        "label": "老号深度运营模式",
        "platforms": {
            "wechat": {"relevance": 0.35, "timeliness": 0.20, "value": 0.25, "compliance": 0.12, "competition": 0.08},
            "toutiao": {"relevance": 0.30, "timeliness": 0.30, "value": 0.15, "compliance": 0.15, "competition": 0.10},
            "xiaohongshu": {"relevance": 0.32, "timeliness": 0.20, "value": 0.28, "compliance": 0.12, "competition": 0.08},
        },
    },
}


def init_db(db_path: str = "data/select_topic.db") -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    from datetime import datetime
    now = datetime.now().isoformat()

    # Seed weight config if not present
    cursor = conn.execute("SELECT COUNT(*) FROM config WHERE key = 'weights'")
    if cursor.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
            ("weights", json.dumps(WEIGHT_CONFIG, ensure_ascii=False), now),
        )

    # Seed rating thresholds
    cursor = conn.execute("SELECT COUNT(*) FROM config WHERE key = 'rating_thresholds'")
    if cursor.fetchone()[0] == 0:
        thresholds = {"S": 90, "A": 80, "B": 70, "C": 0}
        conn.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
            ("rating_thresholds", json.dumps(thresholds, ensure_ascii=False), now),
        )

    conn.commit()
    return conn


if __name__ == "__main__":
    db_path = "data/select_topic.db"
    conn = init_db(db_path)
    print(f"Database initialized at {db_path}")
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    for t in tables:
        print(f"  Table: {t[0]}")
    conn.close()
