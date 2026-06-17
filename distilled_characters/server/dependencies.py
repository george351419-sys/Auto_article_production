"""FastAPI dependency injection — provides storage, repos, and LLM backends."""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from config import load_config
from core.llm.base import AbstractLLMBackend
from core.llm.registry import create_backend
from storage.file_storage import FileStorage
from storage.repository import (
    CharacterRepository,
    DistillationRepository,
    MaterialRepository,
)

logger = logging.getLogger("dependencies")

_storage_instance: FileStorage | None = None
_llm_cache: dict[str, AbstractLLMBackend] = {}

# ── Shared config integration (orchestrator account management) ──
#
# distilled_characters first looks for backends in `shared_config.json` at
# the project root, with secrets interpolated from `.env`. This lets the
# orchestrator's 「账号管理」page be the single source of truth for LLM keys.
# If shared config is missing or has no real keys, we fall back to the
# legacy per-module `data/config.json`.

_SHARED_CONFIG_PATH = Path(__file__).resolve().parents[2] / "shared_config.json"
_DOTENV_PATH = _SHARED_CONFIG_PATH.parent / ".env"


def _load_dotenv() -> None:
    """Best-effort .env loader. Does NOT overwrite existing env vars."""
    if not _DOTENV_PATH.is_file():
        return
    for raw in _DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _interp(text: str) -> str:
    return _ENV_VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), text)


def _backends_from_shared_config() -> list[dict]:
    """Build LLM backend dicts from shared_config.json + .env.

    Returns [] if shared config is missing or no real API keys are present
    so callers can fall through to the legacy data/config.json path.
    """
    if not _SHARED_CONFIG_PATH.is_file():
        return []
    _load_dotenv()
    try:
        raw_text = _SHARED_CONFIG_PATH.read_text(encoding="utf-8")
        raw = json.loads(_interp(raw_text))
    except Exception as e:
        logger.warning("Failed to read shared_config.json: %s", e)
        return []

    llm = raw.get("llm") or {}
    if not isinstance(llm, dict):
        return []

    label_map = {
        "deepseek": "DeepSeek (账号管理)",
        "qwen": "Qwen / DashScope (账号管理)",
    }

    backends: list[dict] = []
    for vendor, cfg in llm.items():
        if not isinstance(cfg, dict):
            continue
        api_key = (cfg.get("api_key") or "").strip()
        if not api_key:
            continue  # Skip vendors with no key configured in .env
        backends.append({
            "name": label_map.get(vendor, vendor),
            "type": "openai_compatible",
            "base_url": cfg.get("base_url", ""),
            "api_key": api_key,
            "model": cfg.get("model", ""),
            "is_default": vendor == "deepseek",
            "_source": "shared_config",
        })
    return backends


def get_storage() -> FileStorage:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = FileStorage(data_root="data")
    return _storage_instance


def get_character_repo() -> CharacterRepository:
    return CharacterRepository(get_storage())


def get_material_repo() -> MaterialRepository:
    return MaterialRepository(get_storage())


def get_distillation_repo() -> DistillationRepository:
    return DistillationRepository(get_storage())


def list_available_backends() -> list[dict]:
    """Return the merged list of backends. Shared config wins; legacy
    per-module config.json fills any gaps."""
    backends = _backends_from_shared_config()
    has_shared = bool(backends)
    seen_names = {b["name"] for b in backends}
    legacy = load_config().get("llm_backends", []) or []
    for b in legacy:
        if b.get("name") in seen_names:
            continue
        entry = dict(b, _source="data/config.json")
        # When shared config provides a default, demote legacy defaults
        if has_shared:
            entry["is_default"] = False
        backends.append(entry)
    return backends


def get_llm_backend(backend_name: str | None = None) -> AbstractLLMBackend | None:
    """Get (cached) LLM backend by name, or the default backend.

    Lookup order:
      1. Shared config (orchestrator 账号管理 → .env + shared_config.json)
      2. Legacy local data/config.json (for backwards compatibility)
    """
    global _llm_cache

    backends = list_available_backends()
    if not backends:
        return None

    target = None
    if backend_name:
        for b in backends:
            if b.get("name") == backend_name:
                target = b
                break
    else:
        target = backends[0]
        for b in backends:
            if b.get("is_default"):
                target = b
                break

    if target is None:
        return None

    cache_key = target.get("name", "default")
    if cache_key not in _llm_cache:
        # Strip our private marker before handing off to create_backend
        clean = {k: v for k, v in target.items() if not k.startswith("_")}
        _llm_cache[cache_key] = create_backend(clean)

    return _llm_cache[cache_key]


def reset_llm_cache() -> None:
    """Clear the LLM backend cache (after config changes)."""
    global _llm_cache
    _llm_cache = {}
