"""FastAPI entry point. Business logic lives in ``application`` and ``domain``."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from synapse.api.auth import router as auth_router
from synapse.api.auth import session_auth_middleware
from synapse.api.deps import Container, build_container
from synapse.api.routes import router
from synapse.api.settings import router as settings_router
from synapse.application.auth import AuthStoreUnavailable
from synapse.application.credentials import (
    CredentialDecryptionError,
    CredentialMissing,
    CredentialStoreDisabled,
    CredentialStoreUnavailable,
    CredentialValidationError,
)
from synapse.infrastructure.snapshots import SnapshotError
from synapse.infrastructure.sqlite_state import StateSchemaError


def _web_origins() -> list[str]:
    raw = os.getenv(
        "SYNAPSE_WEB_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app(container: Container | None = None) -> FastAPI:
    # The composition root is injectable so tests can swap one adapter (a fake
    # graph generator, a stub LLM client) without patching globals.
    resolved = container or build_container()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Release the auth engine/Redis connection. A test that never enters
            # the lifespan can call ``container.auth_dispose`` directly.
            if resolved.auth_dispose is not None:
                resolved.auth_dispose()

    app = FastAPI(
        title="SynapseMind API",
        version="0.1.0",
        description="单题诊断引导：状态机、探针、卡点卡。学习模式不返回答案。",
        lifespan=lifespan,
    )
    app.state.container = resolved

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

    @app.exception_handler(AuthStoreUnavailable)
    async def auth_store_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        # A missing migration or an unreachable database/Redis is an operator
        # problem. It must not look like "wrong password" or a silent logout.
        return JSONResponse(
            status_code=503,
            content={"detail": f"账号服务暂不可用：{exc}"},
        )

    @app.exception_handler(CredentialValidationError)
    @app.exception_handler(CredentialMissing)
    async def credential_invalid_handler(_request: Request, exc: Exception) -> JSONResponse:
        # Input the settings form can fix; the message never echoes the key.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(CredentialStoreDisabled)
    @app.exception_handler(CredentialDecryptionError)
    @app.exception_handler(CredentialStoreUnavailable)
    async def credential_store_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        # No master key, a wrong master key or a missing migration is an
        # operator problem: 503 with the actionable sentence, never a 500.
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # The session middleware must run inside CORS so a 401 still carries the
    # CORS headers a browser needs to read it. Starlette inserts each middleware
    # at the front, so the one added last is the outermost.
    @app.middleware("http")
    async def _session_auth(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await session_auth_middleware(request, call_next, resolved)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_web_origins(),
        # The browser always sends the same cookie jar (``credentials: include``)
        # so a session created while auth is on survives; with auth off the
        # cookie is simply absent. The origin list above is explicit, never "*",
        # which is what makes credentialed CORS safe here.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(settings_router)
    return app


app = create_app()
