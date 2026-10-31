"""FastAPI entry point. Business logic lives in ``application`` and ``domain``."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from synapse.api.deps import Container, build_container
from synapse.api.routes import router
from synapse.infrastructure.snapshots import SnapshotError
from synapse.infrastructure.sqlite_state import StateSchemaError


def _web_origins() -> list[str]:
    raw = os.getenv(
        "SYNAPSE_WEB_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(
        title="SynapseMind API",
        version="0.1.0",
        description="单题诊断引导：状态机、探针、卡点卡。学习模式不返回答案。",
    )
    # The composition root is injectable so tests can swap one adapter (a fake
    # graph generator, a stub LLM client) without patching globals.
    app.state.container = container or build_container()

    @app.exception_handler(SnapshotError)
    async def snapshot_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        # A legacy or corrupt snapshot is an operator problem, not a 404. The
        # message carries the explicit migration command instead of letting
        # Starlette answer with a bare "Internal Server Error".
        return JSONResponse(
            status_code=500,
            content={"detail": f"会话快照无法读取：{exc}"},
        )

    @app.exception_handler(StateSchemaError)
    async def schema_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": f"会话存储结构不兼容：{exc}"},
        )

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
