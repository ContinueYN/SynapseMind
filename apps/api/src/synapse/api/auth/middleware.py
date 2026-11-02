"""Session authentication middleware and the protected-router gate.

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

* ``/api/v1/sessions…``, ``/api/v1/settings…``, ``/api/v1/review…`` and
  ``/api/v1/executions`` — the async ``session_auth_middleware``. It must be
  async because the model runtime reads the current user from a
  ``ContextVar``, and a ``ContextVar`` set inside a sync FastAPI dependency is
  not guaranteed to reach the sync route in another worker thread. ``anyio``
  copies the async context into the threadpool, so a value set before dispatch
  is visible downstream.
* ``GET /auth/me`` — the endpoint itself, because it is not under a protected
  prefix. ``POST /auth/login|register`` start a new family; ``POST /auth/logout``
  revokes the family and clears the cookie.

With ``SYNAPSE_AUTH=off`` the middleware does nothing and
``require_authenticated`` is a no-op, so the local single-user flow is
unchanged.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from synapse.api.auth.cookies import delete_session_cookie, set_session_cookie
from synapse.api.deps import Container
from synapse.application.auth.service import (
    AuthStoreUnavailable,
    AuthUser,
    SessionReuseDetected,
)
from synapse.application.shared.context import bind_owner, reset_owner
from synapse.infrastructure.auth.settings import COOKIE_NAME

LOGIN_REQUIRED_DETAIL = "需要先登录。"
REUSE_DETAIL = "检测到会话被复用，已强制下线，请重新登录。"
_STORE_UNAVAILABLE = "账号服务暂不可用："

# Only these resources exchange the login ticket. Public routes (health, docs,
# knowledge search, the account endpoints) must never touch the cookie: a
# public page load would otherwise burn the session the diagnostic page is
# using. Review and executions are internal resources, so they are protected
# too; /auth/* is the only route family that starts a session.
_PROTECTED_PREFIXES = (
    "/api/v1/sessions",
    "/api/v1/settings",
    "/api/v1/review",
    "/api/v1/executions",
)


def container_for(request: Request) -> Container:
    """The composition root attached to the running app."""

    return cast(Container, request.app.state.container)


def is_protected(path: str) -> bool:
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

    if not container.auth_settings.enabled or not is_protected(request.url.path):
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
            content={"detail": REUSE_DETAIL},
            headers={"WWW-Authenticate": "Cookie"},
        )
        delete_session_cookie(reuse_response, container)
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
            content={"detail": LOGIN_REQUIRED_DETAIL},
            headers={"WWW-Authenticate": "Cookie"},
        )
        if token:
            # A presented-but-unusable cookie is stale; clear it so the browser
            # does not keep replaying it.
            delete_session_cookie(denied, container)
        return denied

    request.state.auth_user = authenticated.user
    request.state.session_token = authenticated.replacement_token or token
    owner_token = bind_owner(authenticated.user.id)
    try:
        forwarded: Response = await call_next(request)
    finally:
        reset_owner(owner_token)
    # A ticket is consumed before dispatch. If the route raises, this header is
    # never sent and the browser keeps the spent value; the next request trips
    # the reuse alarm and asks for a fresh login. We do not swallow the
    # exception just to attach the replacement cookie.
    if authenticated.replacement_token is not None:
        set_session_cookie(forwarded, container, authenticated.replacement_token)
    return forwarded


def require_authenticated(request: Request) -> AuthUser | None:
    """Gate for the protected routers.

    Off means "no gate at all": the dependency returns immediately, which is why
    every existing unauthenticated test and local workflow keeps working. On
    means the middleware already authenticated the cookie (exchanging a login
    ticket if needed) and stored the account on ``request.state``; a missing
    value here means the route is not covered by the middleware, so it fails
    closed with 401 instead of running unauthenticated.

    Health, ``/auth/*``, docs/openapi and knowledge search stay public on purpose.
    Review and executions are internal resources: they are in the middleware's
    protected prefixes, so enabling auth turns an anonymous call into 401.
    """

    container = container_for(request)
    if not container.auth_settings.enabled:
        return None
    user = cast(AuthUser | None, getattr(request.state, "auth_user", None))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_REQUIRED_DETAIL,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user
