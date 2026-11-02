"""Auth protocol package: endpoints, session middleware and cookie helpers."""

from synapse.api.auth.middleware import require_authenticated, session_auth_middleware
from synapse.api.auth.routes import router

__all__ = ["require_authenticated", "router", "session_auth_middleware"]
