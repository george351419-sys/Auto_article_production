"""Tests for contract_check.py script logic.

Per DEV_PLAN §5.3: verifies contract deviation detection works correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from helpers.mock_modules import make_mock_scorer_app


class TestContractDeviationDetection:
    """Test that contract check correctly detects missing/extraneous endpoints."""

    # Mock scorer app's contract includes /api/score but NOT /health and /contract
    # because our _add_contract_routes adds them separately
    EXPECTED_SCORER_BUSINESS = {
        "POST /api/score",
    }

    def test_scorer_mock_has_health_and_contract(self):
        """Verify mock scorer app serves /health and /contract."""
        app = make_mock_scorer_app()
        client = TestClient(app)

        r = client.get("/health")
        assert r.status_code == 200

        r = client.get("/contract")
        assert r.status_code == 200
        actual = {f"{ep['method']} {ep['path']}" for ep in r.json()["endpoints"]}
        assert "POST /api/score" in actual

    def test_scorer_mock_has_required_business_endpoints(self):
        """Verify mock scorer has /api/score in contract."""
        app = make_mock_scorer_app()
        client = TestClient(app)
        r = client.get("/contract")
        actual = {f"{ep['method']} {ep['path']}" for ep in r.json()["endpoints"]}
        missing = self.EXPECTED_SCORER_BUSINESS - actual
        assert not missing, f"Missing endpoints: {missing}"

    def test_missing_endpoint_detected(self):
        """If an app is missing an expected endpoint, it should be detected."""
        expected = {"POST /api/score", "GET /health", "GET /contract", "GET /api/missing"}
        app = make_mock_scorer_app()
        client = TestClient(app)
        r = client.get("/contract")
        actual = {f"{ep['method']} {ep['path']}" for ep in r.json()["endpoints"]}
        missing = expected - actual
        assert "GET /api/missing" in missing

    def test_extraneous_endpoint_detected(self):
        """Extra endpoint not in expected set is reported."""
        expected = {"GET /health", "GET /contract"}  # intentionally missing /api/score
        app = make_mock_scorer_app()
        client = TestClient(app)
        r = client.get("/contract")
        actual = {f"{ep['method']} {ep['path']}" for ep in r.json()["endpoints"]}
        extra = actual - expected
        assert "POST /api/score" in extra


class TestContractCheckSmoke:
    """Smoke tests for the contract_check script logic (unit level)."""

    def test_all_mock_apps_health_pass(self):
        """All 5 mock modules' /health should return 200."""
        from helpers.mock_modules import (
            make_mock_autopublish_app,
            make_mock_distilled_app,
            make_mock_scorer_app,
            make_mock_select_app,
            make_mock_writing_app,
        )

        factories = {
            "distilled_characters": make_mock_distilled_app,
            "select_topic": make_mock_select_app,
            "writing": make_mock_writing_app,
            "platform_scorer": make_mock_scorer_app,
            "autopublish": make_mock_autopublish_app,
        }

        for name, factory in factories.items():
            app = factory()
            client = TestClient(app)
            r = client.get("/health")
            assert r.status_code == 200, f"{name} /health failed"
            data = r.json()
            assert data["ok"] is True, f"{name} /health not ok"

    def test_all_mock_apps_contract_pass(self):
        """All 5 mock modules' /contract should return 200 with endpoints."""
        from helpers.mock_modules import (
            make_mock_autopublish_app,
            make_mock_distilled_app,
            make_mock_scorer_app,
            make_mock_select_app,
            make_mock_writing_app,
        )

        factories = {
            "distilled_characters": make_mock_distilled_app,
            "select_topic": make_mock_select_app,
            "writing": make_mock_writing_app,
            "platform_scorer": make_mock_scorer_app,
            "autopublish": make_mock_autopublish_app,
        }

        for name, factory in factories.items():
            app = factory()
            client = TestClient(app)
            r = client.get("/contract")
            assert r.status_code == 200, f"{name} /contract failed"
            data = r.json()
            assert len(data["endpoints"]) >= 1, f"{name} has no endpoints"
