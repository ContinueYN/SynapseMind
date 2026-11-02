"""Account endpoints and the diagnostic-session auth gate.

Scope is deliberately narrow: one owner account on a self-hosted deployment, no
roles and no tenants. The endpoints are:

``POST /api/v1/auth/register``  201 + HttpOnly cookie (first owner only by default)
``POST /api/v1/auth/login``     200 + HttpOnly cookie
``POST /api/v1/auth/logout``    200, revokes the server-side session
``GET  /api/v1/auth/me``        200 with the public account view, else 401

The cookie is ``synapse_session``: HttpOnly, SameSite=Lax, path=/, Secure only
when ``SYNAPSE_COOKIE_SECURE=on``, max-age = ``SYNAPSE_AUTH_SESSION_TTL_S``.

With ``SYNAPSE_AUTH=off`` the account endpoints answer 403 (``logout`` still
clears a stale cookie), and ``require_authenticated`` is a no-op so the existing
local single-user flow is unchanged.
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status

from synapse.api.deps import Container
from synapse.api.mappers import auth_user_out
from synapse.api.schemas import AuthUserOut, LoginRequest, LogoutOut, RegisterRequest
from synapse.application.auth import (
    AuthService,
    AuthUser,
    EmailAlreadyRegistered,
    InvalidCredentials,
    IssuedSession,
    RegistrationClosed,
)
from synapse.infrastructure.auth.settings import COOKIE_NAME

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_LOGIN_REQUIRED = "需要先登录。"
_AUTH_DISABLED = "认证未启用；设置 SYNAPSE_AUTH=on 后才能使用账号接口。"


def _container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


def _enabled_service(request: Request) -> AuthService:
    service = _container(request).auth
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_AUTH_DISABLED,
        )
    return service


def _set_cookie(response: Response, container: Container, issued: IssuedSession) -> None:
    settings = container.auth_settings
    response.set_cookie(
        key=COOKIE_NAME,
        value=issued.token,
        max_age=settings.session_ttl_s,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _delete_cookie(response: Response, container: Container) -> None:
    settings = container.auth_settings
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.post(
    "/register",
    response_model=AuthUserOut,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest, request: Request, response: Response) -> AuthUserOut:
    """Create the first owner account and sign it in.

    A deployment that already has an owner answers 409 unless the operator set
    ``SYNAPSE_AUTH_ALLOW_SIGNUP=on``. The same 409 covers a duplicate email, so
    the endpoint does not tell a caller whether a different account exists.
    """

    service = _enabled_service(request)
    try:
        issued = service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except (RegistrationClosed, EmailAlreadyRegistered) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    _set_cookie(response, _container(request), issued)
    return auth_user_out(issued.user)


@router.post("/login", response_model=AuthUserOut)
def login(payload: LoginRequest, request: Request, response: Response) -> AuthUserOut:
    """Exchange email/password for a new server-side session.

    A wrong password, an unknown email and a closed shop all answer 401 with the
    same message; the password check runs the KDF even for an unknown email so
    timing does not become an account oracle.
    """

    service = _enabled_service(request)
    try:
        issued = service.login(email=payload.email, password=payload.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Cookie"},
        ) from exc
    _set_cookie(response, _container(request), issued)
    return auth_user_out(issued.user)


@router.post("/logout", response_model=LogoutOut)
def logout(request: Request, response: Response) -> LogoutOut:
    """Revoke the current session server-side and clear the cookie.

    Idempotent: calling it without a cookie succeeds. It also works when auth is
    off, so a client that was pointed at a gated server can clean up its jar.
    """

    container = _container(request)
    if container.auth is not None:
        container.auth.logout(request.cookies.get(COOKIE_NAME))
    _delete_cookie(response, container)
    return LogoutOut()


@router.get("/me", response_model=AuthUserOut)
def me(request: Request) -> AuthUserOut:
    """The account behind the cookie, or 401 for missing/expired/revoked."""

    service = _enabled_service(request)
    principal = service.principal(request.cookies.get(COOKIE_NAME))
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_LOGIN_REQUIRED,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return auth_user_out(principal)


def require_authenticated(request: Request) -> AuthUser | None:
    """Gate for the diagnostic session routes.

    Off means "no gate at all": the dependency returns immediately, which is why
    every existing unauthenticated test and local workflow keeps working. On
    means a missing, unknown, revoked or expired cookie is a 401 before the route
    body runs.

    Health, ``/auth/*``, docs/openapi, executions, knowledge search and the
    local review queue stay public on purpose; only ``/api/v1/sessions...`` is
    gated in this slice.
    """

    container = _container(request)
    if not container.auth_settings.enabled:
        return None
    service = container.auth
    if service is None:  # pragma: no cover - composition always builds both
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证已启用但账号服务未初始化。",
        )
    principal = service.principal(request.cookies.get(COOKIE_NAME))
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_LOGIN_REQUIRED,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return principal
