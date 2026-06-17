"""Celebrity data routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.celebrity_loader import get_celebrity_summaries, get_celebrity_by_id, get_celebrity_by_name

router = APIRouter(prefix="/celebrities", tags=["celebrities"])


@router.get("")
async def list_celebrities():
    summaries = get_celebrity_summaries()
    return [s.model_dump() for s in summaries]


@router.get("/{celebrity_id}")
async def get_celebrity(celebrity_id: str):
    celeb = get_celebrity_by_id(celebrity_id)
    if not celeb:
        raise HTTPException(404, "Celebrity not found")
    return celeb.model_dump()
