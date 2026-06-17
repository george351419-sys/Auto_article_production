"""Contract adapter — unified /health and /contract endpoints per LLD §3.

Provides GET /health (health check) and GET /contract (endpoint manifest)
for the Autopublish module. Route handler functions for the custom HTTP server.
"""
from __future__ import annotations

import json
import time

START_TIME = time.time()

MODULE = "autopublish"
VERSION = "3.0.5"
CONTRACT_VERSION = "1.0"

ENDPOINTS = [
    {"path": "/api/publish", "method": "POST", "purpose": "execute_publish"},
    {"path": "/api/publish/{plan_id}", "method": "GET", "purpose": "get_publish_status"},
    {"path": "/api/accounts", "method": "GET", "purpose": "list_accounts"},
    {"path": "/api/accounts", "method": "PUT", "purpose": "update_accounts"},
    {"path": "/api/accounts/verify", "method": "POST", "purpose": "verify_cookie"},
    {"path": "/api/status", "method": "GET", "purpose": "system_status"},
    {"path": "/api/log", "method": "GET", "purpose": "publish_log"},
]


def handle_health() -> tuple[int, dict]:
    return 200, {
        "ok": True,
        "module": MODULE,
        "version": VERSION,
        "uptime_seconds": int(time.time() - START_TIME),
        "deps_ok": True,
    }


def handle_contract() -> tuple[int, dict]:
    return 200, {
        "module": MODULE,
        "contract_version": CONTRACT_VERSION,
        "endpoints": ENDPOINTS,
    }
