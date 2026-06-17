"""Contract adapter — unified /health and /contract endpoints per LLD §3.

Provides GET /health (health check) and GET /contract (endpoint manifest)
for the platform_scorer module.
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
        "module": "platform_scorer",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - START_TIME),
        "deps_ok": True,
    }


@router.get("/contract")
async def contract():
    return {
        "module": "platform_scorer",
        "contract_version": "1.0",
        "endpoints": [
            {"path": "/api/score", "method": "POST", "purpose": "score_article"},
            {"path": "/health", "method": "GET", "purpose": "health_check"},
            {"path": "/contract", "method": "GET", "purpose": "contract_manifest"},
        ],
    }
