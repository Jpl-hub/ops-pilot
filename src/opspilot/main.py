from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from opspilot.api.routes import router
from opspilot.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", description="新能源企业运营分析与决策支持系统 P0 演示版")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
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
