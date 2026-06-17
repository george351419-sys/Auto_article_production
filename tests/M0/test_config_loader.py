"""M0 · shared_config.json loader 单元测试."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.config_loader import (
    Config,
    ConfigError,
    LLMProvider,
    load_config,
    parse_config,
)

pytestmark = pytest.mark.M0


def _valid_raw() -> dict:
    return {
        "version": "1.0",
        "llm": {
            "deepseek": {
                "api_key": "sk-x",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
            }
        },
        "services": {
            "orchestrator_url": "http://127.0.0.1:8800",
            "distilled_characters_url": "http://127.0.0.1:8767",
            "select_topic_url": "http://127.0.0.1:8766",
            "writing_url": "http://127.0.0.1:8788",
            "platform_scorer_url": "http://127.0.0.1:8789",
            "autopublish_url": "http://127.0.0.1:8765",
        },
        "publishing": {
            "account_label": "main",
            "author": "烽灵",
            "location": "北京",
            "platforms": ["wechat_official", "xiaohongshu", "toutiao"],
        },
        "pipeline": {
            "auto_scan_cron": "0 8 * * *",
            "review_timeout_hours": 2,
            "boost_check_hour": 23,
            "auto_dispatch_to_writing": True,
        },
        "cleanup": {
            "sweep_cron": "0 */3 * * *",
            "threshold_gb": 2.5,
            "guard_check_minutes": 10,
            "vacuum_cron": "0 3 * * 0",
        },
        "scoring": {
            "publish_threshold": 70,
            "boost_min_score": 50,
        },
    }


def test_parse_valid_config_returns_dataclass():
    cfg = parse_config(_valid_raw())
    assert isinstance(cfg, Config)
    assert cfg.version == "1.0"
    assert "deepseek" in cfg.llm
    assert isinstance(cfg.llm["deepseek"], LLMProvider)
    assert cfg.services.orchestrator_url == "http://127.0.0.1:8800"
    assert cfg.publishing.platforms == ["wechat_official", "xiaohongshu", "toutiao"]
    assert cfg.cleanup.threshold_gb == 2.5
    assert cfg.scoring.publish_threshold == 70


def test_load_config_from_file(tmp_path: Path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(_valid_raw()), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.version == "1.0"


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.json")


def test_load_invalid_json_raises(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(p)


def test_missing_top_field_raises():
    raw = _valid_raw()
    del raw["services"]
    with pytest.raises(ConfigError, match=r"root.*services"):
        parse_config(raw)


def test_missing_services_field_raises():
    raw = _valid_raw()
    del raw["services"]["platform_scorer_url"]
    with pytest.raises(ConfigError, match=r"services.*platform_scorer_url"):
        parse_config(raw)


def test_missing_llm_provider_field_raises():
    raw = _valid_raw()
    del raw["llm"]["deepseek"]["api_key"]
    with pytest.raises(ConfigError, match=r"llm.deepseek.*api_key"):
        parse_config(raw)


def test_empty_llm_dict_raises():
    raw = _valid_raw()
    raw["llm"] = {}
    with pytest.raises(ConfigError, match=r"llm.*non-empty"):
        parse_config(raw)


def test_empty_platforms_list_raises():
    raw = _valid_raw()
    raw["publishing"]["platforms"] = []
    with pytest.raises(ConfigError, match=r"platforms.*non-empty"):
        parse_config(raw)


def test_real_shared_config_loads(project_root: Path):
    """The actual shared_config.json must be loadable as-is."""
    cfg = load_config(project_root / "shared_config.json")
    assert cfg.version == "1.0"
    assert cfg.services.platform_scorer_url.endswith(":8789")
    assert cfg.services.distilled_characters_url.endswith(":8767")
    assert cfg.services.autopublish_url.endswith(":8765")
    assert cfg.cleanup.threshold_gb == 2.5
    assert cfg.scoring.publish_threshold == 70
    assert "deepseek" in cfg.llm


def test_dataclass_is_frozen():
    cfg = parse_config(_valid_raw())
    with pytest.raises(Exception):
        cfg.version = "9.9"  # type: ignore[misc]
