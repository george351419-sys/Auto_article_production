"""M0 · 0001_init.sql 迁移单元测试.

验收点 (DEV_PLAN M0):
- 8 张表全部建出
- 全部索引建出
- settings 初始记录正确写入
- 二次运行迁移幂等
- WAL / 外键 / busy_timeout PRAGMA 生效
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from orchestrator import db as db_mod
from orchestrator.migrate import (
    MIGRATION_PATTERN,
    MigrationError,
    discover_migrations,
    get_current_version,
    migrate,
)

pytestmark = pytest.mark.M0


EXPECTED_TABLES = {
    "topic",
    "article",
    "score",
    "publish",
    "asset",
    "audit_log",
    "cleanup_log",
    "settings",
}

# Indexes declared in 0001_init.sql (excluding implicit ones SQLite creates
# for PRIMARY KEY and UNIQUE constraints — those start with sqlite_autoindex).
EXPECTED_INDEXES = {
    "idx_topic_status",
    "idx_topic_created",
    "idx_topic_normalized",
    "idx_article_status",
    "idx_article_topic",
    "idx_article_retry",
    "idx_article_review",
    "idx_score_article",
    "idx_publish_status",
    "idx_publish_scheduled",
    "idx_asset_article",
    "idx_asset_deleted",
    "idx_audit_entity",
    "idx_audit_at",
}

EXPECTED_SETTINGS_KEYS = {
    "schema_version",
    "cleanup.threshold_gb",
    "cleanup.sweep_cron",
    "cleanup.guard_minutes",
    "cleanup.vacuum_cron",
    "review.timeout_hours",
    "boost.daily_check_hour",
    "retry.max_attempts",
    "scoring.publish_threshold",
    "scoring.boost_min_score",
}


def test_discover_migrations_finds_0001(migrations_dir: Path):
    found = discover_migrations(migrations_dir)
    assert (1, migrations_dir / "0001_init.sql") in found


def test_migration_pattern_rejects_garbage():
    assert MIGRATION_PATTERN.match("0001_init.sql") is not None
    assert MIGRATION_PATTERN.match("readme.md") is None
    assert MIGRATION_PATTERN.match("init.sql") is None
    assert MIGRATION_PATTERN.match("1_init.sql") is None


def test_migrate_creates_all_tables(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    applied = migrate(db_path, migrations_dir)
    assert applied[0] == 1
    assert applied == sorted(applied), "migrations must be applied in order"

    conn = db_mod.connect(db_path)
    try:
        tables = set(db_mod.list_tables(conn))
        assert EXPECTED_TABLES.issubset(tables), (
            f"missing tables: {EXPECTED_TABLES - tables}"
        )
    finally:
        conn.close()


def test_migrate_creates_all_indexes(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    migrate(db_path, migrations_dir)

    conn = db_mod.connect(db_path)
    try:
        indexes = set(db_mod.list_indexes(conn))
        # filter out partial-index conditional names if any sqlite quirks
        missing = EXPECTED_INDEXES - indexes
        assert not missing, f"missing indexes: {missing}"
    finally:
        conn.close()


def test_migrate_inserts_initial_settings(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    migrate(db_path, migrations_dir)

    conn = db_mod.connect(db_path)
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        seen = {r["key"]: r["value"] for r in rows}
        assert EXPECTED_SETTINGS_KEYS.issubset(seen.keys())
        # schema_version reflects the last applied migration; bumps as we add new ones.
        assert int(seen["schema_version"]) >= 1
        assert seen["cleanup.threshold_gb"] == "2.5"
        assert seen["review.timeout_hours"] == "2"
        assert seen["boost.daily_check_hour"] == "23"
        assert seen["scoring.publish_threshold"] == "70"
        assert seen["scoring.boost_min_score"] == "50"
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    first = migrate(db_path, migrations_dir)
    second = migrate(db_path, migrations_dir)
    assert first and first[0] == 1
    assert second == [], "second run should apply nothing"


def test_get_current_version_when_uninitialized(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    conn = db_mod.connect(db_path)
    try:
        # No settings table exists yet — should return 0, not raise
        assert get_current_version(conn) == 0
    finally:
        conn.close()


def test_get_current_version_after_migration(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    applied = migrate(db_path, migrations_dir)
    conn = db_mod.connect(db_path)
    try:
        assert get_current_version(conn) == applied[-1]
    finally:
        conn.close()


def test_pragmas_applied(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    migrate(db_path, migrations_dir)
    conn = db_mod.connect(db_path)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert foreign_keys == 1
        assert busy_timeout >= 5000
    finally:
        conn.close()


def test_foreign_keys_enforced(tmp_path: Path, migrations_dir: Path):
    """ON DELETE CASCADE / NOT NULL REFERENCES should kick in."""
    db_path = tmp_path / "pipeline.db"
    migrate(db_path, migrations_dir)
    conn = db_mod.connect(db_path)
    try:
        # article.topic_id must reference an existing topic row
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO article (id, topic_id, status, trace_id, "
                "created_at, updated_at) VALUES "
                "('a1', 'nonexistent-topic', 'collected', 't1', "
                "'2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')"
            )
            conn.commit()
    finally:
        conn.close()


def test_score_unique_constraint(tmp_path: Path, migrations_dir: Path):
    db_path = tmp_path / "pipeline.db"
    migrate(db_path, migrations_dir)
    conn = db_mod.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO topic (id, title, title_normalized, source, status, "
            "trace_id, created_at, updated_at) "
            "VALUES ('t1', 'T', 't', 'user', 'collected', 'trace', "
            "'2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO article (id, topic_id, status, trace_id, "
            "created_at, updated_at) VALUES "
            "('a1', 't1', 'scored', 'trace', "
            "'2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO score (id, article_id, platform, score, reason, "
            "generation_n, generated_at) VALUES "
            "('s1', 'a1', 'wechat', 88, 'good', 1, '2026-06-16T00:00:00Z')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO score (id, article_id, platform, score, reason, "
                "generation_n, generated_at) VALUES "
                "('s2', 'a1', 'wechat', 90, 'good', 1, '2026-06-16T00:00:00Z')"
            )
        conn.commit()
    finally:
        conn.close()


def test_migration_dir_missing_raises(tmp_path: Path):
    with pytest.raises(MigrationError):
        migrate(tmp_path / "x.db", tmp_path / "nonexistent")


def test_discover_migrations_skips_non_pattern_files(tmp_path: Path):
    (tmp_path / "0001_init.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")
    (tmp_path / "init.sql").write_text("-- no version prefix", encoding="utf-8")
    (tmp_path / "0002_x.sql").write_text("SELECT 2;", encoding="utf-8")

    found = discover_migrations(tmp_path)
    versions = [v for v, _ in found]
    assert versions == [1, 2]


def test_migrations_dir_empty_raises(tmp_path: Path):
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    (mdir / "README.md").write_text("nothing here", encoding="utf-8")

    with pytest.raises(MigrationError, match="no migrations found"):
        migrate(tmp_path / "x.db", mdir)


def test_get_current_version_when_key_missing(tmp_path: Path):
    """settings table exists but schema_version row absent → return 0."""
    db_path = tmp_path / "x.db"
    conn = db_mod.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"
        )
        conn.commit()
        assert get_current_version(conn) == 0
    finally:
        conn.close()


def test_bad_sql_raises_migration_error(tmp_path: Path):
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    (mdir / "0001_bad.sql").write_text("THIS IS NOT SQL;", encoding="utf-8")

    with pytest.raises(MigrationError, match="0001_bad.sql failed"):
        migrate(tmp_path / "x.db", mdir)
