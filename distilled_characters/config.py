"""Global configuration management.

Loads from data/config.json. Provides defaults when no config exists.
Includes fallback backends so the system always has a working LLM.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from core.llm.registry import VENDOR_PRESETS

DEFAULT_CONFIG = {
    "llm_backends": [
        {
            "name": "讯飞 Spark",
            "type": "openai_compatible",
            "base_url": "https://spark-api-open.xf-yun.com/v1",
            "api_key": "16122a064d1ce0b8c2bb35ad88bb7eb3:MjVjMmU0ZTY3YzE3ZjliM2M2YjRlN2Zh",
            "model": "4.0Ultra",
            "is_default": True,
        },
    ],
    "search_backend": "multi_channel",
    "search_channels": ["searxng", "open_library", "duckduckgo"],
    "web_search_enabled": False,
    "server_host": "127.0.0.1",
    "server_port": 8765,
}

_config_cache: Optional[dict] = None


def _config_path() -> Path:
    return Path("data") / "config.json"


def load_config() -> dict[str, Any]:
    """Load config, creating default if not exists."""
    global _config_cache
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if not config_path.exists():
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)

    if _config_cache is None:
        with open(config_path, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)

    # Ensure at least one real backend
    real = [b for b in _config_cache.get("llm_backends", []) if b.get("type") != "mock"]
    if not real:
        _config_cache["llm_backends"] = DEFAULT_CONFIG["llm_backends"]
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(_config_cache, f, ensure_ascii=False, indent=2)

    return _config_cache


def save_config(config: dict) -> None:
    """Persist config to disk."""
    global _config_cache
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve at least one real backend
    real = [b for b in config.get("llm_backends", []) if b.get("type") != "mock"]
    if not real:
        config["llm_backends"] = DEFAULT_CONFIG["llm_backends"]

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    _config_cache = config


def get_default_backend() -> dict | None:
    """Get the configured default LLM backend."""
    config = load_config()
    backends = config.get("llm_backends", [])
    for b in backends:
        if b.get("is_default"):
            return b
    # Fallback to first real backend
    for b in backends:
        if b.get("type") != "mock":
            return b
    return backends[0] if backends else None


def reset_config_cache() -> None:
    """Reset cached config (useful for testing)."""
    global _config_cache
    _config_cache = None
