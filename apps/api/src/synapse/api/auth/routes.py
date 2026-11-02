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

The exchange itself lives in ``synapse.api.auth.middleware``; this module keeps
the account endpoints (register/login/logout/me) and the login failure budget.

Endpoints: ``POST /api/v1/auth/register`` 201 (open only when signup is on),
``POST /api/v1/auth/login`` 200, ``POST /api/v1/auth/logout`` 200,
``GET /api/v1/auth/me`` 200.

Failed login/register attempts are throttled by a process-local fixed-window
limiter (``application/auth/limits.py``): two buckets, per client IP and per
(IP, normalized email). The route checks before the password KDF and counts
only after a failure, so a blocked request answers 429 with ``Retry-After``
without touching credential verification. With ``SYNAPSE_AUTH=off`` the routes
stay 403 and no limiter is consulted.

With ``SYNAPSE_AUTH=off`` the account endpoints answer 403, ``logout`` still
clears a stale cookie, and ``require_authenticated`` is a no-op so the local
single-user flow is unchanged.
"""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, HTTPException, Request, Response, status

from synapse.api.auth.cookies import (
    clearing_cookie_header,
    delete_session_cookie,
    set_session_cookie,
)
from synapse.api.auth.middleware import (
    LOGIN_REQUIRED_DETAIL,
    REUSE_DETAIL,
    container_for,
)
from synapse.api.mappers.auth import auth_user_out
from synapse.api.schemas.auth import AuthUserOut, LoginRequest, LogoutOut, RegisterRequest
from synapse.application.auth.service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    RegistrationClosed,
    SessionReuseDetected,
)
from synapse.infrastructure.auth.settings import COOKIE_NAME

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_AUTH_DISABLED = "认证未启用；设置 SYNAPSE_AUTH=on 后才能使用账号接口。"
_THROTTLED = "尝试次数过多，请稍后再试。"


def _enabled_service(request: Request) -> AuthService:
    service = container_for(request).auth
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_AUTH_DISABLED,
        )
    return service


def _client_ip(request: Request) -> str:
    """The peer address uvicorn derived; nginx proxy headers are trusted there."""

    client = request.client
    return client.host if client is not None else "unknown"


def _check_failure_budget(request: Request, email: str) -> None:
    """Reject a throttled attempt before any KDF or account work happens."""

    limiter = container_for(request).auth_limiter
    if limiter is None:
        return
    retry_after = limiter.check(client_ip=_client_ip(request), email=email)
    if retry_after is None:
        return
    # Whole seconds, never 0: Retry-After = 0 invites a hot retry loop.
    wait_seconds = max(1, ceil(retry_after))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_THROTTLED,
        headers={"Retry-After": str(wait_seconds)},
    )


def _record_failure(request: Request, email: str) -> None:
    limiter = container_for(request).auth_limiter
    if limiter is not None:
        limiter.record_failure(client_ip=_client_ip(request), email=email)


def _clear_email_failures(request: Request, email: str) -> None:
    limiter = container_for(request).auth_limiter
    if limiter is not None:
        limiter.clear(client_ip=_client_ip(request), email=email)


def _unauthorized(request: Request, detail: str) -> HTTPException:
    container = container_for(request)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={
            "WWW-Authenticate": "Cookie",
            "Set-Cookie": clearing_cookie_header(container),
        },
    )


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
    different account exists. A closed or duplicate attempt counts against the
    brute-force budget; a successful registration clears this account's
    (IP, email) counter.
    """

    service = _enabled_service(request)
    container = container_for(request)
    _check_failure_budget(request, payload.email)
    try:
        issued = service.register(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except (RegistrationClosed, EmailAlreadyRegistered) as exc:
        _record_failure(request, payload.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    _clear_email_failures(request, payload.email)
    set_session_cookie(response, container, issued.token)
    return auth_user_out(issued.user)


@router.post("/login", response_model=AuthUserOut)
def login(payload: LoginRequest, request: Request, response: Response) -> AuthUserOut:
    """Exchange email/password for a new session family.

    A wrong password, an unknown email and a closed shop all answer 401 with the
    same message; the password check runs the KDF even for an unknown email so
    timing does not become an account oracle. The failure budget is checked
    first: a throttled attempt answers 429 and never reaches the KDF.
    """

    service = _enabled_service(request)
    container = container_for(request)
    _check_failure_budget(request, payload.email)
    try:
        issued = service.login(email=payload.email, password=payload.password)
    except InvalidCredentials as exc:
        _record_failure(request, payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Cookie"},
        ) from exc
    _clear_email_failures(request, payload.email)
    set_session_cookie(response, container, issued.token)
    return auth_user_out(issued.user)


@router.post("/logout", response_model=LogoutOut)
def logout(request: Request, response: Response) -> LogoutOut:
    """Revoke the current session family and clear the cookie.

    Idempotent: calling it without a cookie succeeds. It also works when auth is
    off, so a client that was pointed at a gated server can clean up its jar.
    """

    container = container_for(request)
    if container.auth is not None:
        container.auth.logout(request.cookies.get(COOKIE_NAME))
    delete_session_cookie(response, container)
    return LogoutOut()


@router.get("/me", response_model=AuthUserOut)
def me(request: Request, response: Response) -> AuthUserOut:
    """The account behind the cookie; exchanges a login ticket if present."""

    service = _enabled_service(request)
    container = container_for(request)
    try:
        authenticated = service.authenticate(request.cookies.get(COOKIE_NAME))
    except SessionReuseDetected as exc:
        raise _unauthorized(request, REUSE_DETAIL) from exc
    if authenticated is None:
        raise _unauthorized(request, LOGIN_REQUIRED_DETAIL)
    if authenticated.replacement_token is not None:
        set_session_cookie(response, container, authenticated.replacement_token)
    return auth_user_out(authenticated.user)
