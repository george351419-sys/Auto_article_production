"""FastAPI application factory."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.dependencies import (
    get_character_repo,
    get_distillation_repo,
    get_material_repo,
    get_storage,
)
from adapters.contract import router as contract_router
from server.routes import (
    characters,
    config as config_routes,
    distillation,
    materials,
    modules,
    pipeline,
    search,
)

logger = logging.getLogger("app")


def create_app() -> FastAPI:
    app = FastAPI(title="蒸笼阁 · 人物思维蒸馏工坊", version="1.0.0")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Startup — recover orphaned tasks from previous crash/restart
    @app.on_event("startup")
    async def on_startup():
        logger.info("Server starting — recovering orphaned tasks")
        await distillation.recover_orphaned_tasks()

    # API routes
    app.include_router(characters.router, prefix="/api")
    app.include_router(materials.router, prefix="/api")
    app.include_router(distillation.router, prefix="/api")
    app.include_router(pipeline.router, prefix="/api")
    app.include_router(modules.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(config_routes.router, prefix="/api")
    app.include_router(contract_router)

    # Static files
    static_dir = Path(__file__).parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
