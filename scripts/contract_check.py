"""Contract smoke test script per DEV_PLAN M1.

Starts 6 modules (or connects to running ones), hits /health and /contract
on each, tests key happy-path endpoints, and reports deviations from LLD §3.

Usage:
  python3 scripts/contract_check.py [--base-dir /path/to/project]

The script can either:
  - Connect to already-running modules (default)
  - Or be run after manually starting all modules
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SERVICES = {
    "orchestrator":         "http://127.0.0.1:8800",
    "distilled_characters": "http://127.0.0.1:8767",
    "select_topic":         "http://127.0.0.1:8766",
    "writing":              "http://127.0.0.1:8788",
    "platform_scorer":      "http://127.0.0.1:8789",
    "autopublish":          "http://127.0.0.1:8765",
}

# Expected contracts per LLD §3
EXPECTED_ENDPOINTS: dict[str, set[str]] = {
    "distilled_characters": {
        "GET /api/characters",
        "POST /api/match",
        "GET /health",
        "GET /contract",
    },
    "select_topic": {
        "POST /api/collect/trigger",
        "GET /api/topics",
        "POST /api/topics",
        "GET /api/topics/{id}",
        "POST /api/topics/{id}/match",
        "POST /api/topics/{id}/review",
        "GET /health",
        "GET /contract",
    },
    "writing": {
        "POST /api/tasks",
        "POST /api/tasks/{id}/run",
        "GET /api/tasks/{id}",
        "GET /api/tasks",
        "GET /health",
        "GET /contract",
    },
    "platform_scorer": {
        "POST /api/score",
        "GET /health",
        "GET /contract",
    },
    "autopublish": {
        "POST /api/publish",
        "GET /api/publish/{plan_id}",
        "GET /health",
        "GET /contract",
    },
}

ERROR = "\033[91m"
OK = "\033[92m"
WARN = "\033[93m"
RESET = "\033[0m"


def _check_mark(passed: bool) -> str:
    return f"{OK}PASS{RESET}" if passed else f"{ERROR}FAIL{RESET}"


async def check_health(name: str, url: str) -> dict[str, Any]:
    """Check /health endpoint returns valid response."""
    result = {"module": name, "health": False, "version": None, "uptime": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{url}/health")
            data = r.json()
            result["health"] = data.get("ok", False) or r.status_code == 200
            result["version"] = data.get("version", "?")
            result["uptime"] = data.get("uptime_seconds")
    except Exception as e:
        result["error"] = str(e)
    return result


async def check_contract(name: str, url: str) -> dict[str, Any]:
    """Check /contract returns expected endpoint manifest."""
    result = {"module": name, "contract": False, "endpoints": [], "missing": [], "extra": [], "error": None}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{url}/contract")
            data = r.json()
            result["contract"] = r.status_code == 200

            actual = set()
            for ep in data.get("endpoints", []):
                actual.add(f"{ep['method']} {ep['path']}")

            result["endpoints"] = sorted(actual)
            expected = EXPECTED_ENDPOINTS.get(name, set())
            result["missing"] = sorted(expected - actual)
            result["extra"] = sorted(actual - expected)
    except Exception as e:
        result["error"] = str(e)
    return result


async def check_happy_paths() -> dict[str, Any]:
    """Test key happy-path endpoints with small data."""
    results: dict[str, Any] = {}

    # Platform scorer: POST /api/score with mock data
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{SERVICES['platform_scorer']}/api/score",
                json={
                    "article_id": "test-contract-check",
                    "topic_brief": "测试选题",
                    "platforms": ["wechat", "xiaohongshu", "toutiao"],
                    "package_summary": {"platforms": []},
                },
            )
            data = r.json()
            scores = data.get("scores", {})
            results["platform_scorer"] = {
                "ok": r.status_code == 200 and all(
                    p in scores for p in ["wechat", "xiaohongshu", "toutiao"]
                ),
                "status": r.status_code,
                "scores": {k: v.get("score") for k, v in scores.items()},
            }
    except Exception as e:
        results["platform_scorer"] = {"ok": False, "error": str(e)}

    return results


async def main() -> int:
    print("=" * 60)
    print("  Contract Smoke Test (DEV_PLAN M1)")
    print("=" * 60)
    print()

    failures = 0
    health_results = []
    contract_results = []

    # Phase 1: Health checks
    print("── Phase 1: Health checks ──")
    tasks = [check_health(name, url) for name, url in SERVICES.items()]
    health_results = await asyncio.gather(*tasks)

    for r in health_results:
        mark = _check_mark(r["health"])
        ver = r.get("version", "?")
        uptime = r.get("uptime", "?")
        err = r.get("error", "")
        status = f"{mark} {r['module']:25s}  v{ver:8s}  uptime={uptime}s"
        if err:
            status += f"  ({err})"
        print(f"  {status}")
        if not r["health"]:
            failures += 1

    print()

    # Phase 2: Contract checks
    print("── Phase 2: Contract manifests ──")
    contracts_tasks = [check_contract(name, url) for name, url in SERVICES.items()
                       if name != "orchestrator"]  # orchestrator has no adapter yet
    contract_results = await asyncio.gather(*contracts_tasks)

    for r in contract_results:
        mark = _check_mark(r["contract"])
        missing = r.get("missing", [])
        extra = r.get("extra", [])
        err = r.get("error", "")

        print(f"  {mark} {r['module']:25s}  endpoints={len(r['endpoints'])}")
        if missing:
            print(f"         {WARN}missing:{RESET} {missing}")
        if extra:
            print(f"         {WARN}extra:{RESET} {extra}")
        if err:
            print(f"         {ERROR}error:{RESET} {err}")
            failures += 1
        if missing:
            failures += 1

    print()

    # Phase 3: Happy path smoke
    print("── Phase 3: Happy path smoke ──")
    hp_results = await check_happy_paths()
    for name, r in hp_results.items():
        mark = _check_mark(r["ok"])
        if "error" in r:
            print(f"  {mark} {name}: {r['error']}")
            failures += 1
        else:
            print(f"  {mark} {name}: {r}")
            if not r["ok"]:
                failures += 1

    print()
    print("=" * 60)
    if failures == 0:
        print(f"  {OK}All checks passed!{RESET}")
    else:
        print(f"  {ERROR}{failures} check(s) failed{RESET}")
    print("=" * 60)

    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
