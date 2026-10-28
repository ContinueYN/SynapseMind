"""FastAPI entry point. Business logic lives in ``application`` and ``domain``."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from synapse.api.deps import build_container
from synapse.api.routes import router


def _web_origins() -> list[str]:
    raw = os.getenv(
        "SYNAPSE_WEB_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="SynapseMind API",
        version="0.1.0",
        description="单题诊断引导：状态机、探针、卡点卡。学习模式不返回答案。",
    )
    app.state.container = build_container()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_web_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
