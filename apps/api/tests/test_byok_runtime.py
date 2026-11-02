"""Per-user model runtime: one credential-aware client, resolved per request.

``SYNAPSE_BYOK=on`` alone does not enable anything: the mode must ask for the
model. What BYOK changes is *which key* a call uses —

* the calling user's saved key, when the request is bound to that user;
* otherwise the server-wide key;
* otherwise no call at all (``LLMCallFailed``), so the rule fallback runs and a
  request never 500s because a key is missing.

A public/unauthenticated request is never bound to a user, which is what keeps a
logged-in user's key off those paths.

The fake provider records the ``Authorization`` header of every call, so "the
same client used the right key in the right request" is asserted end to end
(middleware -> ContextVar -> threadpool -> client), not inferred from internals.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import cast

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alembic import command
from synapse.api.deps import Container, build_container
from synapse.api.main import create_app
from synapse.application.credentials.service import (
    CredentialDecryptionError,
    CredentialInput,
    CredentialService,
    SecretCredential,
)
from synapse.application.shared.context import bind_owner, reset_owner
from synapse.application.shared.llm import LLMCallFailed, LLMRequest
from synapse.infrastructure.llm.client import CredentialAwareLLMClient
from synapse.infrastructure.llm.settings import LLMMode, LLMSettings

APPS_API = Path(__file__).resolve().parents[1]
ALEMBIC_INI = APPS_API / "alembic.ini"
PASSWORD = "correct horse battery"
MASTER_KEY = "runtime-master-key"
KEY_A = "sk-alice-aaaaaaaaaaaa"
KEY_B = "sk-bob-bbbbbbbbbbbbbb"
SERVER_KEY = "sk-server-cccccccccccc"


def _upgrade(url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


class _NullAuditor:
    def record(self, entry: object) -> None:
        del entry


class _Provider:
    """Record every model call and answer with an unparsable JSON object."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "fake-model",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    @property
    def authorizations(self) -> list[str]:
        return [request.headers.get("authorization", "") for request in self.requests]


@dataclass(frozen=True, slots=True)
class Runtime:
    app: FastAPI
    container: Container
    settings: LLMSettings
    provider: _Provider
    database: Path

    @property
    def credentials(self) -> CredentialService:
        assert self.container.credentials is not None
        return self.container.credentials

    def client(self) -> CredentialAwareLLMClient:
        return CredentialAwareLLMClient(
            self.settings,
            credentials=self.container.credentials,
            transport_factory=lambda: httpx.MockTransport(self.provider),
        )


@pytest.fixture()
def make_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., Runtime]]:
    containers: list[Container] = []
    counter = count()

    def make(
        *,
        mode: LLMMode = "on",
        byok: bool = True,
        server_key: str | None = None,
        master_key: str | None = MASTER_KEY,
        auth: bool = True,
    ) -> Runtime:
        database = tmp_path / f"runtime-{next(counter)}.sqlite3"
        url = f"sqlite+pysqlite:///{database.as_posix()}"
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", url)
        monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", "3600")
        monkeypatch.setenv("SYNAPSE_AUTH_ALLOW_SIGNUP", "on")
        monkeypatch.setenv("SYNAPSE_COOKIE_SECURE", "off")
        monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
        if auth:
            monkeypatch.setenv("SYNAPSE_AUTH", "on")
            _upgrade(url)
        else:
            monkeypatch.delenv("SYNAPSE_AUTH", raising=False)
        if master_key is None:
            monkeypatch.delenv("SYNAPSE_CREDENTIAL_KEY", raising=False)
        else:
            monkeypatch.setenv("SYNAPSE_CREDENTIAL_KEY", master_key)
        provider = _Provider()
        settings = LLMSettings(
            mode=mode,
            provider="deepseek",
            model="server-model",
            base_url="https://server.example/v1",
            api_key=server_key,
            byok=byok,
            timeout_s=2.0,
        )
        container = build_container(
            settings,
            auditor=_NullAuditor(),
            llm_transport_factory=lambda: httpx.MockTransport(provider),
        )
        containers.append(container)
        return Runtime(
            app=create_app(container),
            container=container,
            settings=settings,
            provider=provider,
            database=database,
        )

    try:
        yield make
    finally:
        for container in containers:
            if container.auth_dispose is not None:
                container.auth_dispose()


@contextmanager
def _bound(user_id: str | None) -> Iterator[None]:
    token = bind_owner(user_id)
    try:
        yield
    finally:
        reset_owner(token)


def _request() -> LLMRequest:
    return LLMRequest(
        purpose="coach",
        system="system",
        user="user",
        schema_name="coach-v1",
    )


def _user(app: FastAPI, email: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return client


def _me(client: TestClient) -> str:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200, response.text
    user_id = response.json()["id"]
    assert isinstance(user_id, str)
    return user_id


# --------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------


def test_byok_counts_as_a_reason_to_build_the_model_path() -> None:
    assert LLMSettings(mode="off", byok=True).llm_enabled is False
    assert LLMSettings(mode="on", byok=False).llm_enabled is False
    assert LLMSettings(mode="on", byok=True).llm_enabled is True
    assert LLMSettings(mode="on", api_key="k").llm_enabled is True


# --------------------------------------------------------------------------
# The client: which key does one call use?
# --------------------------------------------------------------------------


def test_bound_user_key_wins_and_carries_its_own_base_url(
    make_runtime: Callable[..., Runtime],
) -> None:
    runtime = make_runtime(server_key=SERVER_KEY)
    runtime.credentials.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )
    client = runtime.client()

    with _bound("U_A"):
        client.complete(_request(), timeout_s=1.0)

    request = runtime.provider.requests[-1]
    assert request.headers["authorization"] == f"Bearer {KEY_A}"
    assert request.url.host == "api.deepseek.com"
    body = request.read().decode("utf-8")
    assert "deepseek-chat" in body


def test_two_users_never_share_a_key(make_runtime: Callable[..., Runtime]) -> None:
    runtime = make_runtime(server_key=SERVER_KEY)
    runtime.credentials.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )
    runtime.credentials.save(
        "U_B",
        CredentialInput(provider="openai", base_url="", model="", api_key=KEY_B),
    )
    client = runtime.client()

    with _bound("U_A"):
        client.complete(_request(), timeout_s=1.0)
    with _bound("U_B"):
        client.complete(_request(), timeout_s=1.0)
    with _bound("U_A"):
        client.complete(_request(), timeout_s=1.0)

    assert runtime.provider.authorizations == [
        f"Bearer {KEY_A}",
        f"Bearer {KEY_B}",
        f"Bearer {KEY_A}",
    ]
    hosts = [request.url.host for request in runtime.provider.requests]
    assert hosts == ["api.deepseek.com", "api.openai.com", "api.deepseek.com"]


def test_a_user_without_a_key_falls_back_to_the_server_key(
    make_runtime: Callable[..., Runtime],
) -> None:
    runtime = make_runtime(server_key=SERVER_KEY)
    client = runtime.client()

    with _bound("U_NOBODY"):
        client.complete(_request(), timeout_s=1.0)

    request = runtime.provider.requests[-1]
    assert request.headers["authorization"] == f"Bearer {SERVER_KEY}"
    assert request.url.host == "server.example"


def test_no_owner_means_no_user_key_even_if_one_is_saved(
    make_runtime: Callable[..., Runtime],
) -> None:
    """A public/unauthenticated request must never borrow a user's key."""

    runtime = make_runtime(server_key=SERVER_KEY)
    runtime.credentials.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )
    client = runtime.client()

    # No binding at all (a public path) and an explicit None are the same thing.
    client.complete(_request(), timeout_s=1.0)
    with _bound(None):
        client.complete(_request(), timeout_s=1.0)

    assert runtime.provider.authorizations == [
        f"Bearer {SERVER_KEY}",
        f"Bearer {SERVER_KEY}",
    ]


def test_byok_off_keeps_using_the_server_key(
    make_runtime: Callable[..., Runtime],
) -> None:
    runtime = make_runtime(server_key=SERVER_KEY, byok=False)
    runtime.credentials.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )
    client = runtime.client()

    with _bound("U_A"):
        client.complete(_request(), timeout_s=1.0)

    assert runtime.provider.authorizations == [f"Bearer {SERVER_KEY}"]


def test_no_key_anywhere_fails_softly_instead_of_crashing(
    make_runtime: Callable[..., Runtime],
) -> None:
    runtime = make_runtime(server_key=None)
    client = runtime.client()

    with _bound("U_NOBODY"), pytest.raises(LLMCallFailed):
        client.complete(_request(), timeout_s=1.0)
    assert runtime.provider.requests == []


def test_an_undecryptable_saved_key_falls_back_to_the_server_key(
    make_runtime: Callable[..., Runtime],
) -> None:
    runtime = make_runtime(server_key=SERVER_KEY)
    runtime.credentials.save(
        "U_A",
        CredentialInput(provider="deepseek", base_url="", model="", api_key=KEY_A),
    )
    # Simulate "the operator changed SYNAPSE_CREDENTIAL_KEY after the save": the
    # row is there but cannot be opened. That must degrade to the server key,
    # never fail the diagnosis.
    client = CredentialAwareLLMClient(
        runtime.settings,
        credentials=cast(CredentialService, _Undecryptable()),
        transport_factory=lambda: httpx.MockTransport(runtime.provider),
    )

    with _bound("U_A"):
        client.complete(_request(), timeout_s=1.0)

    assert runtime.provider.authorizations == [f"Bearer {SERVER_KEY}"]


class _Undecryptable:
    """A credential service whose saved row cannot be opened."""

    def resolve(self, user_id: str) -> SecretCredential | None:
        del user_id
        raise CredentialDecryptionError("cannot decrypt")


# --------------------------------------------------------------------------
# End to end: the request's own key, through the gate and the threadpool
# --------------------------------------------------------------------------


def _start(client: TestClient, sample_payload: dict[str, object]) -> str:
    response = client.post("/api/v1/sessions", json=sample_payload)
    assert response.status_code == 201, response.text
    session_id = response.json()["session_id"]
    assert isinstance(session_id, str)
    return session_id


def _save_key(client: TestClient, key: str, provider: str = "deepseek") -> None:
    response = client.put(
        "/api/v1/settings/model",
        json={"provider": provider, "base_url": "", "model": "", "api_key": key},
    )
    assert response.status_code == 200, response.text


def test_each_request_uses_the_logged_in_users_key(
    make_runtime: Callable[..., Runtime],
    sample_payload: dict[str, object],
) -> None:
    runtime = make_runtime(server_key=None)
    alice = _user(runtime.app, "alice@example.com")
    _save_key(alice, KEY_A)
    session_id = _start(alice, sample_payload)

    coach = alice.post(f"/api/v1/sessions/{session_id}/coach", json={"focus": "where_wrong"})
    assert coach.status_code == 200, coach.text
    assert runtime.provider.requests, "the coach/model path must have called the provider"
    assert set(runtime.provider.authorizations) == {f"Bearer {KEY_A}"}

    bob = _user(runtime.app, "bob@example.com")
    _save_key(bob, KEY_B, provider="openai")
    bob_session = _start(bob, sample_payload)
    bob.post(f"/api/v1/sessions/{bob_session}/coach", json={"focus": "where_wrong"})

    # Alice's earlier calls kept her key; every later call uses Bob's.
    seen = runtime.provider.authorizations
    first_bob = next(index for index, value in enumerate(seen) if value == f"Bearer {KEY_B}")
    assert seen[:first_bob] == [f"Bearer {KEY_A}"] * first_bob
    assert seen[first_bob:] == [f"Bearer {KEY_B}"] * (len(seen) - first_bob)
    assert all(authorization != f"Bearer {SERVER_KEY}" for authorization in seen)


def test_a_request_without_a_saved_key_never_calls_the_provider(
    make_runtime: Callable[..., Runtime],
    sample_payload: dict[str, object],
) -> None:
    """No user key, no server key: the rule path answers, the provider is silent."""

    runtime = make_runtime(server_key=None)
    alice = _user(runtime.app, "alice@example.com")
    session_id = _start(alice, sample_payload)

    coach = alice.post(f"/api/v1/sessions/{session_id}/coach", json={"focus": "where_wrong"})
    assert coach.status_code == 200
    assert coach.json()["mode"] == "rules"
    assert runtime.provider.requests == []


def test_a_public_route_never_uses_a_logged_in_users_key(
    make_runtime: Callable[..., Runtime],
    sample_payload: dict[str, object],
) -> None:
    runtime = make_runtime(server_key=None)
    alice = _user(runtime.app, "alice@example.com")
    _save_key(alice, KEY_A)

    # ``/knowledge/search`` is public and does not call the model, but the
    # canary probe on the next public-safe path must still see no owner. The
    # session route is gated, so an anonymous call is 401 and never reaches the
    # provider.
    anonymous = TestClient(runtime.app)
    assert anonymous.post("/api/v1/sessions", json=sample_payload).status_code == 401
    assert runtime.provider.requests == []

    # And the settings view itself is not a model call.
    assert alice.get("/api/v1/settings/model").status_code == 200
    assert runtime.provider.requests == []
