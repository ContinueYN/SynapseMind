"""Focused tests for the self-hosted account layer and its persistence.

Deliberately small and dependency-free: SQLite on a temp file, a migrated schema
via the checked-in Alembic config, and a dict-backed fake Redis. No network, no
clock sleeping (expiry is forced through the database or an injected clock).
"""

from __future__ import annotations

import hashlib
import io
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
from synapse.api.deps import Container
from synapse.api.main import create_app
from synapse.application.auth import AuthService
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
    DEFAULT_SESSION_TTL_S,
    AuthSettings,
)
from synapse.infrastructure.auth.stores import (
    RedisSessionTokenStore,
    SqlSessionTokenStore,
    SqlUserStore,
)

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
    ) -> AuthHarness:
        database = tmp_path / f"auth-{next(counter)}.sqlite3"
        url = _sqlite_url(database)
        monkeypatch.setenv("SYNAPSE_AUTH", "on")
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", url)
        monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", str(ttl_s))
        monkeypatch.setenv("SYNAPSE_AUTH_ALLOW_SIGNUP", "on" if allow_signup else "off")
        monkeypatch.setenv("SYNAPSE_COOKIE_SECURE", "on" if cookie_secure else "off")
        if redis_url is None:
            monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
        else:
            monkeypatch.setenv("SYNAPSE_REDIS_URL", redis_url)
        _upgrade(url)
        app = create_app()
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
    settings = AuthSettings.from_env()
    assert settings.enabled is True
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.allow_signup is True
    assert settings.cookie_secure is True
    assert settings.session_ttl_s == 900


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

    # Gating only covers sessions in this slice: the local review queue and
    # executors keep their own flags/behaviour.
    assert anonymous.get("/api/v1/review/items").status_code == 200


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
    """Just the four calls the adapter uses; no server, no TTL clock."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}

    def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self.values[name] = value
        self.expiries[name] = ex
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def delete(self, *names: str) -> int:
        for name in names:
            self.values.pop(name, None)
            self.expiries.pop(name, None)
        return len(names)


def test_redis_store_roundtrip_uses_the_configured_ttl() -> None:
    fake = FakeRedis()
    store = RedisSessionTokenStore(fake, ttl_s=120)
    token_hash = "a" * 64
    expires_at = datetime.now(UTC) + timedelta(seconds=120)

    store.create(token_hash=token_hash, user_id="U_1", expires_at=expires_at)
    key = f"synapse:auth:sess:{token_hash}"
    assert fake.expiries[key] == 120

    resolved = store.resolve(token_hash)
    assert resolved is not None
    assert resolved.user_id == "U_1"
    assert resolved.expires_at == expires_at

    store.revoke(token_hash)
    assert store.resolve(token_hash) is None


def test_redis_store_rejects_a_corrupt_value() -> None:
    fake = FakeRedis()
    store = RedisSessionTokenStore(fake, ttl_s=60)
    fake.values[f"synapse:auth:sess:{'b' * 64}"] = "{not json"
    assert store.resolve("b" * 64) is None


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
        principal = runtime.service.principal(issued.token)
        assert principal is not None
        assert principal.email == OWNER_EMAIL
        assert any(key.startswith("synapse:auth:sess:") for key in fake.values)

        factory = build_session_factory(engine)
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(AuthSessionRow)) == 0

        runtime.service.logout(issued.token)
        assert runtime.service.principal(issued.token) is None
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
        assert runtime.service.principal(issued.token) is not None
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
        assert service.principal(issued.token) is not None
        clock_values[0] = now + timedelta(seconds=61)
        # The row is still unrevoked, but the hard expiry wins.
        assert service.principal(issued.token) is None
    finally:
        engine.dispose()


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
        assert {"users", "auth_sessions", "alembic_version"} <= tables
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_auth_engine(url)
    try:
        assert "users" not in inspect(engine).get_table_names()
        assert "auth_sessions" not in inspect(engine).get_table_names()
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
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in sql
    assert "CREATE UNIQUE INDEX ix_users_email ON users (email)" in sql


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
