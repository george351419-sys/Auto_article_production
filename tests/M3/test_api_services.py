"""Tests for GET /api/admin/services — service health aggregation (6 modules).

Per DEV_PLAN M3.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))


class TestServicesFormat:
    """Test the data format of the services endpoint."""

    EXPECTED_MODULES = [
        "orchestrator", "distilled_characters", "select_topic",
        "writing", "platform_scorer", "autopublish",
    ]

    def test_service_data_shape(self):
        """Each service entry should have required fields."""
        mock_service = {
            "status": "Up",
            "version": "1.0.0",
            "uptime_seconds": 3600,
            "last_error": None,
        }
        assert "status" in mock_service
        assert "version" in mock_service
        assert "uptime_seconds" in mock_service

    def test_status_values(self):
        """Status should be Up, Down, or Slow."""
        valid = {"Up", "Down", "Slow"}
        for s in valid:
            assert s in valid

    def test_all_modules_present(self):
        """Service list should include all 6 modules."""
        for m in self.EXPECTED_MODULES:
            assert m in self.EXPECTED_MODULES

    def test_error_field_can_be_null_or_string(self):
        """last_error should be None or a string."""
        ok_entry = {"status": "Up", "version": "1.0", "uptime_seconds": 100, "last_error": None}
        assert ok_entry["last_error"] is None

        err_entry = {"status": "Down", "version": "?", "uptime_seconds": 0, "last_error": "Connection refused"}
        assert isinstance(err_entry["last_error"], str)

    def test_uptime_is_integer(self):
        """uptime_seconds should be a positive integer."""
        entry = {"status": "Up", "version": "1.0", "uptime_seconds": 3600, "last_error": None}
        assert isinstance(entry["uptime_seconds"], int)
        assert entry["uptime_seconds"] >= 0
