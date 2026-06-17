"""Ad-hoc pipeline step execution — the module reuse API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.pipeline.orchestrator import PipelineOrchestrator, get_step_info
from server.dependencies import get_llm_backend

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class StepRunRequest(BaseModel):
    step_name: str
    context: dict
    backend_name: str | None = None


@router.get("/steps")
async def list_steps():
    return get_step_info()


@router.post("/run")
async def run_step(body: StepRunRequest):
    llm = get_llm_backend(body.backend_name)
    if llm is None:
        raise HTTPException(400, "No LLM backend configured or specified backend not found.")

    orch = PipelineOrchestrator(llm)
    try:
        result = await orch.run_step(body.step_name, body.context)
        return {"step_name": body.step_name, "status": "completed", "result": result}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"Step execution failed: {e}")
