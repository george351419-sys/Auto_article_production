"""Distillation pipeline execution routes."""
from __future__ import annotations

import asyncio
import json
import logging
import traceback

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core.pipeline.orchestrator import PipelineOrchestrator
from core.utils.markdown_export import render_distillation_markdown
from server.dependencies import (
    get_character_repo,
    get_distillation_repo,
    get_llm_backend,
    get_material_repo,
)

logger = logging.getLogger("distillation")

router = APIRouter(tags=["distillations"])


class DistillationStartResponse(BaseModel):
    distillation_id: str
    status: str


class DistillationStatusUpdate(BaseModel):
    status: str  # "completed" | "failed" | "expired"


# ── WebSocket connections tracking ─────────────────────────────────

_active_ws: dict[str, list[WebSocket]] = {}
_running_tasks: dict[str, asyncio.Task] = {}


# ── Startup recovery: clean up orphaned in_progress records ───────

async def recover_orphaned_tasks():
    """On server startup, reset any distillation/character records left
    in a running state by a previous crash or restart."""
    dist_repo = get_distillation_repo()
    char_repo = get_character_repo()

    all_records = await dist_repo.list_all()
    orphaned = [r for r in all_records if r.get("status") == "in_progress"]

    if not orphaned:
        return

    logger.warning(
        "Found %d orphaned in_progress distillation(s) — recovering",
        len(orphaned),
    )

    for record in orphaned:
        dist_id = record.get("id", "?")
        char_id = record.get("character_id", "")
        try:
            await dist_repo.update(dist_id, {
                "status": "failed",
                "error_message": "服务器重启，任务中断",
            })
            if char_id:
                char = await char_repo.get(char_id)
                if char and char.get("status") == "distilling":
                    await char_repo.update(char_id, {"status": "materials_ready"})
            logger.info("Recovered orphaned distillation %s (character %s)", dist_id, char_id)
        except Exception:
            logger.exception("Failed to recover orphaned distillation %s", dist_id)


async def _broadcast_progress(distillation_id: str, step_name: str, status: str, progress: float):
    ws_list = _active_ws.get(distillation_id, [])
    dead = []
    for ws in ws_list:
        try:
            await ws.send_json({
                "step_name": step_name,
                "status": status,
                "progress": progress,
            })
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_list.remove(ws)


# ── Endpoints ──────────────────────────────────────────────────────

@router.post("/characters/{character_id}/distill")
async def start_distillation(character_id: str):
    char_repo = get_character_repo()
    char = await char_repo.get(character_id)
    if not char:
        raise HTTPException(404, "Character not found")

    mat_repo = get_material_repo()
    materials = await mat_repo.list_for_character(character_id)

    # Only use S/A grade materials if classified, else all
    s_a_materials = [m for m in materials if m.get("confidence") in ("S", "A")]
    if not s_a_materials:
        s_a_materials = materials

    if not s_a_materials:
        raise HTTPException(400, "No materials available for distillation. Add materials first.")

    llm = get_llm_backend()
    if llm is None:
        raise HTTPException(400, "No LLM backend configured. Set up a backend in settings.")

    # Create distillation record
    dist_repo = get_distillation_repo()
    dist_record = await dist_repo.create({
        "character_id": character_id,
        "status": "in_progress",
        "source_material_ids": [m["id"] for m in s_a_materials],
    })

    # Update character status
    await char_repo.update(character_id, {"status": "distilling"})

    # Run pipeline in background
    async def _run():
        try:
            orch = PipelineOrchestrator(llm)
            orch.on_progress(
                lambda sn, st, pr: asyncio.create_task(
                    _broadcast_progress(dist_record["id"], sn, st, pr)
                )
            )
            result = await orch.run_full(char["name"], s_a_materials)
            current = await dist_repo.get(dist_record["id"])
            if current and current.get("status") == "cancelled":
                return
            await dist_repo.update(dist_record["id"], {
                "status": "completed",
                "layers": result.get("layers", {}),
                "verification": result.get("verification", {}),
                "step_results": result.get("step_results", {}),
                "completed_at": result.get("completed_at"),
            })
            await char_repo.update(character_id, {"status": "completed"})
            logger.info("Distillation %s completed for character %s", dist_record["id"], char["name"])
        except asyncio.CancelledError:
            # Cancelled by user — reset character status so it's distillable again
            logger.info("Distillation %s cancelled by user", dist_record["id"])
            try:
                await dist_repo.update(dist_record["id"], {
                    "status": "failed",
                    "error_message": "用户取消",
                })
                await char_repo.update(character_id, {"status": "materials_ready"})
            except Exception:
                logger.exception("Failed to update status after cancellation")
            raise
        except Exception:
            logger.exception("Distillation %s failed", dist_record["id"])
            current = await dist_repo.get(dist_record["id"])
            if current and current.get("status") == "cancelled":
                return
            await dist_repo.update(dist_record["id"], {
                "status": "failed",
                "error_message": traceback.format_exc(),
            })
            await char_repo.update(character_id, {"status": "failed"})
        finally:
            _running_tasks.pop(dist_record["id"], None)

    task = asyncio.create_task(_run())
    _running_tasks[dist_record["id"]] = task

    return {
        "distillation_id": dist_record["id"],
        "status": "in_progress",
    }


@router.get("/characters/{character_id}/distillations")
async def list_distillations(character_id: str):
    dist_repo = get_distillation_repo()
    return await dist_repo.list_for_character(character_id)


@router.get("/distillations/{distillation_id}")
async def get_distillation(distillation_id: str):
    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")
    return record


@router.get("/distillations/{distillation_id}/layer/{layer_name}")
async def get_distillation_layer(distillation_id: str, layer_name: str):
    valid_layers = ["expression_dna", "thinking_tools", "decision_rules", "worldview", "boundaries_evolution", "suggested_topics"]
    if layer_name not in valid_layers:
        raise HTTPException(400, f"Invalid layer name. Must be one of: {valid_layers}")

    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")

    layers = record.get("layers", {})
    return layers.get(layer_name, {})


@router.get("/distillations/{distillation_id}/export/json")
async def export_distillation_json(distillation_id: str):
    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")
    return record


@router.get("/distillations/{distillation_id}/export/markdown", response_class=PlainTextResponse)
async def export_distillation_markdown(distillation_id: str):
    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")
    char_repo = get_character_repo()
    char = await char_repo.get(record.get("character_id", ""))
    name = (char or {}).get("name", "") if char else ""
    md = render_distillation_markdown(record, character_name=name)
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


@router.delete("/distillations/{distillation_id}")
async def cancel_or_delete_distillation(distillation_id: str):
    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")

    # Cancel running task if present
    task = _running_tasks.pop(distillation_id, None)
    if task and not task.done():
        task.cancel()

    # Reset character status if this was the running distillation
    char_id = record.get("character_id", "")
    if char_id and record.get("status") == "in_progress":
        char_repo = get_character_repo()
        char = await char_repo.get(char_id)
        if char and char.get("status") == "distilling":
            await char_repo.update(char_id, {"status": "materials_ready"})

    # Broadcast cancellation
    await _broadcast_progress(distillation_id, "", "cancelled", 0)

    # Delete the record
    await dist_repo.delete(distillation_id)
    return {"status": "cancelled_and_deleted"}


@router.put("/distillations/{distillation_id}/status")
async def update_distillation_status(distillation_id: str, body: DistillationStatusUpdate):
    """Toggle a completed/failed/expired distillation's status.
    - 'completed' or 'failed' → restores it to active
    - 'expired' → marks it as expired (hidden from results, kept for audit)
    Cannot change status of in_progress distillations.
    """
    valid = {"completed", "failed", "expired"}
    if body.status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid}")

    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")

    if record.get("status") == "in_progress":
        raise HTTPException(400, "Cannot change status of a running distillation. Cancel it first.")

    await dist_repo.update(distillation_id, {"status": body.status})
    return {"status": "updated", "new_status": body.status}


class LayerUpdateRequest(BaseModel):
    layers: dict


@router.put("/distillations/{distillation_id}/layers")
async def update_distillation_layers(distillation_id: str, body: LayerUpdateRequest):
    """Replace all layers of a completed/expired distillation.
    Used for user editing / fine-tuning of distillation results.
    """
    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")

    if record.get("status") not in ("completed", "expired"):
        raise HTTPException(400, "Can only edit layers of completed or expired distillations.")

    await dist_repo.update(distillation_id, {"layers": body.layers})
    updated = await dist_repo.get(distillation_id)
    return updated


@router.patch("/distillations/{distillation_id}/layers/{layer_name}")
async def update_distillation_layer(distillation_id: str, layer_name: str, body: dict):
    """Update a single layer of a distillation result.
    Merges the provided data into the existing layer.
    """
    valid_layers = [
        "expression_dna", "thinking_tools", "decision_rules",
        "worldview", "boundaries_evolution", "suggested_topics"
    ]
    if layer_name not in valid_layers:
        raise HTTPException(400, f"Invalid layer name. Must be one of: {valid_layers}")

    dist_repo = get_distillation_repo()
    record = await dist_repo.get(distillation_id)
    if not record:
        raise HTTPException(404, "Distillation not found")

    if record.get("status") not in ("completed", "expired"):
        raise HTTPException(400, "Can only edit layers of completed or expired distillations.")

    layers = record.get("layers", {})
    layers[layer_name] = body
    await dist_repo.update(distillation_id, {"layers": layers})
    return {"layer_name": layer_name, "data": body, "status": "updated"}


@router.delete("/characters/{character_id}/distillations/expired")
async def cleanup_expired_distillations(character_id: str):
    """Permanently delete all expired distillation records for a character."""
    dist_repo = get_distillation_repo()
    records = await dist_repo.list_for_character(character_id)
    expired = [r for r in records if r.get("status") == "expired"]
    for r in expired:
        await dist_repo.delete(r["id"])
    logger.info("Cleaned up %d expired distillations for character %s", len(expired), character_id)
    return {"deleted": len(expired)}


@router.websocket("/ws/pipeline/{distillation_id}")
async def pipeline_websocket(ws: WebSocket, distillation_id: str):
    await ws.accept()
    _active_ws.setdefault(distillation_id, []).append(ws)
    try:
        while True:
            await ws.receive_text()  # Keep alive
    except WebSocketDisconnect:
        ws_list = _active_ws.get(distillation_id, [])
        if ws in ws_list:
            ws_list.remove(ws)
