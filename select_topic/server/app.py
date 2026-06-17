"""FastAPI application factory."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.database import init_db
from server.scheduler import CollectionScheduler

logger = logging.getLogger("app")

_scheduler: CollectionScheduler | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="名人热点智能匹配选题系统", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def on_startup():
        logger.info("Initializing database...")
        await init_db()
        global _scheduler
        _scheduler = CollectionScheduler()
        # Inject scheduler into collect routes (avoids circular import)
        from server.routes import collect
        collect.set_scheduler(_scheduler)
        await _scheduler.start()
        logger.info("Server ready")

    @app.on_event("shutdown")
    async def on_shutdown():
        global _scheduler
        if _scheduler:
            await _scheduler.stop()

    # API routes
    from adapters.contract import router as contract_router
    from server.routes import topics, scoring, matching, review, config, pipeline, celebrities, collect
    app.include_router(topics.router, prefix="/api")
    app.include_router(scoring.router, prefix="/api")
    app.include_router(matching.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(pipeline.router, prefix="/api")
    app.include_router(celebrities.router, prefix="/api")
    app.include_router(collect.router, prefix="/api")
    app.include_router(contract_router)

    # Static files (serve frontend)
    static_dir = Path(__file__).parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
