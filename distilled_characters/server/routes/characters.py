"""Character CRUD routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.models.character import CharacterCreate, CharacterUpdate
from server.dependencies import get_character_repo

logger = logging.getLogger("characters")

router = APIRouter(prefix="/characters", tags=["characters"])


@router.post("")
async def create_character(body: CharacterCreate):
    repo = get_character_repo()
    record = await repo.create(body.model_dump())
    return record


@router.get("")
async def list_characters(q: str = ""):
    repo = get_character_repo()
    records = await repo.list(query=q or None)
    # Attach material count
    from server.dependencies import get_material_repo
    mat_repo = get_material_repo()
    for r in records:
        mats = await mat_repo.list_for_character(r["id"])
        r["material_count"] = len(mats)
    return records


@router.get("/{character_id}")
async def get_character(character_id: str):
    repo = get_character_repo()
    record = await repo.get(character_id)
    if not record:
        raise HTTPException(404, "Character not found")
    return record


@router.put("/{character_id}")
async def update_character(character_id: str, body: CharacterUpdate):
    repo = get_character_repo()
    existing = await repo.get(character_id)
    if not existing:
        raise HTTPException(404, "Character not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return await repo.update(character_id, updates)


@router.delete("/{character_id}")
async def delete_character(character_id: str):
    repo = get_character_repo()
    existing = await repo.get(character_id)
    if not existing:
        raise HTTPException(404, "Character not found")
    # Cancel any running distillation task for this character
    from server.dependencies import get_material_repo, get_distillation_repo
    from server.routes.distillation import _running_tasks, _active_ws
    mat_repo = get_material_repo()
    dist_repo = get_distillation_repo()
    dist_records = await dist_repo.list_for_character(character_id)
    for d in dist_records:
        task = _running_tasks.pop(d["id"], None)
        if task and not task.done():
            task.cancel()
            logger.info("Cancelled running distillation %s for deleted character %s", d["id"], character_id)
        await dist_repo.delete(d["id"])
    for m in await mat_repo.list_for_character(character_id):
        await mat_repo.delete(m["id"])
    await repo.delete(character_id)
    return {"deleted": True}
