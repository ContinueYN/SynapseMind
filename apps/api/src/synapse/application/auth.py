"""Account and session use cases for a self-hosted, single-owner deployment.

There are no roles, tenants or classrooms here: one deployment holds one owner
account, plus more only if the operator explicitly re-opens registration
(``SYNAPSE_AUTH_ALLOW_SIGNUP=on``). That is why the default policy is
"first registration wins, later ones get 409" instead of pretending to be a
multi-tenant signup service.

The service depends on three ports only — a user store, a session-token store
and a password hasher — so SQLite, PostgreSQL and Redis are infrastructure
choices, not part of the use case.

Two boundaries this module keeps:

* Raw secrets never reach a store. Passwords arrive as KDF digests; session
  tokens are stored as SHA-256 digests, so a database read cannot be replayed
  as a cookie.
* Expiry is checked here, not only in the store, so a token store that forgets
  its TTL (or a SQL row read after the fact) still cannot authenticate.

The "first registration wins" rule is a plain user count, not a transaction
lock: two simultaneous first registrations with *different* e-mails could both
pass. That is acceptable for a single-owner instance and is recorded as a
follow-up rather than hidden behind a fake invitation flow.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

# A fixed, never-matching Argon2id digest. Verifying against it when the email
# is unknown spends the same KDF time as a real check, so login latency does
# not reveal whether an account exists. It is not a credential: the password it
# digests was random and discarded.
_UNKNOWN_USER_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$2GxFnskIEajjVRGjif8E5g$"
    "XKIn9mzTJ+msLaSST4NSjfMsTzmnTAUgE1gN50XEEZg"
)


class AuthError(RuntimeError):
    """Base class for account/session failures the API maps to a status."""


class InvalidCredentials(AuthError):
    """Email/password did not match. The message never says which one."""


class RegistrationClosed(AuthError):
    """This deployment already has an owner and signup is not re-opened."""


class EmailAlreadyRegistered(AuthError):
    """The normalized email already has an account."""


class AuthStoreUnavailable(AuthError):
    """The account database or Redis is configured but not usable."""


@dataclass(frozen=True, slots=True)
class UserRecord:
    """What a user store returns, including the digest used by login."""

    id: str
    email: str
    display_name: str | None
    password_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthUser:
    """A public account view; the password digest is deliberately absent."""

    id: str
    email: str
    display_name: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionToken:
    """The server-side half of a cookie: owner and hard expiry."""

    user_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A freshly issued cookie value plus the account it belongs to."""

    token: str
    expires_at: datetime
    user: AuthUser


def hash_session_token(token: str) -> str:
    """The only form of a session token a store is allowed to see."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PasswordHasher(Protocol):
    """A real KDF; the infrastructure adapter uses Argon2id."""

    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


class UserStore(Protocol):
    def count(self) -> int: ...

    def find_by_email(self, email: str) -> UserRecord | None: ...

    def get(self, user_id: str) -> UserRecord | None: ...

    def create(
        self,
        *,
        email: str,
        display_name: str | None,
        password_hash: str,
        created_at: datetime,
    ) -> UserRecord: ...


class SessionTokenStore(Protocol):
    """Opaque bearer tokens: SQLite/PostgreSQL rows or Redis keys with a TTL."""

    def create(self, *, token_hash: str, user_id: str, expires_at: datetime) -> None: ...

    def resolve(self, token_hash: str) -> SessionToken | None: ...

    def revoke(self, token_hash: str) -> None: ...


class AuthService:
    """Register/login/logout plus cookie -> account resolution."""

    def __init__(
        self,
        *,
        users: UserStore,
        tokens: SessionTokenStore,
        hasher: PasswordHasher,
        session_ttl_s: int,
        allow_signup: bool = False,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._hasher = hasher
        self._session_ttl_s = session_ttl_s
        self._allow_signup = allow_signup
        self._clock = clock

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> IssuedSession:
        normalized = normalize_email(email)
        if not self._allow_signup and self._users.count() > 0:
            raise RegistrationClosed(
                "这个自托管实例已有账号，注册已关闭；"
                "如需再开一个账号，请设置 SYNAPSE_AUTH_ALLOW_SIGNUP=on。"
            )
        if self._users.find_by_email(normalized) is not None:
            raise EmailAlreadyRegistered("该邮箱已注册。")
        now = self._clock()
        record = self._users.create(
            email=normalized,
            display_name=display_name,
            password_hash=self._hasher.hash(password),
            created_at=now,
        )
        return self._issue(record, now)

    def login(self, *, email: str, password: str) -> IssuedSession:
        record = self._users.find_by_email(normalize_email(email))
        if record is None:
            # Same KDF cost as a real check; the result is irrelevant.
            self._hasher.verify(_UNKNOWN_USER_HASH, password)
            raise InvalidCredentials("邮箱或密码不正确。")
        if not self._hasher.verify(record.password_hash, password):
            raise InvalidCredentials("邮箱或密码不正确。")
        return self._issue(record, self._clock())

    def logout(self, token: str | None) -> None:
        """Revoke server-side state; a missing/blank cookie is a no-op."""

        if not token:
            return
        self._tokens.revoke(hash_session_token(token))

    def principal(self, token: str | None) -> AuthUser | None:
        """Resolve a cookie value to an account, or ``None``.

        Missing, unknown, revoked and expired tokens are indistinguishable to a
        caller: all yield ``None``.
        """

        if not token:
            return None
        record = self._tokens.resolve(hash_session_token(token))
        if record is None:
            return None
        if record.expires_at <= self._clock():
            return None
        user = self._users.get(record.user_id)
        if user is None:
            # The account disappeared; drop the orphaned session token.
            self._tokens.revoke(hash_session_token(token))
            return None
        return AuthUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
        )

    def _issue(self, record: UserRecord, now: datetime) -> IssuedSession:
        token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=self._session_ttl_s)
        self._tokens.create(
            token_hash=hash_session_token(token),
            user_id=record.id,
            expires_at=expires_at,
        )
        return IssuedSession(
            token=token,
            expires_at=expires_at,
            user=AuthUser(
                id=record.id,
                email=record.email,
                display_name=record.display_name,
                created_at=record.created_at,
            ),
        )
