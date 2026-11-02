"""Focused tests for the self-hosted account layer and its persistence.

Deliberately small and dependency-free: SQLite on a temp file, a migrated schema
via the checked-in Alembic config, and a dict-backed fake Redis. No network, no
clock sleeping (expiry is forced through the database or an injected clock).
"""

from __future__ import annotations

import hashlib
import io
import secrets
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import cast

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from alembic import command
from synapse.api.deps import Container, build_container
from synapse.api.main import create_app
from synapse.application.auth.service import (
    LOGIN_TICKET_PREFIX,
    SESSION_PREFIX,
    AuthService,
    SessionReuseDetected,
    hash_session_token,
)
from synapse.application.execution.service import ExecutionResult, RunCodeCommand
from synapse.infrastructure.auth.build import build_auth
from synapse.infrastructure.auth.db import (
    AuthSessionRow,
    Base,
    build_session_factory,
    create_auth_engine,
)
from synapse.infrastructure.auth.passwords import Argon2PasswordHasher
from synapse.infrastructure.auth.settings import (
    COOKIE_NAME,
    DEFAULT_DATABASE_URL,
    DEFAULT_FAILURE_WINDOW_S,
    DEFAULT_MAX_FAILURES_PER_EMAIL,
    DEFAULT_MAX_FAILURES_PER_IP,
    DEFAULT_SESSION_TTL_S,
    AuthSettings,
)
from synapse.infrastructure.auth.stores import (
    RedisSessionTokenStore,
    SqlSessionTokenStore,
    SqlUserStore,
)
from synapse.infrastructure.credentials.db import UserModelCredentialRow
from synapse.infrastructure.features import FeatureFlags

APPS_API = Path(__file__).resolve().parents[1]
ALEMBIC_INI = APPS_API / "alembic.ini"

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "correct horse battery"


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def _upgrade(url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def _cookie_token(client: TestClient) -> str:
    token = client.cookies.get(COOKIE_NAME)
    assert token, "expected a session cookie"
    return token


def _register(client: TestClient, email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )


@dataclass(frozen=True)
class AuthHarness:
    app: FastAPI
    client: TestClient
    database: Path
    url: str

    def anonymous(self) -> TestClient:
        """A client without the owner's cookie jar."""

        return TestClient(self.app)

    @property
    def container(self) -> Container:
        return cast(Container, self.app.state.container)


class _PassThroughExecutor:
    """A fake executor so the gated executions route can return 200."""

    def __init__(self) -> None:
        self.commands: list[RunCodeCommand] = []

    def run(self, command: RunCodeCommand) -> ExecutionResult:
        self.commands.append(command)
        return ExecutionResult(
            status="pass",
            detail="ok",
            exit_code=0,
            duration_ms=1,
            stdout="ok\n",
        )


@pytest.fixture()
def make_auth_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., AuthHarness]]:
    """Build gated apps (one migrated SQLite file each) and dispose their engines."""

    containers: list[Container] = []
    counter = count()

    def make(
        *,
        allow_signup: bool = False,
        ttl_s: int = 3600,
        cookie_secure: bool = False,
        redis_url: str | None = None,
        max_failures_per_ip: int = 10,
        max_failures_per_email: int = 5,
        failure_window_s: int = 300,
        executor: object | None = None,
    ) -> AuthHarness:
        database = tmp_path / f"auth-{next(counter)}.sqlite3"
        url = _sqlite_url(database)
        monkeypatch.setenv("SYNAPSE_AUTH", "on")
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", url)
        monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", str(ttl_s))
        monkeypatch.setenv("SYNAPSE_AUTH_ALLOW_SIGNUP", "on" if allow_signup else "off")
        monkeypatch.setenv("SYNAPSE_COOKIE_SECURE", "on" if cookie_secure else "off")
        monkeypatch.setenv("SYNAPSE_AUTH_MAX_FAILURES_PER_IP", str(max_failures_per_ip))
        monkeypatch.setenv("SYNAPSE_AUTH_MAX_FAILURES_PER_EMAIL", str(max_failures_per_email))
        monkeypatch.setenv("SYNAPSE_AUTH_FAILURE_WINDOW_S", str(failure_window_s))
        if redis_url is None:
            monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
        else:
            monkeypatch.setenv("SYNAPSE_REDIS_URL", redis_url)
        _upgrade(url)
        if executor is None:
            app = create_app()
        else:
            app = create_app(
                build_container(
                    features=FeatureFlags(execution=True),
                    executor=executor,  # type: ignore[arg-type]
                )
            )
        containers.append(cast(Container, app.state.container))
        return AuthHarness(app=app, client=TestClient(app), database=database, url=url)

    try:
        yield make
    finally:
        for container in containers:
            if container.auth_dispose is not None:
                container.auth_dispose()


def _expire_all_sessions(url: str) -> None:
    engine = create_auth_engine(url)
    factory = build_session_factory(engine)
    with factory() as session:
        for row in session.scalars(select(AuthSessionRow)):
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()
    engine.dispose()


# --------------------------------------------------------------------------
# Settings: the environment contract
# --------------------------------------------------------------------------


def test_settings_defaults_are_off(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = AuthSettings.from_env()
    assert settings.enabled is False
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.redis_url is None
    assert settings.allow_signup is False
    assert settings.cookie_secure is False
    assert settings.session_ttl_s == DEFAULT_SESSION_TTL_S
    assert settings.max_failures_per_ip == DEFAULT_MAX_FAILURES_PER_IP == 10
    assert settings.max_failures_per_email == DEFAULT_MAX_FAILURES_PER_EMAIL == 5
    assert settings.failure_window_s == DEFAULT_FAILURE_WINDOW_S == 300
    assert COOKIE_NAME == "synapse_session"


def test_settings_read_the_documented_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_AUTH", "on")
    monkeypatch.setenv(
        "SYNAPSE_DATABASE_URL",
        "postgresql+psycopg://synapse:synapse@postgres:5432/synapse",
    )
    monkeypatch.setenv("SYNAPSE_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("SYNAPSE_AUTH_ALLOW_SIGNUP", "on")
    monkeypatch.setenv("SYNAPSE_COOKIE_SECURE", "on")
    monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", "900")
    monkeypatch.setenv("SYNAPSE_AUTH_MAX_FAILURES_PER_IP", "20")
    monkeypatch.setenv("SYNAPSE_AUTH_MAX_FAILURES_PER_EMAIL", "7")
    monkeypatch.setenv("SYNAPSE_AUTH_FAILURE_WINDOW_S", "120")
    settings = AuthSettings.from_env()
    assert settings.enabled is True
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.allow_signup is True
    assert settings.cookie_secure is True
    assert settings.session_ttl_s == 900
    assert settings.max_failures_per_ip == 20
    assert settings.max_failures_per_email == 7
    assert settings.failure_window_s == 120


def test_settings_reject_a_bad_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_AUTH", "onn")
    with pytest.raises(ValueError, match="SYNAPSE_AUTH"):
        AuthSettings.from_env()


def test_settings_validate_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", "later")
    with pytest.raises(ValueError, match="SYNAPSE_AUTH_SESSION_TTL_S"):
        AuthSettings.from_env()
    monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", "0")
    with pytest.raises(ValueError, match="SYNAPSE_AUTH_SESSION_TTL_S"):
        AuthSettings.from_env()


@pytest.mark.parametrize(
    "name",
    [
        "SYNAPSE_AUTH_MAX_FAILURES_PER_IP",
        "SYNAPSE_AUTH_MAX_FAILURES_PER_EMAIL",
        "SYNAPSE_AUTH_FAILURE_WINDOW_S",
    ],
)
@pytest.mark.parametrize("raw", ["0", "-3", "later", "1.5"])
def test_settings_validate_the_failure_buckets(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    raw: str,
) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(ValueError, match=name):
        AuthSettings.from_env()


# --------------------------------------------------------------------------
# Registration / login / me / logout
# --------------------------------------------------------------------------


def test_register_first_owner_sets_hardened_cookie(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    response = _register(harness.client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == OWNER_EMAIL
    assert body["display_name"] is None
    assert "password" not in body
    assert "created_at" in body

    cookie = response.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=3600" in cookie
    assert "secure" not in cookie

    me = harness.client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == OWNER_EMAIL


def test_register_normalizes_email_and_display_name(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    response = harness.client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Owner@Example.COM ",
            "password": OWNER_PASSWORD,
            "display_name": "  Owner   Name  ",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["email"] == OWNER_EMAIL
    assert response.json()["display_name"] == "Owner Name"
    # Login is case-insensitive because the stored address is normalized.
    assert (
        harness.anonymous()
        .post(
            "/api/v1/auth/login",
            json={"email": "OWNER@example.com", "password": OWNER_PASSWORD},
        )
        .status_code
        == 200
    )


def test_second_registration_is_closed_by_default(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    second = _register(harness.anonymous(), email="second@example.com")
    assert second.status_code == 409
    assert "SYNAPSE_AUTH_ALLOW_SIGNUP" in second.json()["detail"]


def test_second_registration_allowed_when_signup_is_on(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(allow_signup=True)
    assert _register(harness.client).status_code == 201
    assert _register(harness.anonymous(), email="second@example.com").status_code == 201


def test_duplicate_email_is_conflict_even_with_signup_on(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(allow_signup=True)
    assert _register(harness.client).status_code == 201
    duplicate = _register(harness.anonymous(), email="Owner@Example.com")
    assert duplicate.status_code == 409
    assert "已注册" in duplicate.json()["detail"]


def test_register_rejects_a_short_password(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client, password="short").status_code == 422


def test_login_rejects_wrong_password(make_auth_app: Callable[..., AuthHarness]) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    response = harness.anonymous().post(
        "/api/v1/auth/login",
        json={"email": OWNER_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Cookie"
    assert "set-cookie" not in response.headers


def test_login_rejects_unknown_email(make_auth_app: Callable[..., AuthHarness]) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    response = harness.anonymous().post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": OWNER_PASSWORD},
    )
    assert response.status_code == 401


def test_login_issues_a_new_server_side_session(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    first = _cookie_token(harness.client)
    anonymous = harness.anonymous()
    login = anonymous.post(
        "/api/v1/auth/login",
        json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
    )
    assert login.status_code == 200
    second = _cookie_token(anonymous)
    assert second != first
    assert anonymous.get("/api/v1/auth/me").status_code == 200


def test_me_requires_a_session(make_auth_app: Callable[..., AuthHarness]) -> None:
    harness = make_auth_app()
    response = harness.anonymous().get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Cookie"


def test_logout_revokes_the_server_side_session(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    token = _cookie_token(harness.client)

    logout = harness.client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"status": "ok"}
    clear_cookie = logout.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in clear_cookie
    assert "max-age=0" in clear_cookie
    assert harness.client.get("/api/v1/auth/me").status_code == 401

    # Replaying the old value must fail too: logout touched the server, not just
    # the browser's jar.
    replay = harness.anonymous()
    replay.cookies.set(COOKIE_NAME, token)
    assert replay.get("/api/v1/auth/me").status_code == 401


def test_logout_without_a_cookie_is_idempotent(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    assert make_auth_app().anonymous().post("/api/v1/auth/logout").status_code == 200


# --------------------------------------------------------------------------
# Brute-force throttle (process-local, fixed window)
# --------------------------------------------------------------------------


def _wrong_login(client: TestClient, email: str = OWNER_EMAIL):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password"},
    )


def test_login_is_throttled_per_email(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(
        max_failures_per_ip=10,
        max_failures_per_email=2,
        failure_window_s=120,
    )
    assert _register(harness.client).status_code == 201
    anonymous = harness.anonymous()

    assert _wrong_login(anonymous).status_code == 401
    assert _wrong_login(anonymous).status_code == 401
    blocked = _wrong_login(anonymous)

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "尝试次数过多，请稍后再试。"
    retry_after = int(blocked.headers["Retry-After"])
    assert 1 <= retry_after <= 120
    # No credential echo and no account-existence hint in the body.
    assert OWNER_EMAIL not in blocked.text


def test_login_is_throttled_per_ip_across_different_emails(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(
        max_failures_per_ip=2,
        max_failures_per_email=10,
        failure_window_s=60,
    )
    assert _register(harness.client).status_code == 201
    anonymous = harness.anonymous()

    # Each address has its own (IP, email) budget; only the IP bucket is shared.
    assert _wrong_login(anonymous, "nobody-1@example.com").status_code == 401
    assert _wrong_login(anonymous, "nobody-2@example.com").status_code == 401
    blocked = _wrong_login(anonymous, "nobody-3@example.com")

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_a_successful_login_clears_that_accounts_failure_count(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(max_failures_per_ip=10, max_failures_per_email=2)
    assert _register(harness.client).status_code == 201
    anonymous = harness.anonymous()

    def login(password: str):
        return anonymous.post(
            "/api/v1/auth/login",
            json={"email": OWNER_EMAIL, "password": password},
        )

    assert login("wrong-password").status_code == 401
    assert login(OWNER_PASSWORD).status_code == 200  # clears the (IP, email) count
    assert login("wrong-password").status_code == 401
    assert login(OWNER_PASSWORD).status_code == 200

    # Two more failures fill the reset bucket; the next attempt is blocked.
    assert login("wrong-password").status_code == 401
    assert login("wrong-password").status_code == 401
    assert login(OWNER_PASSWORD).status_code == 429


def test_closed_or_duplicate_registration_attempts_count(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(
        allow_signup=True,
        max_failures_per_ip=10,
        max_failures_per_email=2,
    )
    assert _register(harness.client).status_code == 201
    anonymous = harness.anonymous()

    assert _register(anonymous).status_code == 409
    assert _register(anonymous).status_code == 409
    blocked = _register(anonymous)

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "尝试次数过多，请稍后再试。"


def test_a_throttled_login_never_reaches_credential_verification(
    make_auth_app: Callable[..., AuthHarness],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = make_auth_app(max_failures_per_ip=10, max_failures_per_email=1)
    assert _register(harness.client).status_code == 201
    anonymous = harness.anonymous()
    assert _wrong_login(anonymous).status_code == 401

    service = harness.container.auth
    assert service is not None

    def _explode(**_kwargs: object) -> None:
        raise AssertionError("a throttled request must not run the password KDF")

    monkeypatch.setattr(service, "login", _explode)
    blocked = anonymous.post(
        "/api/v1/auth/login",
        json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
    )
    assert blocked.status_code == 429


# --------------------------------------------------------------------------
# Cookie expiry / invalidity
# --------------------------------------------------------------------------


def test_invalid_cookie_is_401(make_auth_app: Callable[..., AuthHarness]) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    bogus = harness.anonymous()
    bogus.cookies.set(COOKIE_NAME, "not-a-real-token")
    assert bogus.get("/api/v1/auth/me").status_code == 401
    assert bogus.post("/api/v1/sessions", json={}).status_code == 401


def test_expired_cookie_is_401(make_auth_app: Callable[..., AuthHarness]) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    _expire_all_sessions(harness.url)
    assert harness.client.get("/api/v1/auth/me").status_code == 401
    assert harness.client.post("/api/v1/sessions", json={}).status_code == 401


def test_cookie_flags_follow_the_env(make_auth_app: Callable[..., AuthHarness]) -> None:
    harness = make_auth_app(cookie_secure=True, ttl_s=120)
    response = _register(harness.client)
    assert response.status_code == 201, response.text
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "max-age=120" in cookie


# --------------------------------------------------------------------------
# Diagnostic session gate
# --------------------------------------------------------------------------


def test_gate_blocks_diagnostic_routes_when_auth_is_on(
    make_auth_app: Callable[..., AuthHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_auth_app()
    anonymous = harness.anonymous()

    assert anonymous.post("/api/v1/sessions", json=sample_payload).status_code == 401
    assert anonymous.get("/api/v1/sessions/S_ABC123").status_code == 401
    assert anonymous.get("/api/v1/sessions/S_ABC123/agent").status_code == 401
    assert (
        anonymous.post("/api/v1/sessions/S_ABC123/turns", json={"answer": "x"}).status_code == 401
    )
    assert (
        anonymous.post(
            "/api/v1/sessions/S_ABC123/intake",
            json={"answer": "x"},
        ).status_code
        == 401
    )
    assert anonymous.post("/api/v1/sessions/S_ABC123/exit", json={}).status_code == 401

    # Public on purpose: health, docs/openapi and the account endpoints.
    assert anonymous.get("/api/v1/health").status_code == 200
    assert anonymous.get("/docs").status_code == 200
    assert anonymous.get("/openapi.json").status_code == 200

    # Protected on purpose too: the review queue and the executor are internal
    # resources, so auth on turns an anonymous call into 401 (not the local 200
    # review listing or the executor's 403).
    assert anonymous.get("/api/v1/review/items").status_code == 401
    assert (
        anonymous.post(
            "/api/v1/executions",
            json={"language": "python", "code": "print(1)"},
        ).status_code
        == 401
    )


def test_gate_admits_the_logged_in_owner(
    make_auth_app: Callable[..., AuthHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    created = harness.client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    assert harness.client.get(f"/api/v1/sessions/{session_id}").status_code == 200
    assert harness.client.get("/api/v1/review/items").status_code == 200
    # Executor stays off in this harness: login gating is what is under test.
    executions = harness.client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "print(1)"},
    )
    assert executions.status_code == 403
    assert "SYNAPSE_EXEC=on" in executions.json()["detail"]


def test_gate_admits_the_logged_in_owner_to_executions(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    executor = _PassThroughExecutor()
    harness = make_auth_app(executor=executor)
    anonymous = harness.anonymous()

    # Even with the executor on, auth runs first: no cookie means 401 and the
    # submitted code never reaches the executor.
    assert (
        anonymous.post(
            "/api/v1/executions",
            json={"language": "python", "code": "print('nope')"},
        ).status_code
        == 401
    )
    assert executor.commands == []

    assert _register(harness.client).status_code == 201
    response = harness.client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "print('ok')"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pass"
    assert executor.commands[0].code == "print('ok')"


def test_gate_off_keeps_existing_local_behavior(
    client: TestClient,
    sample_payload: dict[str, object],
) -> None:
    # The conftest fixture deletes SYNAPSE_AUTH, so this is the default install.
    assert client.post("/api/v1/sessions", json=sample_payload).status_code == 201
    assert client.get("/api/v1/health").status_code == 200


def test_auth_endpoints_are_403_when_the_flag_is_off(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/auth/register",
            json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 403
    # Logout stays a no-op so a client can always clean its jar.
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_unmigrated_database_is_503_with_a_migration_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing ``alembic upgrade head`` must not look like a wrong password."""

    url = _sqlite_url(tmp_path / "empty.sqlite3")
    monkeypatch.setenv("SYNAPSE_AUTH", "on")
    monkeypatch.setenv("SYNAPSE_DATABASE_URL", url)
    monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
    app = create_app()
    container = cast(Container, app.state.container)
    try:
        response = _register(TestClient(app))
        assert response.status_code == 503
        assert "alembic upgrade head" in response.json()["detail"]
    finally:
        if container.auth_dispose is not None:
            container.auth_dispose()


# --------------------------------------------------------------------------
# What is actually stored
# --------------------------------------------------------------------------


def test_password_uses_argon2_and_tokens_are_digested(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    token = _cookie_token(harness.client)

    with sqlite3.connect(harness.database) as connection:
        email, password_hash = connection.execute(
            "SELECT email, password_hash FROM users"
        ).fetchone()
        stored_hashes = [
            row[0] for row in connection.execute("SELECT token_hash FROM auth_sessions")
        ]

    assert email == OWNER_EMAIL
    assert password_hash.startswith("$argon2id$")
    assert OWNER_PASSWORD not in password_hash
    assert token not in stored_hashes
    assert hashlib.sha256(token.encode("utf-8")).hexdigest() in stored_hashes


# --------------------------------------------------------------------------
# Redis-backed tokens and the SQL fallback
# --------------------------------------------------------------------------


class FakeRedis:
    """Just the calls the adapter uses; no server, no TTL clock."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self.values[name] = value
        self.expiries[name] = ex
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def getdel(self, name: str) -> str | None:
        value = self.values.pop(name, None)
        self.expiries.pop(name, None)
        return value

    def delete(self, *names: str) -> int:
        for name in names:
            self.values.pop(name, None)
            self.expiries.pop(name, None)
        return len(names)


def test_redis_store_roundtrip_uses_the_configured_ttl() -> None:
    fake = FakeRedis()
    store = RedisSessionTokenStore(fake, ttl_s=120)
    token_hash = "a" * 64
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=120)

    store.issue(
        token_hash=token_hash,
        user_id="U_1",
        family_id="F_1",
        created_at=now,
        expires_at=expires_at,
    )
    key = f"synapse:auth:sess:{token_hash}"
    assert fake.expiries[key] == 120

    # A lookup is read-only: the live key stays and no tombstone appears.
    looked_up = store.lookup(token_hash, now=now)
    assert looked_up.status == "active"
    assert looked_up.user_id == "U_1"
    assert looked_up.family_id == "F_1"
    assert looked_up.expires_at == expires_at
    assert key in fake.values
    assert f"synapse:auth:used:{token_hash}" not in fake.values

    state = store.consume(token_hash, now=now)
    assert state.status == "active"
    assert state.user_id == "U_1"
    assert state.family_id == "F_1"
    assert state.expires_at == expires_at
    # GETDEL removed the live key; a tombstone keeps the replay signal.
    assert key not in fake.values
    assert f"synapse:auth:used:{token_hash}" in fake.values

    # The second consume is "used", not "unknown": that is the theft signal.
    replay = store.consume(token_hash, now=now)
    assert replay.status == "used"
    assert replay.family_id == "F_1"
    assert store.lookup(token_hash, now=now).status == "used"


def test_redis_store_revokes_a_whole_family() -> None:
    fake = FakeRedis()
    store = RedisSessionTokenStore(fake, ttl_s=60)
    now = datetime.now(UTC)
    for index in range(2):
        store.issue(
            token_hash=str(index) * 64,
            user_id="U_1",
            family_id="F_1",
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        )
    store.revoke_family("F_1", now=now)
    assert fake.expiries["synapse:auth:fam:F_1"] == 60
    # Both paths report the revocation while the live key is still present.
    assert store.lookup("0" * 64, now=now).status == "revoked"
    state = store.consume("0" * 64, now=now)
    assert state.status == "revoked"


def test_redis_store_rejects_a_corrupt_value() -> None:
    fake = FakeRedis()
    store = RedisSessionTokenStore(fake, ttl_s=60)
    fake.values[f"synapse:auth:sess:{'b' * 64}"] = "{not json"
    assert store.consume("b" * 64, now=datetime.now(UTC)).status == "unknown"
    assert store.lookup("b" * 64, now=datetime.now(UTC)).status == "unknown"


def test_redis_backed_sessions_skip_the_sql_session_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "redis-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    fake = FakeRedis()
    settings = AuthSettings(
        enabled=True,
        database_url=url,
        redis_url="redis://redis:6379/0",
        session_ttl_s=120,
    )
    runtime = build_auth(settings, redis_client=fake, engine=engine)
    assert runtime is not None
    try:
        issued = runtime.service.register(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        assert issued.token.startswith(LOGIN_TICKET_PREFIX)

        authenticated = runtime.service.authenticate(issued.token)
        assert authenticated is not None
        assert authenticated.user.email == OWNER_EMAIL
        replacement = authenticated.replacement_token
        assert replacement is not None
        assert replacement.startswith(SESSION_PREFIX)
        assert any(key.startswith("synapse:auth:sess:") for key in fake.values)

        factory = build_session_factory(engine)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(AuthSessionRow)) == 0

        # An ordinary session is reused in place: no new token, no Set-Cookie.
        reused = runtime.service.authenticate(replacement)
        assert reused is not None
        assert reused.replacement_token is None

        runtime.service.logout(replacement)
        assert runtime.service.authenticate(replacement) is None
        # Replaying the consumed login ticket is still the theft signal.
        with pytest.raises(SessionReuseDetected):
            runtime.service.authenticate(issued.token)
    finally:
        runtime.close()


def test_sessions_fall_back_to_sql_without_redis(
    tmp_path: Path,
) -> None:
    database = tmp_path / "sql-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    runtime = build_auth(AuthSettings(enabled=True, database_url=url), engine=engine)
    assert runtime is not None
    try:
        issued = runtime.service.register(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        factory = build_session_factory(engine)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(AuthSessionRow)) == 1
        authenticated = runtime.service.authenticate(issued.token)
        assert authenticated is not None
        replacement = authenticated.replacement_token
        assert replacement is not None
        # The exchange leaves the spent ticket row beside the ordinary session,
        # and both belong to the same token family.
        with factory() as session:
            rows = list(session.scalars(select(AuthSessionRow)))
        assert len(rows) == 2
        assert rows[0].family_id == rows[1].family_id
        assert runtime.service.authenticate(replacement) is not None
    finally:
        runtime.close()


def test_build_auth_is_inert_when_disabled(tmp_path: Path) -> None:
    assert build_auth(AuthSettings(enabled=False)) is None
    # No engine was created, so no file appeared.
    assert not (tmp_path / "unused.sqlite3").exists()


def test_service_rejects_expired_tokens_with_an_injected_clock(tmp_path: Path) -> None:
    database = tmp_path / "clock-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    factory = build_session_factory(engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_values = [now]

    service = AuthService(
        users=SqlUserStore(factory),
        tokens=SqlSessionTokenStore(factory),
        hasher=Argon2PasswordHasher(),
        session_ttl_s=60,
        clock=lambda: clock_values[0],
    )
    try:
        issued = service.register(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        exchanged = service.authenticate(issued.token)
        assert exchanged is not None
        ordinary = exchanged.replacement_token
        assert ordinary is not None

        issued = service.login(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        clock_values[0] = now + timedelta(seconds=61)
        # The ticket row is still unconsumed, but the hard expiry wins.
        assert service.authenticate(issued.token) is None
        # The ordinary session issued at ``now`` has expired too.
        assert service.authenticate(ordinary) is None
    finally:
        engine.dispose()


# --------------------------------------------------------------------------
# Login tickets vs ordinary sessions: exchange, reuse and expiry
# --------------------------------------------------------------------------


def test_login_ticket_is_exchanged_once_for_an_ordinary_session(
    make_auth_app: Callable[..., AuthHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    ticket = _cookie_token(harness.client)
    assert ticket.startswith(LOGIN_TICKET_PREFIX)

    created = harness.client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    ordinary = _cookie_token(harness.client)
    assert ordinary.startswith(SESSION_PREFIX)
    assert ordinary != ticket
    # The exchange is the only place a protected request sets the cookie.
    assert len(created.headers.get_list("set-cookie")) == 1

    session_id = created.json()["session_id"]
    second = harness.client.get(f"/api/v1/sessions/{session_id}")
    assert second.status_code == 200, second.text
    assert "set-cookie" not in second.headers
    assert _cookie_token(harness.client) == ordinary

    # The same ordinary session also covers the other protected prefix.
    settings = harness.client.get("/api/v1/settings/model")
    assert settings.status_code == 200, settings.text
    assert "set-cookie" not in settings.headers
    assert _cookie_token(harness.client) == ordinary


def test_ordinary_session_is_reused_until_logout(
    make_auth_app: Callable[..., AuthHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    created = harness.client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    ordinary = _cookie_token(harness.client)

    for _ in range(3):
        response = harness.client.get(f"/api/v1/sessions/{session_id}")
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert _cookie_token(harness.client) == ordinary

    assert harness.client.post("/api/v1/auth/logout").status_code == 200
    assert harness.client.get(f"/api/v1/sessions/{session_id}").status_code == 401
    assert harness.client.get("/api/v1/auth/me").status_code == 401


def test_me_exchanges_a_login_ticket_but_not_an_ordinary_session(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    ticket = _cookie_token(harness.client)

    first = harness.client.get("/api/v1/auth/me")
    assert first.status_code == 200
    ordinary = _cookie_token(harness.client)
    assert ordinary.startswith(SESSION_PREFIX)
    assert ordinary != ticket
    assert len(first.headers.get_list("set-cookie")) == 1

    second = harness.client.get("/api/v1/auth/me")
    assert second.status_code == 200
    assert "set-cookie" not in second.headers
    assert _cookie_token(harness.client) == ordinary


def test_replaying_a_consumed_login_ticket_revokes_the_family(
    make_auth_app: Callable[..., AuthHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_auth_app(allow_signup=True)
    assert _register(harness.client).status_code == 201
    ticket = _cookie_token(harness.client)
    created = harness.client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    ordinary = _cookie_token(harness.client)
    assert ordinary != ticket

    replay = harness.anonymous()
    replay.cookies.set(COOKIE_NAME, ticket)
    reused = replay.get(f"/api/v1/sessions/{session_id}")

    assert reused.status_code == 401
    assert "会话被复用" in reused.json()["detail"]
    assert reused.headers.get("www-authenticate") == "Cookie"
    cleared = reused.headers["set-cookie"].lower()
    assert f"{COOKIE_NAME}=" in cleared
    assert "max-age=0" in cleared

    # The alarm revoked the whole family, including the current ordinary cookie.
    assert harness.client.get(f"/api/v1/sessions/{session_id}").status_code == 401
    assert harness.client.get("/api/v1/auth/me").status_code == 401


def test_me_replay_of_a_consumed_login_ticket_is_also_theft(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    ticket = _cookie_token(harness.client)

    assert harness.client.get("/api/v1/auth/me").status_code == 200
    ordinary = _cookie_token(harness.client)
    assert ordinary != ticket

    replay = harness.anonymous()
    replay.cookies.set(COOKIE_NAME, ticket)
    reused = replay.get("/api/v1/auth/me")
    assert reused.status_code == 401
    assert "会话被复用" in reused.json()["detail"]

    # Current value is now revoked as well.
    assert harness.client.get("/api/v1/auth/me").status_code == 401


def test_reusing_an_ordinary_session_is_not_treated_as_theft(
    make_auth_app: Callable[..., AuthHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    created = harness.client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    ordinary = _cookie_token(harness.client)

    clone = harness.anonymous()
    clone.cookies.set(COOKIE_NAME, ordinary)
    copied = clone.get("/api/v1/auth/me")
    assert copied.status_code == 200
    assert "set-cookie" not in copied.headers

    # Neither copy is accused of theft: the family is still alive.
    assert harness.client.get(f"/api/v1/sessions/{session_id}").status_code == 200
    assert clone.get(f"/api/v1/sessions/{session_id}").status_code == 200


def test_logout_revokes_every_token_in_the_family(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    ticket = _cookie_token(harness.client)
    assert harness.client.get("/api/v1/auth/me").status_code == 200
    ordinary = _cookie_token(harness.client)
    assert ordinary != ticket

    logout = harness.client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    # Logout itself is not a theft alarm even when the ticket was already spent.
    assert "会话被复用" not in logout.text

    # Replaying the *consumed* ticket is still theft, even after logout.
    ticket_replay = harness.anonymous()
    ticket_replay.cookies.set(COOKIE_NAME, ticket)
    reused = ticket_replay.get("/api/v1/auth/me")
    assert reused.status_code == 401
    assert "会话被复用" in reused.json()["detail"]

    # The ordinary session was revoked, not consumed, so it is a plain 401.
    ordinary_replay = harness.anonymous()
    ordinary_replay.cookies.set(COOKIE_NAME, ordinary)
    revoked = ordinary_replay.get("/api/v1/auth/me")
    assert revoked.status_code == 401
    assert "会话被复用" not in revoked.json()["detail"]


def test_two_consumes_cannot_both_succeed(tmp_path: Path) -> None:
    """The store, not the caller, decides who wins a race for one digest."""

    database = tmp_path / "race-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    try:
        store = SqlSessionTokenStore(build_session_factory(engine))
        now = datetime.now(UTC)
        token_hash = "c" * 64
        store.issue(
            token_hash=token_hash,
            user_id="U_1",
            family_id="F_1",
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        )

        winner = store.consume(token_hash, now=now)
        loser = store.consume(token_hash, now=now)

        assert winner.status == "active"
        assert loser.status == "used"
        assert loser.family_id == "F_1"
    finally:
        engine.dispose()


def test_a_route_error_after_the_exchange_leaves_a_spent_ticket(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    """No response object means no replacement cookie; the next call is reuse.

    This pins the documented edge rather than redesigning ticket semantics: the
    ticket is consumed before dispatch, so an unhandled route error cannot put
    the ordinary session on the 500 response. The browser keeps the spent value
    and the next protected request trips the family revocation.
    """

    harness = make_auth_app()
    assert _register(harness.client).status_code == 201
    ticket = _cookie_token(harness.client)

    @harness.app.get("/api/v1/sessions/__boom__/explode")
    def explode() -> None:
        raise RuntimeError("boom")

    failing = TestClient(harness.app, raise_server_exceptions=False)
    failing.cookies.set(COOKIE_NAME, ticket)
    response = failing.get("/api/v1/sessions/__boom__/explode")

    assert response.status_code == 500
    assert "set-cookie" not in response.headers

    replay = harness.anonymous()
    replay.cookies.set(COOKIE_NAME, ticket)
    reused = replay.get("/api/v1/sessions/S_missing")
    assert reused.status_code == 401
    assert "会话被复用" in reused.json()["detail"]


def test_sql_lookup_is_read_only_and_reports_state(tmp_path: Path) -> None:
    database = tmp_path / "lookup-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    factory = build_session_factory(engine)
    try:
        store = SqlSessionTokenStore(factory)
        now = datetime.now(UTC)
        token_hash = "d" * 64
        other_hash = "e" * 64
        store.issue(
            token_hash=token_hash,
            user_id="U_1",
            family_id="F_1",
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        )

        first = store.lookup(token_hash, now=now)
        assert first.status == "active"
        assert first.user_id == "U_1"
        assert first.family_id == "F_1"
        assert first.expires_at == now + timedelta(seconds=60)
        # A lookup does not spend the digest.
        assert store.lookup(token_hash, now=now).status == "active"

        # Expiry is reported, not enforced, by the store; the service decides.
        with factory() as session:
            row = session.scalar(
                select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
            )
            assert row is not None
            row.expires_at = now - timedelta(seconds=1)
            session.commit()
        expired = store.lookup(token_hash, now=now)
        assert expired.status == "active"
        assert expired.expires_at is not None
        assert expired.expires_at < now

        # Only consume spends it; a later lookup sees the used marker.
        assert store.consume(token_hash, now=now).status == "active"
        assert store.lookup(token_hash, now=now).status == "used"

        # Revoking one family leaves another family's lookup untouched.
        store.issue(
            token_hash=other_hash,
            user_id="U_2",
            family_id="F_2",
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        )
        store.revoke_family("F_2", now=now)
        assert store.lookup(other_hash, now=now).status == "revoked"
        assert store.lookup(token_hash, now=now).status == "used"
        assert store.lookup("f" * 64, now=now).status == "unknown"
    finally:
        engine.dispose()


def test_legacy_unprefixed_tokens_are_ordinary_sessions(tmp_path: Path) -> None:
    database = tmp_path / "legacy-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    factory = build_session_factory(engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tokens = SqlSessionTokenStore(factory)
    service = AuthService(
        users=SqlUserStore(factory),
        tokens=tokens,
        hasher=Argon2PasswordHasher(),
        session_ttl_s=60,
        clock=lambda: now,
    )
    try:
        issued = service.register(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        legacy = "legacy-" + secrets.token_urlsafe(32)
        assert not legacy.startswith(LOGIN_TICKET_PREFIX)
        assert not legacy.startswith(SESSION_PREFIX)
        legacy_hash = hash_session_token(legacy)
        tokens.issue(
            token_hash=legacy_hash,
            user_id=issued.user.id,
            family_id=issued.family_id,
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        )

        authenticated = service.authenticate(legacy)
        assert authenticated is not None
        assert authenticated.user.id == issued.user.id
        assert authenticated.replacement_token is None
        # Unprefixed means ordinary: it is reusable, not a one-time ticket.
        assert service.authenticate(legacy) is not None
        with factory() as session:
            row = session.scalar(
                select(AuthSessionRow).where(AuthSessionRow.token_hash == legacy_hash)
            )
            assert row is not None
            assert row.used_at is None
    finally:
        engine.dispose()


def test_legacy_unprefixed_tokens_are_ordinary_on_redis(tmp_path: Path) -> None:
    database = tmp_path / "legacy-redis-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    factory = build_session_factory(engine)
    fake = FakeRedis()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tokens = RedisSessionTokenStore(fake, ttl_s=60)
    service = AuthService(
        users=SqlUserStore(factory),
        tokens=tokens,
        hasher=Argon2PasswordHasher(),
        session_ttl_s=60,
        clock=lambda: now,
    )
    try:
        issued = service.register(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        legacy = "legacy-" + secrets.token_urlsafe(32)
        legacy_hash = hash_session_token(legacy)
        tokens.issue(
            token_hash=legacy_hash,
            user_id=issued.user.id,
            family_id=issued.family_id,
            created_at=now,
            expires_at=now + timedelta(seconds=60),
        )

        authenticated = service.authenticate(legacy)
        assert authenticated is not None
        assert authenticated.replacement_token is None
        assert service.authenticate(legacy) is not None
        assert f"synapse:auth:used:{legacy_hash}" not in fake.values
    finally:
        engine.dispose()


def test_redis_backed_ordinary_sessions_expire(tmp_path: Path) -> None:
    database = tmp_path / "redis-expiry-auth.sqlite3"
    url = _sqlite_url(database)
    _upgrade(url)
    engine = create_auth_engine(url)
    factory = build_session_factory(engine)
    fake = FakeRedis()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock_values = [now]
    service = AuthService(
        users=SqlUserStore(factory),
        tokens=RedisSessionTokenStore(fake, ttl_s=60),
        hasher=Argon2PasswordHasher(),
        session_ttl_s=60,
        clock=lambda: clock_values[0],
    )
    try:
        issued = service.register(email=OWNER_EMAIL, password=OWNER_PASSWORD)
        exchanged = service.authenticate(issued.token)
        assert exchanged is not None
        ordinary = exchanged.replacement_token
        assert ordinary is not None
        assert service.authenticate(ordinary) is not None

        clock_values[0] = now + timedelta(seconds=61)
        # The fake Redis does not sweep keys; the service's hard expiry wins.
        assert service.authenticate(ordinary) is None
    finally:
        engine.dispose()


def test_multi_user_signup_keeps_families_independent(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app(allow_signup=True)
    assert _register(harness.client, email="a@example.com").status_code == 201
    a_ticket = _cookie_token(harness.client)
    a_identity = harness.client.get("/api/v1/auth/me").json()

    second = harness.anonymous()
    assert _register(second, email="b@example.com").status_code == 201
    b_identity = second.get("/api/v1/auth/me").json()

    assert a_identity["id"] != b_identity["id"]

    # A replay alarm on A's chain must not touch B's session.
    replay = harness.anonymous()
    replay.cookies.set(COOKIE_NAME, a_ticket)
    reused = replay.get("/api/v1/auth/me")
    assert reused.status_code == 401
    assert "会话被复用" in reused.json()["detail"]
    assert harness.client.get("/api/v1/auth/me").status_code == 401
    assert second.get("/api/v1/auth/me").status_code == 200


# --------------------------------------------------------------------------
# The gate sits inside CORS, so a browser can read its 401
# --------------------------------------------------------------------------


def test_a_401_still_carries_cors_headers(
    make_auth_app: Callable[..., AuthHarness],
) -> None:
    harness = make_auth_app()
    response = harness.anonymous().get(
        "/api/v1/sessions/S_missing",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 401
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


# --------------------------------------------------------------------------
# Alembic: SQLite for real, PostgreSQL compiled offline
# --------------------------------------------------------------------------


def test_migration_upgrade_downgrade_and_model_parity(tmp_path: Path) -> None:
    url = _sqlite_url(tmp_path / "migrate.sqlite3")
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "head")
    engine = create_auth_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"users", "auth_sessions", "user_model_credentials"} <= tables
        assert UserModelCredentialRow.__tablename__ == "user_model_credentials"
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_auth_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "users" not in tables
        assert "auth_sessions" not in tables
        assert "user_model_credentials" not in tables
    finally:
        engine.dispose()


def test_migration_compiles_for_postgres_offline() -> None:
    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+psycopg://synapse:synapse@postgres:5432/synapse",
    )
    config.output_buffer = buffer

    command.upgrade(config, "head", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE users" in sql
    assert "CREATE TABLE auth_sessions" in sql
    assert "CREATE TABLE user_model_credentials" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in sql
    assert "CREATE UNIQUE INDEX ix_users_email ON users (email)" in sql
    assert "ALTER TABLE auth_sessions ADD COLUMN family_id VARCHAR(40)" in sql
    assert "ALTER TABLE auth_sessions ADD COLUMN used_at TIMESTAMP WITH TIME ZONE" in sql
    assert "ALTER TABLE auth_sessions ALTER COLUMN family_id SET NOT NULL" in sql
    assert "CREATE INDEX ix_auth_sessions_family_id ON auth_sessions (family_id)" in sql


def test_postgres_spelling_is_normalized() -> None:
    from synapse.infrastructure.auth.db import normalize_database_url

    assert (
        normalize_database_url("postgres://synapse:synapse@postgres:5432/synapse")
        == "postgresql+psycopg://synapse:synapse@postgres:5432/synapse"
    )
    assert (
        normalize_database_url("postgresql://synapse:synapse@postgres:5432/synapse")
        == "postgresql+psycopg://synapse:synapse@postgres:5432/synapse"
    )
    assert (
        normalize_database_url("sqlite+pysqlite:///var/auth.sqlite3")
        == "sqlite+pysqlite:///var/auth.sqlite3"
    )
