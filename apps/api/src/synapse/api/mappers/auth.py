"""Account mapper."""

from __future__ import annotations

from synapse.api.schemas.auth import AuthUserOut
from synapse.application.auth.service import AuthUser


def auth_user_out(user: AuthUser) -> AuthUserOut:
    """Only the public account fields; digest and token are not reachable here."""

    return AuthUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
    )
