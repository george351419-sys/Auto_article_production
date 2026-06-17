"""Configuration routes — LLM backends and system settings."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import load_config, save_config
from core.llm.base import AbstractLLMBackend
from core.llm.registry import BACKEND_TYPES, VENDOR_PRESETS, create_backend
from server.dependencies import get_llm_backend, list_available_backends, reset_llm_cache

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_config():
    return load_config()


@router.put("")
async def update_config(body: dict):
    save_config(body)
    reset_llm_cache()
    return load_config()


@router.get("/llm/backends")
async def list_llm_backends():
    """List configured LLM backends (masked API keys). Merges shared config
    (.env + shared_config.json) with the legacy data/config.json."""
    backends = list_available_backends()
    masked = []
    for b in backends:
        b_copy = dict(b)
        if "api_key" in b_copy and b_copy["api_key"]:
            key = b_copy["api_key"]
            b_copy["api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
        masked.append(b_copy)
    return masked


@router.post("/llm/test")
async def test_llm_backend(body: dict):
    """Test an LLM backend connection."""
    try:
        backend = create_backend(body)
        ok = await backend.test_connection()
        return {"ok": ok, "backend_type": backend.backend_type}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/llm/types")
async def list_backend_types():
    return BACKEND_TYPES


@router.get("/llm/vendors")
async def list_vendor_presets():
    """List vendor presets for one-click setup of Chinese LLM providers."""
    return VENDOR_PRESETS
