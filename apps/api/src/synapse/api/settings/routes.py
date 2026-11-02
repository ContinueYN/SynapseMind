"""Per-user model settings (BYOK) endpoints.

Four operations on ``/api/v1/settings/model``:

``GET``     the masked public view (never the key)
``PUT``     encrypt and store the caller's own key
``POST``    ``/test``: one tiny provider round trip with the saved or a candidate key
``DELETE``  remove the stored key (204, idempotent)

Authentication is required and the caller's own row is the only row touched, so
user A can never read or overwrite user B's credential. With ``SYNAPSE_AUTH=off``
the endpoints answer 403: there is no account to attach a key to, and the local
baseline keeps using the optional server key.

Ticket exchange: these routes sit under ``/api/v1/settings``, which the async
auth middleware treats like ``/api/v1/sessions`` — presenting a login ticket
consumes it and the response carries the ordinary session cookie; an ordinary
session is reused without a new ``Set-Cookie``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from synapse.api.deps import Container
from synapse.api.mappers.settings import model_credential_out, model_test_out
from synapse.api.schemas.settings import (
    ModelCredentialIn,
    ModelCredentialOut,
    ModelCredentialTestIn,
    ModelTestOut,
)
from synapse.application.auth.service import AuthUser
from synapse.application.credentials.service import (
    CredentialInput,
    CredentialService,
    CredentialTestInput,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_AUTH_DISABLED = "认证未启用；设置 SYNAPSE_AUTH=on 后才能保存个人模型密钥。"
_LOGIN_REQUIRED = "需要先登录。"


@dataclass(frozen=True, slots=True)
class SettingsContext:
    """The caller's credential service and account, resolved once per request."""

    service: CredentialService
    user: AuthUser


def get_settings_context(request: Request) -> SettingsContext:
    """The BYOK service plus the authenticated account.

    The middleware has already authenticated the cookie and stored the account on
    ``request.state``. Without auth there is no account, so the endpoint is 403
    rather than pretending the server key is the user's.
    """

    container = cast(Container, request.app.state.container)
    if container.auth is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_AUTH_DISABLED)
    service = container.credentials
    if service is None:  # pragma: no cover - auth always builds credentials
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="模型凭据服务未初始化。",
        )
    user = cast(AuthUser | None, getattr(request.state, "auth_user", None))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_LOGIN_REQUIRED,
            headers={"WWW-Authenticate": "Cookie"},
        )
    return SettingsContext(service=service, user=user)


@router.get("/model", response_model=ModelCredentialOut)
def get_model_settings(ctx: SettingsContext = Depends(get_settings_context)) -> ModelCredentialOut:
    """The masked view; ``configured`` is false until a key is stored and usable."""

    return model_credential_out(ctx.service.get_public(ctx.user.id))


@router.put("/model", response_model=ModelCredentialOut)
def put_model_settings(
    payload: ModelCredentialIn,
    ctx: SettingsContext = Depends(get_settings_context),
) -> ModelCredentialOut:
    """Store (or replace) this account's key, encrypted with the master key.

    The response is the same masked view as ``GET``: the key is never echoed and
    is not recoverable through the API afterwards.
    """

    public = ctx.service.save(
        ctx.user.id,
        CredentialInput(
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
        ),
    )
    return model_credential_out(public)


@router.post("/model/test", response_model=ModelTestOut)
def test_model_settings(
    payload: ModelCredentialTestIn | None = None,
    ctx: SettingsContext = Depends(get_settings_context),
) -> ModelTestOut:
    """Call the provider once with a one-token request.

    A provider-side rejection or network failure is a normal ``200`` with
    ``ok=false`` and a key-free message; a malformed URL/input is 422 and a
    missing master key is 503. Nothing from the response body is echoed.
    """

    candidate = payload or ModelCredentialTestIn()
    result = ctx.service.test(
        ctx.user.id,
        CredentialTestInput(
            provider=candidate.provider,
            base_url=candidate.base_url,
            model=candidate.model,
            api_key=candidate.api_key,
        ),
    )
    return model_test_out(result)


@router.delete("/model", status_code=status.HTTP_204_NO_CONTENT)
def delete_model_settings(ctx: SettingsContext = Depends(get_settings_context)) -> Response:
    """Delete this account's stored key; deleting nothing is still 204."""

    ctx.service.delete(ctx.user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
