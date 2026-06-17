-- Auto Content Production · Orchestrator · Migration 0002
-- Purpose: scheduler_v2 needs a writing_task_detail column on article to
-- store the live writing-module status snapshot (agent outputs, score
-- reports, current_round). Without it, every poll cycle crashes with
-- `no such column: writing_task_detail` and the article falls into failed.

ALTER TABLE article ADD COLUMN writing_task_detail TEXT;

UPDATE settings SET value = '2', updated_at = '2026-06-17T00:00:00Z'
 WHERE key = 'schema_version';
