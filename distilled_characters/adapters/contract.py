"""Contract adapter — unified /health and /contract endpoints per LLD §3.

Provides GET /health (health check) and GET /contract (endpoint manifest)
for the distilled_characters module.
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
        "module": "distilled_characters",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - START_TIME),
        "deps_ok": True,
    }


@router.get("/contract")
async def contract():
    return {
        "module": "distilled_characters",
        "contract_version": "1.0",
        "endpoints": [
            {"path": "/api/characters", "method": "GET", "purpose": "list_characters"},
            {"path": "/api/match", "method": "POST", "purpose": "match_character"},
            {"path": "/api/characters/{id}", "method": "GET", "purpose": "get_character"},
            {"path": "/api/characters/{id}/distillations", "method": "GET", "purpose": "list_distillations"},
            {"path": "/api/characters/{id}/distill", "method": "POST", "purpose": "start_distillation"},
            {"path": "/api/characters/{id}/materials", "method": "POST", "purpose": "add_material"},
        ],
    }
