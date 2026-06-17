"""Load and validate `shared_config.json`.

Schema per LLD §8.1. Missing required fields raise ConfigError on load,
so callers get a clear error at startup rather than a KeyError mid-flow.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


# ── .env loader + ${VAR} substitution ────────────────────────
#
# PRD §7.4: API keys / cookies must not live in the JSON config. We let
# shared_config.json reference them as `${DEEPSEEK_API_KEY}` etc; this
# loader fills them in from the process env, optionally pre-populated
# from a project-root `.env` file.

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _load_dotenv_into_env(dotenv_path: Path) -> None:
    """Best-effort .env loader (no python-dotenv dep).

    Lines starting with `#` or empty lines are skipped. Each remaining
    line is parsed as `KEY=VALUE`. Values may be wrapped in matching
    single or double quotes which we strip. Existing env vars are NOT
    overwritten (process env wins).
    """
    if not dotenv_path.is_file():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _substitute_env_vars(text: str) -> str:
    """Replace `${VAR}` / `${VAR:-default}` in `text`.

    Missing-and-no-default: leaves the placeholder literal (so downstream
    validation can still inspect the structure). Callers that need a real
    secret should detect the literal `${...}` and refuse.
    """
    def repl(m: re.Match[str]) -> str:
        var, default = m.group(1), m.group(2)
        env_val = os.environ.get(var)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        return m.group(0)  # leave placeholder
    return _ENV_VAR_RE.sub(repl, text)


def has_unresolved_placeholders(value: str) -> bool:
    """True if `value` still contains an `${...}` placeholder."""
    return bool(_ENV_VAR_RE.search(value or ""))


@dataclass(frozen=True)
class Services:
    orchestrator_url: str
    distilled_characters_url: str
    select_topic_url: str
    writing_url: str
    platform_scorer_url: str
    autopublish_url: str


@dataclass(frozen=True)
class LLMProvider:
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class Publishing:
    account_label: str
    author: str
    location: str
    platforms: list[str]


@dataclass(frozen=True)
class Pipeline:
    auto_scan_cron: str
    review_timeout_hours: int
    boost_check_hour: int
    auto_dispatch_to_writing: bool


@dataclass(frozen=True)
class Cleanup:
    sweep_cron: str
    threshold_gb: float
    guard_check_minutes: int
    vacuum_cron: str


@dataclass(frozen=True)
class Scoring:
    publish_threshold: int
    boost_min_score: int


@dataclass(frozen=True)
class Config:
    version: str
    llm: dict[str, LLMProvider]
    services: Services
    publishing: Publishing
    pipeline: Pipeline
    cleanup: Cleanup
    scoring: Scoring


_REQUIRED_TOP = (
    "version",
    "llm",
    "services",
    "publishing",
    "pipeline",
    "cleanup",
    "scoring",
)
_REQUIRED_SERVICES = (
    "orchestrator_url",
    "distilled_characters_url",
    "select_topic_url",
    "writing_url",
    "platform_scorer_url",
    "autopublish_url",
)
_REQUIRED_PUBLISHING = ("account_label", "author", "location", "platforms")
_REQUIRED_PIPELINE = (
    "auto_scan_cron",
    "review_timeout_hours",
    "boost_check_hour",
    "auto_dispatch_to_writing",
)
_REQUIRED_CLEANUP = (
    "sweep_cron",
    "threshold_gb",
    "guard_check_minutes",
    "vacuum_cron",
)
_REQUIRED_SCORING = ("publish_threshold", "boost_min_score")


def _require_keys(d: dict[str, Any], keys: tuple[str, ...], path: str) -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise ConfigError(f"{path}: missing required keys: {missing}")


def load_raw_config(config_path: str | Path) -> dict[str, Any]:
    """Read the JSON file, do ${VAR} substitution (with .env if present),
    and return the raw dict. Use this when you want the plain dict shape
    (e.g. scheduler_v2 + server_v2 helpers); use load_config() to get the
    validated dataclass.
    """
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    # Look for .env next to the shared_config.json (i.e. project root).
    _load_dotenv_into_env(path.parent / ".env")

    raw_text = path.read_text(encoding="utf-8")
    interpolated = _substitute_env_vars(raw_text)
    try:
        return json.loads(interpolated)
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file is not valid JSON: {e}") from e


def load_config(config_path: str | Path) -> Config:
    return parse_config(load_raw_config(config_path))


def parse_config(raw: dict[str, Any]) -> Config:
    _require_keys(raw, _REQUIRED_TOP, "root")

    llm_raw = raw["llm"]
    if not isinstance(llm_raw, dict) or not llm_raw:
        raise ConfigError("llm: must be a non-empty object")
    llm: dict[str, LLMProvider] = {}
    for name, cfg in llm_raw.items():
        _require_keys(cfg, ("api_key", "base_url", "model"), f"llm.{name}")
        llm[name] = LLMProvider(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            model=cfg["model"],
        )

    svc_raw = raw["services"]
    _require_keys(svc_raw, _REQUIRED_SERVICES, "services")
    services = Services(**{k: svc_raw[k] for k in _REQUIRED_SERVICES})

    pub_raw = raw["publishing"]
    _require_keys(pub_raw, _REQUIRED_PUBLISHING, "publishing")
    if not isinstance(pub_raw["platforms"], list) or not pub_raw["platforms"]:
        raise ConfigError("publishing.platforms: must be a non-empty list")
    publishing = Publishing(
        account_label=pub_raw["account_label"],
        author=pub_raw["author"],
        location=pub_raw["location"],
        platforms=list(pub_raw["platforms"]),
    )

    pl_raw = raw["pipeline"]
    _require_keys(pl_raw, _REQUIRED_PIPELINE, "pipeline")
    pipeline = Pipeline(
        auto_scan_cron=pl_raw["auto_scan_cron"],
        review_timeout_hours=int(pl_raw["review_timeout_hours"]),
        boost_check_hour=int(pl_raw["boost_check_hour"]),
        auto_dispatch_to_writing=bool(pl_raw["auto_dispatch_to_writing"]),
    )

    cl_raw = raw["cleanup"]
    _require_keys(cl_raw, _REQUIRED_CLEANUP, "cleanup")
    cleanup = Cleanup(
        sweep_cron=cl_raw["sweep_cron"],
        threshold_gb=float(cl_raw["threshold_gb"]),
        guard_check_minutes=int(cl_raw["guard_check_minutes"]),
        vacuum_cron=cl_raw["vacuum_cron"],
    )

    sc_raw = raw["scoring"]
    _require_keys(sc_raw, _REQUIRED_SCORING, "scoring")
    scoring = Scoring(
        publish_threshold=int(sc_raw["publish_threshold"]),
        boost_min_score=int(sc_raw["boost_min_score"]),
    )

    return Config(
        version=str(raw["version"]),
        llm=llm,
        services=services,
        publishing=publishing,
        pipeline=pipeline,
        cleanup=cleanup,
        scoring=scoring,
    )
