"""Request-scoped owner binding for the model runtime.

The BYOK client has to know *which* user is calling before it can pick a key,
but the LLM adapters are built once at composition time. A ``ContextVar`` is the
smallest reliable seam: the async auth middleware sets it before the request is
dispatched (``anyio`` copies the context into FastAPI's sync threadpool), and the
client reads it on every ``complete`` call.

Nothing else in the application layer reads this value. A ``None`` owner means
"authentication is off, or this is a public endpoint": only the server-side
fallback key may be used there.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_OWNER: ContextVar[str | None] = ContextVar("synapse_owner_id", default=None)


def bind_owner(user_id: str | None) -> Token[str | None]:
    """Bind the current owner for the duration of one request."""

    return _OWNER.set(user_id)


def reset_owner(token: Token[str | None]) -> None:
    """Restore the previous binding (always in a ``finally``)."""

    _OWNER.reset(token)


def current_owner_id() -> str | None:
    """The account id bound to the current request, if any."""

    return _OWNER.get()
