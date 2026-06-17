"""Shared pytest fixtures.

Convention (DEV_PLAN §5.3):
- Tests must not depend on real network, real LLM, real wall-clock, or
  real on-disk SQLite at fixed paths. Use tmp_path / in-memory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"
for p in (str(TESTS_DIR), str(PROJECT_ROOT), str(ORCHESTRATOR_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def migrations_dir() -> Path:
    return PROJECT_ROOT / "orchestrator" / "migrations"
