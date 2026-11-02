"""Account and session use cases for a self-hosted, multi-user deployment.

There are no role or tenant tables here: every registered account gets
its own isolated workspace (see ``SessionService.with_owner``). Registration is
open when ``SYNAPSE_AUTH_ALLOW_SIGNUP=on``; when it is off the deployment keeps
the original "first registration wins, later ones get 409" policy so a personal
instance cannot be claimed by a stranger.

The service depends on three ports only — a user store, a session-token store
and a password hasher — so SQLite, PostgreSQL and Redis are infrastructure
choices, not part of the use case.

Three boundaries this module keeps:

* Raw secrets never reach a store. Passwords arrive as KDF digests; session
  tokens are stored as SHA-256 digests, so a database read cannot be replayed
  as a cookie.
* A cookie is either a **one-time login ticket** (``L_…``) or an **ordinary
  session** (``S_…``). Register/login issue a ticket; the first authenticated
  request consumes it atomically and mints an ordinary session in the same
  family. Presenting a consumed ticket again is the theft signal and revokes
  the whole family, while an ordinary session is looked up in place and reused
  until logout/expiry — it is never consumed per request. Legacy unprefixed
  cookies are treated as ordinary sessions.
* Expiry is checked here, not only in the store, so a token store that forgets
  its TTL (or a SQL row read after the fact) still cannot authenticate.

The "first registration wins" rule is a plain user count, not a transaction
lock: two simultaneous first registrations with *different* e-mails could both
pass when signup is off. That is acceptable when signup is deliberately closed
and only the operator registers, and is recorded as a follow-up rather than
hidden behind a fake invitation flow. With ``allow_signup=True`` the count is
not consulted at all.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import uuid4

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


class SessionReuseDetected(AuthError):
    """A consumed cookie was presented again; the whole family is revoked."""

    def __init__(self, message: str, *, family_id: str | None = None) -> None:
        super().__init__(message)
        self.family_id = family_id


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


TokenStatus = Literal["active", "used", "unknown", "revoked"]


@dataclass(frozen=True, slots=True)
class TokenState:
    """What a token store can prove about one presented cookie digest.

    ``active`` means the digest was unspent (the store may or may not have
    marked it spent by the time this value is returned); ``used`` means it was
    already consumed and is evidence of replay; ``revoked`` means the session
    family was closed; ``unknown`` means no such digest was ever issued.
    ``expires_at`` is carried so the use case — not the store — decides whether
    an otherwise valid token is too old.
    """

    status: TokenStatus
    user_id: str | None = None
    family_id: str | None = None
    expires_at: datetime | None = None

    @classmethod
    def unknown(cls) -> TokenState:
        return cls(status="unknown")


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A freshly issued cookie value plus the account it belongs to."""

    token: str
    expires_at: datetime
    user: AuthUser
    family_id: str = ""


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """The account behind a presented cookie, plus an optional replacement.

    ``replacement_token`` is set only when a one-time login ticket was consumed
    and exchanged for an ordinary session. An ordinary cookie authenticates in
    place: it returns no replacement, so the API must not send ``Set-Cookie``.
    """

    user: AuthUser
    family_id: str
    replacement_token: str | None = None


# Login tickets are single-use; ordinary sessions are reused until logout/TTL.
# Stores only ever see SHA-256 digests, so the prefix costs no schema change.
LOGIN_TICKET_PREFIX = "L_"
SESSION_PREFIX = "S_"


def _is_login_ticket(token: str) -> bool:
    return token.startswith(LOGIN_TICKET_PREFIX)


def _new_token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def hash_session_token(token: str) -> str:
    """The only form of a session token a store is allowed to see."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_family_id() -> str:
    """A stable identifier for one login's token family."""

    return f"F_{uuid4().hex}"


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
    """Session-token records: SQL rows or Redis keys with a native TTL.

    ``lookup`` is read-only and is the ordinary-session path. ``consume`` must
    be atomic and is used only for one-time login tickets (and store-level race
    tests): two concurrent calls for the same digest may not both return
    ``active``. The SQL adapter relies on a conditional ``UPDATE``; the Redis
    adapter uses ``GETDEL`` plus a tombstone.
    """

    def issue(
        self,
        *,
        token_hash: str,
        user_id: str,
        family_id: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    def consume(self, token_hash: str, *, now: datetime) -> TokenState: ...

    def lookup(self, token_hash: str, *, now: datetime) -> TokenState: ...

    def revoke_family(self, family_id: str, *, now: datetime) -> None: ...


class AuthService:
    """Register/login/logout plus the login-ticket exchange."""

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
        return self._issue(
            record,
            now,
            family_id=new_family_id(),
            prefix=LOGIN_TICKET_PREFIX,
        )

    def login(self, *, email: str, password: str) -> IssuedSession:
        record = self._users.find_by_email(normalize_email(email))
        if record is None:
            # Same KDF cost as a real check; the result is irrelevant.
            self._hasher.verify(_UNKNOWN_USER_HASH, password)
            raise InvalidCredentials("邮箱或密码不正确。")
        if not self._hasher.verify(record.password_hash, password):
            raise InvalidCredentials("邮箱或密码不正确。")
        return self._issue(
            record,
            self._clock(),
            family_id=new_family_id(),
            prefix=LOGIN_TICKET_PREFIX,
        )

    def logout(self, token: str | None) -> None:
        """Revoke the whole family behind a cookie; blank input is a no-op.

        A lookup (not a consume) is enough: logout must never raise the reuse
        alarm, and revoking the family closes both an unspent login ticket and
        an ordinary session. An unknown or already-revoked cookie is a
        successful no-op so a client can always clean its jar.
        """

        if not token:
            return
        now = self._clock()
        state = self._tokens.lookup(hash_session_token(token), now=now)
        if state.family_id is not None:
            self._tokens.revoke_family(state.family_id, now=now)

    def authenticate(self, token: str | None) -> AuthenticatedSession | None:
        """Resolve one presented cookie.

        ``None`` means "not logged in": missing, unknown, revoked, spent by a
        non-ticket path or expired. A login ticket is consumed exactly once; its
        first use mints an ordinary session in the same family. Presenting an
        already-consumed ticket raises :class:`SessionReuseDetected` after the
        whole family has been revoked — that is the theft signal. An ordinary
        session is looked up in place and never consumed, so reusing it is not
        detectable and simply keeps authenticating.
        """

        if not token:
            return None
        now = self._clock()
        token_hash = hash_session_token(token)
        is_ticket = _is_login_ticket(token)
        state = (
            self._tokens.consume(token_hash, now=now)
            if is_ticket
            else self._tokens.lookup(token_hash, now=now)
        )

        if state.status == "used":
            if is_ticket:
                family_id = state.family_id
                if family_id is not None:
                    self._tokens.revoke_family(family_id, now=now)
                raise SessionReuseDetected(
                    "检测到会话被复用，已强制下线，请重新登录。",
                    family_id=family_id,
                )
            # An ordinary cookie is never consumed; ``used`` can only be a
            # legacy row from the old per-request rotation. Fail closed without
            # accusing the browser of theft.
            return None
        if state.status in {"unknown", "revoked"}:
            return None
        if state.user_id is None or state.expires_at is None:
            return None
        if state.expires_at <= now:
            # The store may not have swept the row yet; the hard expiry wins.
            return None

        user = self._users.get(state.user_id)
        if user is None:
            # The account disappeared; close what is left of the chain.
            if state.family_id is not None:
                self._tokens.revoke_family(state.family_id, now=now)
            return None

        # Backfills from the pre-rotation schema are ``family_id == id``; a
        # store that somehow lost it starts a fresh family instead of sharing
        # one with an unrelated token.
        family_id = state.family_id or new_family_id()
        if not is_ticket:
            return AuthenticatedSession(user=_to_auth_user(user), family_id=family_id)
        issued = self._issue(
            user,
            now,
            family_id=family_id,
            prefix=SESSION_PREFIX,
        )
        return AuthenticatedSession(
            user=issued.user,
            family_id=family_id,
            replacement_token=issued.token,
        )

    def _issue(
        self,
        record: UserRecord,
        now: datetime,
        *,
        family_id: str,
        prefix: str,
    ) -> IssuedSession:
        token = _new_token(prefix)
        expires_at = now + timedelta(seconds=self._session_ttl_s)
        self._tokens.issue(
            token_hash=hash_session_token(token),
            user_id=record.id,
            family_id=family_id,
            created_at=now,
            expires_at=expires_at,
        )
        return IssuedSession(
            token=token,
            expires_at=expires_at,
            user=_to_auth_user(record),
            family_id=family_id,
        )


def _to_auth_user(record: UserRecord) -> AuthUser:
    return AuthUser(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        created_at=record.created_at,
    )
