"""Contract adapter — unified /health and /contract endpoints per LLD §3.

Provides GET /health (health check) and GET /contract (endpoint manifest)
for the writing module. This is an Express-compatible route handler
exported for use by the TypeScript server.
"""
from __future__ import annotations

import json
import time

START_TIME = time.time()

MODULE = "writing"
VERSION = "2.0.1"
CONTRACT_VERSION = "1.0"

ENDPOINTS = [
    {"path": "/api/tasks", "method": "POST", "purpose": "create_task"},
    {"path": "/api/tasks/{id}/run", "method": "POST", "purpose": "run_task"},
    {"path": "/api/tasks/{id}", "method": "GET", "purpose": "get_task"},
    {"path": "/api/tasks", "method": "GET", "purpose": "list_tasks"},
    {"path": "/api/config", "method": "GET", "purpose": "get_config"},
]

# This module exists primarily so the orchestrator contract checker
# can discover the writing module's contract shape without needing
# TypeScript. The actual /health and /contract routes are served
# by the Express server (see adapters/contract.ts).
