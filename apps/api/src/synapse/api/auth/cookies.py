"""Session cookie helpers shared by the auth endpoints and middleware.

The cookie is the whole session: HttpOnly, SameSite=Lax, path=/, Secure only
when ``SYNAPSE_COOKIE_SECURE=on``, max-age = ``SYNAPSE_AUTH_SESSION_TTL_S``.
"""

from __future__ import annotations

from fastapi import Response

from synapse.api.deps import Container
from synapse.infrastructure.auth.settings import COOKIE_NAME


def set_session_cookie(response: Response, container: Container, token: str) -> None:
    """Attach the ordinary session cookie to ``response``."""

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


def delete_session_cookie(response: Response, container: Container) -> None:
    """Clear the session cookie with the same attributes it was set with."""

    settings = container.auth_settings
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clearing_cookie_header(container: Container) -> str:
    """A ``Set-Cookie`` value that clears the cookie, for an HTTPException.

    FastAPI's exception handler builds a fresh response, so headers set on the
    injected ``Response`` would be dropped. Generating the header from a scratch
    ``Response`` keeps path/Secure/SameSite identical to the one we set.
    """

    scratch = Response()
    delete_session_cookie(scratch, container)
    return scratch.headers["set-cookie"]
