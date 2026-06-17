"""Lightweight shape validator for the writing module's final_package.

Goal: when writing returns something malformed (truncated LLM output,
schema drift, etc.), the article should fail in `drafted` with a
**readable** error message instead of crashing deep inside the publish
step where the user sees a generic "all platforms failed".

We deliberately do NOT use pydantic here — the writing module is JS/TS
and its output schema evolves; we want validation that's tolerant of
extra fields and clear about what's missing.

`validate_final_package(pkg)` returns a list of issues (empty = OK).
"""
from __future__ import annotations

from typing import Any

# Platforms the orchestrator can actually publish to. Anything else in
# the final_package is ignored (not flagged as an error).
_ORCH_PLATFORMS: frozenset[str] = frozenset({"wechat", "xiaohongshu", "toutiao"})


def validate_final_package(pkg: Any) -> list[str]:
    """Return a list of human-readable issues with the final_package dict.

    Empty list = good enough to attempt publishing. Issues are scoped
    to *blockers* (no title, no body) — soft-missing fields like tags
    or summary are not flagged because the readiness check inside
    Autopublish handles those per-platform.
    """
    issues: list[str] = []

    if not isinstance(pkg, dict):
        return [f"final_package: expected dict, got {type(pkg).__name__}"]

    platforms = pkg.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        return ["final_package.platforms: missing or empty"]

    seen_platforms: set[str] = set()
    for idx, pp in enumerate(platforms):
        path = f"platforms[{idx}]"
        if not isinstance(pp, dict):
            issues.append(f"{path}: expected dict, got {type(pp).__name__}")
            continue

        platform = pp.get("platform", "")
        if not platform:
            issues.append(f"{path}.platform: missing")
            continue
        path = f"platforms[{platform}]"

        # Per-platform required content. titles can be a non-empty list
        # OR a single string (some writing output forms use one or the
        # other — be tolerant).
        titles = pp.get("titles")
        if isinstance(titles, str):
            has_title = bool(titles.strip())
        elif isinstance(titles, list):
            has_title = any(isinstance(t, str) and t.strip() for t in titles)
        else:
            has_title = False
        if not has_title:
            issues.append(f"{path}: no usable title")

        body = pp.get("formattedArticle") or pp.get("formatted_article") or ""
        if not isinstance(body, str) or not body.strip():
            issues.append(f"{path}: empty body (formattedArticle)")

        seen_platforms.add(platform)

    if not (seen_platforms & _ORCH_PLATFORMS):
        issues.append(
            "final_package: none of the platforms match "
            f"{sorted(_ORCH_PLATFORMS)} — got {sorted(seen_platforms)}"
        )

    return issues
