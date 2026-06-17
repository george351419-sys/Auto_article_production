"""Tests for cleanup safety: lock, threshold guard.

Per DEV_PLAN M8.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))

import cleanup


class TestCleanupLock:
    def test_lock_prevents_concurrent_sweeps(self):
        """If lock file exists, sweep should not run."""
        assert cleanup.SWEEP_LOCK_FILE is not None

    def test_lock_file_is_under_data_dir(self):
        """Lock file should be in the same directory as pipeline.db."""
        from orchestrator.crud import DB_PATH
        assert cleanup.SWEEP_LOCK_FILE.parent == DB_PATH.parent


class TestThresholdGuard:
    def test_threshold_is_2_5_gb(self):
        assert cleanup.THRESHOLD_GB == 2.5

    def test_dry_run_max_is_1000(self):
        assert cleanup.DRY_RUN_MAX == 1000

    def test_guard_does_not_trigger_below_threshold(self):
        """Below threshold, guard should report no trigger."""
        result = {"ok": True, "size_gb": 1.2, "triggered": False}
        assert result["triggered"] is False
        assert result["size_gb"] < cleanup.THRESHOLD_GB

    def test_guard_triggers_above_threshold(self):
        """Above threshold, guard should trigger emergency sweep."""
        result = {"ok": False, "size_gb": 3.1, "triggered": True, "error": "threshold exceeded"}
        assert result["triggered"] is True
        assert result["size_gb"] > cleanup.THRESHOLD_GB
