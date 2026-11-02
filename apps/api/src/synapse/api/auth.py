"""Account endpoints and the login-ticket exchange.

The cookie is the whole session, and it carries one of two kinds of value:

* a one-time **login ticket** (``L_…``) issued by register/login. The first
  authenticated request consumes it exactly once and the response sets an
  ordinary session cookie (``S_…``) in the same token family;
* an ordinary **session** (``S_…``, or a legacy unprefixed value). It is reused
  on every request until logout, expiry or revocation, and ordinary requests
  never carry ``Set-Cookie``.

Presenting an already-consumed login ticket is the theft signal: the whole
family is revoked, the cookie is cleared and the response is 401 with a detail
containing ``会话被复用``. Replaying an ordinary session is not detectable and
simply keeps authenticating until it is revoked or expires.

Where the exchange happens:

* ``/api/v1/sessions…`` and ``/api/v1/settings…`` — the async
  ``session_auth_middleware``. It must be async because the model runtime reads
  the current user from a ``ContextVar``, and a ``ContextVar`` set inside a sync
  FastAPI dependency is not guaranteed to reach the sync route in another
  worker thread. ``anyio`` copies the async context into the threadpool, so a
  value set before dispatch is visible downstream.
* ``GET /auth/me`` — the endpoint itself, because it is not under a protected
  prefix. ``POST /auth/login|register`` start a new family; ``POST /auth/logout``
  revokes the family and clears the cookie.

Endpoints: ``POST /api/v1/auth/register`` 201 (open only when signup is on),
``POST /api/v1/auth/login`` 200, ``POST /api/v1/auth/logout`` 200,
``GET /api/v1/auth/me`` 200.

The cookie is ``synapse_session``: HttpOnly, SameSite=Lax, path=/, Secure only
when ``SYNAPSE_COOKIE_SECURE=on``, max-age = ``SYNAPSE_AUTH_SESSION_TTL_S``.

With ``SYNAPSE_AUTH=off`` the account endpoints answer 403, ``logout`` still
clears a stale cookie, and ``require_authenticated`` is a no-op so the local
single-user flow is unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from synapse.api.deps import Container
from synapse.api.mappers import auth_user_out
from synapse.api.schemas import AuthUserOut, LoginRequest, LogoutOut, RegisterRequest
from synapse.application.auth import (
    AuthService,
    AuthStoreUnavailable,
    AuthUser,
    EmailAlreadyRegistered,
    InvalidCredentials,
    IssuedSession,
    RegistrationClosed,
    SessionReuseDetected,
)
from synapse.application.context import bind_owner, reset_owner
from synapse.infrastructure.auth.settings import COOKIE_NAME

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_LOGIN_REQUIRED = "需要先登录。"
_AUTH_DISABLED = "认证未启用；设置 SYNAPSE_AUTH=on 后才能使用账号接口。"
_REUSE_DETAIL = "检测到会话被复用，已强制下线，请重新登录。"
_STORE_UNAVAILABLE = "账号服务暂不可用："

# Only these resources exchange the login ticket. Public routes (health, docs,
# knowledge search, executions, the local review queue, the account endpoints)
# must never touch the cookie: a public page load would otherwise burn the
# session the diagnostic page is using.
_PROTECTED_PREFIXES = ("/api/v1/sessions", "/api/v1/settings")


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


def _set_cookie(response: Response, container: Container, token: str) -> None:
    settings = container.auth_settings
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
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


def _clearing_cookie_header(container: Container) -> str:
    """A ``Set-Cookie`` value that clears the cookie, for an HTTPException.

    FastAPI's exception handler builds a fresh response, so headers set on the
    injected ``Response`` would be dropped. Generating the header from a scratch
    ``Response`` keeps path/Secure/SameSite identical to the one we set.
    """

    scratch = Response()
    _delete_cookie(scratch, container)
    return scratch.headers["set-cookie"]


def _unauthorized(container: Container, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={
            "WWW-Authenticate": "Cookie",
            "Set-Cookie": _clearing_cookie_header(container),
        },
    )


def _issued_cookie(response: Response, container: Container, issued: IssuedSession) -> None:
    _set_cookie(response, container, issued.token)


def _is_protected(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _PROTECTED_PREFIXES)


async def session_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    container: Container,
) -> Response:
    """Authenticate the cookie for protected resources, then bind the owner.

    A login ticket is exchanged for an ordinary session and only that exchange
    puts a ``Set-Cookie`` on the response; an ordinary session authenticates in
    place without one. Returns early (without calling the route) for a missing,
    expired, unknown, revoked or replayed ticket.
    """

    if not container.auth_settings.enabled or not _is_protected(request.url.path):
        return await call_next(request)

    service = container.auth
    if service is None:  # pragma: no cover - composition always builds both
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "认证已启用但账号服务未初始化。"},
        )

    token = request.cookies.get(COOKIE_NAME)
    try:
        authenticated = service.authenticate(token)
    except SessionReuseDetected:
        reuse_response: Response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": _REUSE_DETAIL},
            headers={"WWW-Authenticate": "Cookie"},
        )
        _delete_cookie(reuse_response, container)
        return reuse_response
    except AuthStoreUnavailable as exc:
        # Middleware runs outside FastAPI's exception handlers, so the 503 is
        # built here with the same shape the handler would produce.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": f"{_STORE_UNAVAILABLE}{exc}"},
        )

    if authenticated is None:
        denied: Response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": _LOGIN_REQUIRED},
            headers={"WWW-Authenticate": "Cookie"},
        )
        if token:
            # A presented-but-unusable cookie is stale; clear it so the browser
            # does not keep replaying it.
            _delete_cookie(denied, container)
        return denied

    request.state.auth_user = authenticated.user
    request.state.session_token = authenticated.replacement_token or token
    owner_token = bind_owner(authenticated.user.id)
    try:
        forwarded: Response = await call_next(request)
    finally:
        reset_owner(owner_token)
    if authenticated.replacement_token is not None:
        _set_cookie(forwarded, container, authenticated.replacement_token)
    return forwarded


@router.post(
    "/register",
    response_model=AuthUserOut,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: RegisterRequest, request: Request, response: Response) -> AuthUserOut:
    """Create an account and sign it in.

    Open to every registration when
    ``SYNAPSE_AUTH_ALLOW_SIGNUP=on`` (multi-user mode). Without it the first
    account claims the instance and later registrations answer 409. A duplicate
    email is the same 409, so the endpoint does not tell a caller whether a
    different account exists.
    """

    service = _enabled_service(request)
    container = _container(request)
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
    _issued_cookie(response, container, issued)
    return auth_user_out(issued.user)


@router.post("/login", response_model=AuthUserOut)
def login(payload: LoginRequest, request: Request, response: Response) -> AuthUserOut:
    """Exchange email/password for a new session family.

    A wrong password, an unknown email and a closed shop all answer 401 with the
    same message; the password check runs the KDF even for an unknown email so
    timing does not become an account oracle.
    """

    service = _enabled_service(request)
    container = _container(request)
    try:
        issued = service.login(email=payload.email, password=payload.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Cookie"},
        ) from exc
    _issued_cookie(response, container, issued)
    return auth_user_out(issued.user)


@router.post("/logout", response_model=LogoutOut)
def logout(request: Request, response: Response) -> LogoutOut:
    """Revoke the current session family and clear the cookie.

    Idempotent: calling it without a cookie succeeds. It also works when auth is
    off, so a client that was pointed at a gated server can clean up its jar.
    """

    container = _container(request)
    if container.auth is not None:
        container.auth.logout(request.cookies.get(COOKIE_NAME))
    _delete_cookie(response, container)
    return LogoutOut()


@router.get("/me", response_model=AuthUserOut)
def me(request: Request, response: Response) -> AuthUserOut:
    """The account behind the cookie; exchanges a login ticket if present."""

    service = _enabled_service(request)
    container = _container(request)
    try:
        authenticated = service.authenticate(request.cookies.get(COOKIE_NAME))
    except SessionReuseDetected as exc:
        raise _unauthorized(container, _REUSE_DETAIL) from exc
    if authenticated is None:
        raise _unauthorized(container, _LOGIN_REQUIRED)
    if authenticated.replacement_token is not None:
        _set_cookie(response, container, authenticated.replacement_token)
    return auth_user_out(authenticated.user)


def require_authenticated(request: Request) -> AuthUser | None:
    """Gate for the protected routers.

    Off means "no gate at all": the dependency returns immediately, which is why
    every existing unauthenticated test and local workflow keeps working. On
    means the middleware already authenticated the cookie (exchanging a login
    ticket if needed) and stored the account on ``request.state``; a missing
    value here means the route is not covered by the middleware, so it fails
    closed with 401 instead of running unauthenticated.

    Health, ``/auth/*``, docs/openapi, executions, knowledge search and the
    local review queue stay public on purpose.
    """

    container = _container(request)
    if not container.auth_settings.enabled:
        return None
    user = cast(AuthUser | None, getattr(request.state, "auth_user", None))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_LOGIN_REQUIRED,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user
