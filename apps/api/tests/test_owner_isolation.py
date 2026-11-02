"""Owner isolation: one workspace per account, 404 for everybody else.

The service binds an owner per request and every load goes through one check.
These tests drive the real app (gate, login-ticket exchange, SQLite
persistence) so a regression in the wiring, not only in the domain object, is
caught.

A session that has no owner (a row written before ownership existed, or one
created with auth off) is deliberately **not** shared: under auth it is visible
to nobody, which is the safe direction for a leak.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import cast

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alembic import command
from synapse.api.deps import Container
from synapse.api.main import create_app
from synapse.application.context import current_owner_id
from synapse.application.service import SessionNotFound

APPS_API = Path(__file__).resolve().parents[1]
ALEMBIC_INI = APPS_API / "alembic.ini"
PASSWORD = "correct horse battery"


def _upgrade(url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@dataclass(frozen=True, slots=True)
class IsolatedHarness:
    app: FastAPI
    auth_database: Path
    session_database: Path

    @property
    def container(self) -> Container:
        return cast(Container, self.app.state.container)


@pytest.fixture()
def make_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., IsolatedHarness]]:
    """Build gated apps; named files let one test restart over the same state."""

    containers: list[Container] = []
    counter = count()

    def make(
        *,
        auth: bool = True,
        allow_signup: bool = True,
        auth_database: Path | None = None,
        session_database: Path | None = None,
    ) -> IsolatedHarness:
        identity = auth_database or tmp_path / f"identity-{next(counter)}.sqlite3"
        state = session_database or tmp_path / f"sessions-{next(counter)}.sqlite3"
        url = f"sqlite+pysqlite:///{identity.as_posix()}"
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", url)
        monkeypatch.setenv("SYNAPSE_SESSION_DB", str(state))
        monkeypatch.setenv("SYNAPSE_AUTH_SESSION_TTL_S", "3600")
        monkeypatch.setenv("SYNAPSE_AUTH_ALLOW_SIGNUP", "on" if allow_signup else "off")
        monkeypatch.setenv("SYNAPSE_COOKIE_SECURE", "off")
        monkeypatch.delenv("SYNAPSE_REDIS_URL", raising=False)
        monkeypatch.delenv("SYNAPSE_CREDENTIAL_KEY", raising=False)
        if auth:
            monkeypatch.setenv("SYNAPSE_AUTH", "on")
            _upgrade(url)
        else:
            monkeypatch.delenv("SYNAPSE_AUTH", raising=False)
        app = create_app()
        containers.append(cast(Container, app.state.container))
        return IsolatedHarness(app=app, auth_database=identity, session_database=state)

    try:
        yield make
    finally:
        for container in containers:
            if container.auth_dispose is not None:
                container.auth_dispose()


def _user(app: FastAPI, email: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return client


def _start(client: TestClient, sample_payload: dict[str, object]) -> str:
    created = client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    assert isinstance(session_id, str)
    return session_id


def test_another_users_session_is_404_on_every_entry_point(
    make_isolated: Callable[..., IsolatedHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_isolated()
    alice = _user(harness.app, "alice@example.com")
    bob = _user(harness.app, "bob@example.com")
    session_id = _start(alice, sample_payload)

    # Bob cannot read, advance, coach, probe, verify, disagree or close it.
    assert bob.get(f"/api/v1/sessions/{session_id}").status_code == 404
    assert (
        bob.post(f"/api/v1/sessions/{session_id}/turns", json={"answer": "换一个"}).status_code
        == 404
    )
    assert (
        bob.post(
            f"/api/v1/sessions/{session_id}/coach",
            json={"focus": "where_wrong"},
        ).status_code
        == 404
    )
    assert bob.get(f"/api/v1/sessions/{session_id}/agent").status_code == 404
    assert bob.post(f"/api/v1/sessions/{session_id}/steps", json={"text": "a=1"}).status_code == 404
    assert (
        bob.post(
            f"/api/v1/sessions/{session_id}/intake",
            json={"answer": "补充"},
        ).status_code
        == 404
    )
    assert (
        bob.post(
            f"/api/v1/sessions/{session_id}/intake/probe",
            json={"answer": "补充"},
        ).status_code
        == 404
    )
    assert bob.post(f"/api/v1/sessions/{session_id}/exit", json={}).status_code == 404
    assert (
        bob.post(
            f"/api/v1/sessions/{session_id}/review/run",
            json={"code": "print(1)"},
        ).status_code
        == 404
    )

    # Alice still owns it.
    assert alice.get(f"/api/v1/sessions/{session_id}").status_code == 200


def test_a_generic_session_is_also_private(
    make_isolated: Callable[..., IsolatedHarness],
) -> None:
    """The owner check runs before the intake/card path, not only on reads."""

    harness = make_isolated()
    alice = _user(harness.app, "alice@example.com")
    bob = _user(harness.app, "bob@example.com")
    created = alice.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": "我的乐高结构一推就散，该怎么加固？"},
            "attempt": {"answer": "不知道"},
        },
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]

    assert bob.get(f"/api/v1/sessions/{session_id}").status_code == 404
    assert alice.get(f"/api/v1/sessions/{session_id}").status_code == 200


def test_owner_filter_lives_in_the_service_not_only_the_route(
    make_isolated: Callable[..., IsolatedHarness],
    sample_payload: dict[str, object],
) -> None:
    harness = make_isolated()
    alice = _user(harness.app, "alice@example.com")
    session_id = _start(alice, sample_payload)

    with pytest.raises(SessionNotFound):
        harness.container.service.with_owner("U_SOMEONE_ELSE").get(session_id)

    # Auth off means "no filter": the unbound facade still reads every row,
    # which is the documented local baseline.
    unbound = harness.container.service.with_owner(None)
    assert unbound.get(session_id).session.session_id == session_id


def test_legacy_rows_without_an_owner_are_invisible_when_auth_is_on(
    make_isolated: Callable[..., IsolatedHarness],
    sample_payload: dict[str, object],
) -> None:
    # Written with auth off: owner_id is None.
    offline = make_isolated(auth=False)
    anonymous = TestClient(offline.app)
    session_id = _start(anonymous, sample_payload)

    # Same session file, auth on, fresh accounts: nobody may read the row.
    gated = make_isolated(session_database=offline.session_database)
    alice = _user(gated.app, "alice@example.com")
    assert alice.get(f"/api/v1/sessions/{session_id}").status_code == 404


def test_owner_survives_a_restart(
    make_isolated: Callable[..., IsolatedHarness],
    sample_payload: dict[str, object],
) -> None:
    first = make_isolated()
    alice = _user(first.app, "alice@example.com")
    session_id = _start(alice, sample_payload)

    # A second app over the same two files: log in again, same workspace.
    second = make_isolated(
        auth_database=first.auth_database,
        session_database=first.session_database,
    )
    alice_again = TestClient(second.app)
    login = alice_again.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    assert alice_again.get(f"/api/v1/sessions/{session_id}").status_code == 200

    # And a different account on the restarted app still gets 404.
    bob = _user(second.app, "bob@example.com")
    assert bob.get(f"/api/v1/sessions/{session_id}").status_code == 404


# --------------------------------------------------------------------------
# Current-owner ContextVar: it must survive into FastAPI's sync threadpool
# --------------------------------------------------------------------------


def test_owner_context_reaches_a_sync_route_in_the_threadpool(
    make_isolated: Callable[..., IsolatedHarness],
) -> None:
    harness = make_isolated()

    @harness.app.get("/api/v1/sessions/__owner__/whoami")
    def whoami() -> dict[str, str | None]:
        # Sync endpoint: FastAPI runs this in the threadpool. A ContextVar set
        # only inside a sync dependency would not be visible here.
        return {"owner": current_owner_id()}

    alice = _user(harness.app, "alice@example.com")
    identity = alice.get("/api/v1/auth/me").json()
    response = alice.get("/api/v1/sessions/__owner__/whoami")

    assert response.status_code == 200, response.text
    assert response.json()["owner"] == identity["id"]


def test_unauthenticated_public_routes_do_not_bind_an_owner(
    make_isolated: Callable[..., IsolatedHarness],
) -> None:
    harness = make_isolated()

    @harness.app.get("/__test__/owner")
    def owner() -> dict[str, str | None]:
        return {"owner": current_owner_id()}

    anonymous = TestClient(harness.app)
    # Public path: the middleware does not run, so nothing is bound.
    assert anonymous.get("/__test__/owner").json() == {"owner": None}
