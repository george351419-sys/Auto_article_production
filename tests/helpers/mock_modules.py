"""Mock FastAPI/HTTP servers for 5 business modules.

Per DEV_PLAN §5.3: all tests use mock servers — no real network, no real LLM.
Each mock app includes /health and /contract endpoints inline (self-contained).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, FastAPI

# ── Inline contract routers (self-contained, no imports from module dirs) ───


def _add_contract_routes(app: FastAPI, module: str, version: str, endpoints: list[dict]) -> None:
    """Add /health and /contract to a FastAPI app."""
    start_time = time.time()

    router = APIRouter(tags=["contract"])

    @router.get("/health")
    async def health():
        return {
            "ok": True,
            "module": module,
            "version": version,
            "uptime_seconds": int(time.time() - start_time),
            "deps_ok": True,
        }

    @router.get("/contract")
    async def contract():
        return {
            "module": module,
            "contract_version": "1.0",
            "endpoints": endpoints,
        }

    app.include_router(router)


# ── Mock app factories ───────────────────────────────────────


def make_mock_distilled_app() -> FastAPI:
    app = FastAPI()
    _add_contract_routes(app, "distilled_characters", "1.0.0", [
        {"path": "/api/characters", "method": "GET", "purpose": "list_characters"},
        {"path": "/api/match", "method": "POST", "purpose": "match_character"},
    ])

    @app.get("/api/characters")
    async def list_characters():
        return {"characters": [{"id": "c1", "name": "测试人物", "status": "completed"}]}

    @app.post("/api/match")
    async def match(body: dict):
        return {
            "matched": {
                "character_id": "c1",
                "character_name": "测试人物",
                "voice_summary": "测试语态摘要",
                "match_score": 87,
            },
            "alternatives": [],
        }

    return app


def make_mock_select_app() -> FastAPI:
    app = FastAPI()
    _add_contract_routes(app, "select_topic", "1.0.0", [
        {"path": "/api/collect/trigger", "method": "POST", "purpose": "trigger_collection"},
        {"path": "/api/topics", "method": "GET", "purpose": "list_topics"},
        {"path": "/api/topics", "method": "POST", "purpose": "create_topic"},
        {"path": "/api/topics/{id}", "method": "GET", "purpose": "get_topic"},
    ])

    @app.post("/api/collect/trigger")
    async def trigger_collect():
        return {"collect_id": "mock-collect-1", "estimated_seconds": 10}

    @app.get("/api/topics")
    async def list_topics(status: str = "", limit: int = 30):
        return {"topics": [{"id": "t1", "title": "测试选题", "status": status or "ready"}]}

    @app.post("/api/topics")
    async def create_topic(body: dict):
        return {"id": "t2", "created_at": "2026-06-16T12:00:00Z"}

    @app.get("/api/topics/{topic_id}")
    async def get_topic(topic_id: str):
        return {"id": topic_id, "title": "测试选题", "status": "ready"}

    return app


def make_mock_writing_app() -> FastAPI:
    app = FastAPI()
    _add_contract_routes(app, "writing", "2.0.1", [
        {"path": "/api/tasks", "method": "POST", "purpose": "create_task"},
        {"path": "/api/tasks/{id}/run", "method": "POST", "purpose": "run_task"},
        {"path": "/api/tasks/{id}", "method": "GET", "purpose": "get_task"},
        {"path": "/api/tasks", "method": "GET", "purpose": "list_tasks"},
    ])

    @app.get("/api/tasks")
    async def list_tasks():
        return {"tasks": []}

    @app.post("/api/tasks")
    async def create_task(body: dict):
        return {"task": {"task_id": "wt-1", "status": "draft", "estimated_seconds": 600}}

    @app.post("/api/tasks/{task_id}/run")
    async def run_task(task_id: str):
        return {"task": {"task_id": task_id, "status": "running"}}

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        return {
            "task": {
                "task_id": task_id,
                "status": "completed",
                "final_package": {
                    "platforms": [{
                        "platform": "wechat",
                        "titles": ["测试标题"],
                        "formatted_article": "# 测试正文",
                        "summary": "摘要",
                        "keywords": ["AI"],
                        "tags": ["科技"],
                        "images": [{"id": "img1", "url": "https://oss.example.com/img.png", "kind": "cover"}],
                    }],
                },
            }
        }

    return app


def make_mock_scorer_app() -> FastAPI:
    app = FastAPI()
    _add_contract_routes(app, "platform_scorer", "1.0.0", [
        {"path": "/api/score", "method": "POST", "purpose": "score_article"},
    ])

    @app.post("/api/score")
    async def score(body: dict):
        return {
            "scores": {
                "wechat": {"score": 80, "reason": "深度长文契合公众号"},
                "xiaohongshu": {"score": 70, "reason": "内容质量可"},
                "toutiao": {"score": 60, "reason": "时效性强"},
            },
            "generated_at": "2026-06-16T12:00:00Z",
            "model": "mock",
        }

    return app


def make_mock_autopublish_app() -> FastAPI:
    app = FastAPI()
    _add_contract_routes(app, "autopublish", "3.0.5", [
        {"path": "/api/publish", "method": "POST", "purpose": "execute_publish"},
        {"path": "/api/publish/{plan_id}", "method": "GET", "purpose": "get_publish_status"},
    ])

    @app.post("/api/publish")
    async def publish(body: dict):
        return {
            "plan_id": "pub-1",
            "status": "success",
            "platform_url": "https://example.com/article",
            "platform_msg_id": "msg-1",
            "duration_ms": 5000,
        }

    @app.get("/api/publish/{plan_id}")
    async def get_publish(plan_id: str):
        return {"plan_id": plan_id, "status": "success"}

    return app
