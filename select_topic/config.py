"""Global configuration for the topic selection system."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "server_host": "127.0.0.1",
    "server_port": 8766,
    "celebrity_data_dir": "../distilled_characters/data",
    "db_path": "data/select_topic.db",
    "default_positioning": "business_tech",
    "llm_backend": {
        "name": "deepseek",
        "type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-e694f04648ab4091889828442fcd7d98",
        "model": "deepseek-chat",
    },
    "collector": {
        "enabled": True,
        "interval_seconds": 3600,
        "trendradar": {
            "enabled": True,
            "command": ["uv", "run", "main.py"],
            "working_dir": "../TrendRadar",
            "timeout_seconds": 60,
        },
        "direct_scrape": {
            "enabled": True,
        },
        "platforms": ["toutiao", "weibo", "xiaohongshu", "newrank", "tophub"],
        "distillation": {
            "max_items_per_batch": 20,
            "model": "deepseek-chat",
        },
        "dedup": {
            "title_similarity_threshold": 0.70,
            "lookback_hours": 72,
        },
        "auto_score_threshold": 80,
    },
}

_config_cache: dict | None = None


def _deep_merge_defaults(config: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Return config with missing nested default keys filled in."""
    merged = defaults.copy()
    for key, value in config.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    config_path = Path("data") / "config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            _config_cache = _deep_merge_defaults(json.load(f), DEFAULT_CONFIG)
    else:
        Path("data").mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        _config_cache = DEFAULT_CONFIG.copy()
    return _config_cache


def get_llm_config() -> dict:
    return load_config().get("llm_backend", DEFAULT_CONFIG["llm_backend"])
