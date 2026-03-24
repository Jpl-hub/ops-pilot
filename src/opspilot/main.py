from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from opspilot.api.routes import get_auth_store, router
from opspilot.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        get_auth_store().initialize()
        yield

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="新能源企业运营分析与决策支持系统 P0 演示版",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    return app


app = create_app()


def run_api() -> None:
    settings = get_settings()
    uvicorn.run("opspilot.main:app", host=settings.host, port=settings.port, reload=False)


def run_ui() -> None:
    from opspilot.web.ui import run_ui_app

    run_ui_app()
