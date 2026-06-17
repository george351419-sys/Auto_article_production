"""Contract adapter — unified /health and /contract endpoints per LLD §3.

Provides GET /health (health check) and GET /contract (endpoint manifest)
for the select_topic module.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

START_TIME = time.time()

router = APIRouter(tags=["contract"])


@router.get("/health")
async def health():
    return {
        "ok": True,
        "module": "select_topic",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - START_TIME),
        "deps_ok": True,
    }


@router.get("/contract")
async def contract():
    return {
        "module": "select_topic",
        "contract_version": "1.0",
        "endpoints": [
            {"path": "/api/collect/trigger", "method": "POST", "purpose": "trigger_collection"},
            {"path": "/api/topics", "method": "GET", "purpose": "list_topics"},
            {"path": "/api/topics", "method": "POST", "purpose": "create_topic"},
            {"path": "/api/topics/{id}", "method": "GET", "purpose": "get_topic"},
            {"path": "/api/topics/{id}/match", "method": "POST", "purpose": "match_topic"},
            {"path": "/api/topics/{id}/review", "method": "POST", "purpose": "review_topic"},
        ],
    }
