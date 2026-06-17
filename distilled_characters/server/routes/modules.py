"""Module registry routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.pipeline.orchestrator import PipelineOrchestrator, get_step_info
from server.dependencies import get_llm_backend

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("")
async def list_modules():
    """List all available modules (pipeline steps + plugins)."""
    steps = get_step_info()
    modules = []
    for s in steps:
        modules.append({
            "name": s["name"],
            "type": "pipeline_step",
            "label": s["label"],
            "description": s["description"],
        })
    return modules


@router.get("/{module_name}")
async def get_module(module_name: str):
    """Get module details."""
    for step in get_step_info():
        if step["name"] == module_name:
            return {
                "name": step["name"],
                "type": "pipeline_step",
                "label": step["label"],
                "description": step["description"],
            }
    raise HTTPException(404, f"Module '{module_name}' not found")


@router.post("/{module_name}/run")
async def run_module(module_name: str, context: dict):
    """Execute a module with custom context."""
    llm = get_llm_backend()
    if llm is None:
        raise HTTPException(400, "No LLM backend configured.")

    orch = PipelineOrchestrator(llm)
    try:
        result = await orch.run_step(module_name, context)
        return {"module": module_name, "status": "completed", "result": result}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Module execution failed: {e}")
