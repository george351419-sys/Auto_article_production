-- Auto Content Production · Orchestrator · Initial Schema
-- Migration: 0001_init
-- Created: 2026-06-16
-- Related: LLD §2

PRAGMA foreign_keys = ON;

-- ============================================================
-- topic — 选题
-- ============================================================
CREATE TABLE IF NOT EXISTS topic (
    id               TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    source           TEXT NOT NULL,
    source_url       TEXT,
    brief            TEXT,
    raw_material     TEXT,
    entities         TEXT,
    topic_keywords   TEXT,
    status           TEXT NOT NULL,
    dup_of_topic_id  TEXT,
    user_submitted   INTEGER NOT NULL DEFAULT 0,
    trace_id         TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topic_status     ON topic(status);
CREATE INDEX IF NOT EXISTS idx_topic_created    ON topic(created_at);
CREATE INDEX IF NOT EXISTS idx_topic_normalized ON topic(title_normalized);

-- ============================================================
-- article — 文章任务
-- ============================================================
CREATE TABLE IF NOT EXISTS article (
    id                  TEXT PRIMARY KEY,
    topic_id            TEXT NOT NULL REFERENCES topic(id),
    character_id        TEXT,
    status              TEXT NOT NULL,
    writing_task_id     TEXT,
    final_package       TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    next_retry_at       TEXT,
    last_error_code     TEXT,
    last_error_message  TEXT,
    review_deadline_at  TEXT,
    trace_id            TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_article_status ON article(status);
CREATE INDEX IF NOT EXISTS idx_article_topic  ON article(topic_id);
CREATE INDEX IF NOT EXISTS idx_article_retry  ON article(next_retry_at) WHERE next_retry_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_article_review ON article(review_deadline_at) WHERE status = 'reviewing';

-- ============================================================
-- score — 平台评分
-- ============================================================
CREATE TABLE IF NOT EXISTS score (
    id            TEXT PRIMARY KEY,
    article_id    TEXT NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    platform      TEXT NOT NULL,
    score         INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    generation_n  INTEGER NOT NULL DEFAULT 1,
    generated_at  TEXT NOT NULL,
    UNIQUE (article_id, platform, generation_n)
);
CREATE INDEX IF NOT EXISTS idx_score_article ON score(article_id);

-- ============================================================
-- publish — 发布记录
-- ============================================================
CREATE TABLE IF NOT EXISTS publish (
    id              TEXT PRIMARY KEY,
    article_id      TEXT NOT NULL REFERENCES article(id),
    platform        TEXT NOT NULL,
    status          TEXT NOT NULL,
    platform_url    TEXT,
    platform_msg_id TEXT,
    error_code      TEXT,
    error_message   TEXT,
    scheduled_at    TEXT NOT NULL,
    executed_at     TEXT,
    duration_ms     INTEGER,
    trace_id        TEXT NOT NULL,
    UNIQUE (article_id, platform)
);
CREATE INDEX IF NOT EXISTS idx_publish_status    ON publish(status);
CREATE INDEX IF NOT EXISTS idx_publish_scheduled ON publish(scheduled_at);

-- ============================================================
-- asset — 图片/封面落地
-- ============================================================
CREATE TABLE IF NOT EXISTS asset (
    id            TEXT PRIMARY KEY,
    article_id    TEXT NOT NULL REFERENCES article(id) ON DELETE CASCADE,
    platform      TEXT,
    kind          TEXT NOT NULL,
    local_path    TEXT NOT NULL,
    origin_url    TEXT,
    bytes         INTEGER,
    sha256        TEXT,
    downloaded_at TEXT NOT NULL,
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_asset_article ON asset(article_id);
CREATE INDEX IF NOT EXISTS idx_asset_deleted ON asset(deleted_at) WHERE deleted_at IS NULL;

-- ============================================================
-- audit_log — 状态切换审计
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    from_state   TEXT,
    to_state     TEXT NOT NULL,
    trigger      TEXT NOT NULL,
    actor        TEXT,
    payload_json TEXT,
    trace_id     TEXT NOT NULL,
    at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_at     ON audit_log(at);

-- ============================================================
-- cleanup_log — 清理任务日志
-- ============================================================
CREATE TABLE IF NOT EXISTS cleanup_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger           TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    freed_bytes       INTEGER,
    deleted_topics    INTEGER DEFAULT 0,
    deleted_articles  INTEGER DEFAULT 0,
    deleted_assets    INTEGER DEFAULT 0,
    deleted_logs      INTEGER DEFAULT 0,
    error_message     TEXT
);

-- ============================================================
-- settings — 运行时可调参数
-- ============================================================
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('schema_version',         '1',            '2026-06-16T00:00:00Z'),
    ('cleanup.threshold_gb',   '2.5',          '2026-06-16T00:00:00Z'),
    ('cleanup.sweep_cron',     '0 */3 * * *',  '2026-06-16T00:00:00Z'),
    ('cleanup.guard_minutes',  '10',           '2026-06-16T00:00:00Z'),
    ('cleanup.vacuum_cron',    '0 3 * * 0',    '2026-06-16T00:00:00Z'),
    ('review.timeout_hours',   '2',            '2026-06-16T00:00:00Z'),
    ('boost.daily_check_hour', '23',           '2026-06-16T00:00:00Z'),
    ('retry.max_attempts',     '3',            '2026-06-16T00:00:00Z'),
    ('scoring.publish_threshold', '70',        '2026-06-16T00:00:00Z'),
    ('scoring.boost_min_score',   '50',        '2026-06-16T00:00:00Z');
