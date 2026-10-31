from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from synapse.api.main import create_app
from synapse.application.errors import SessionConflict
from synapse.domain.diagnosis.hypotheses import HypothesisSet
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.dialogue.states import DialogueState
from synapse.domain.problem.models import AlignmentResult, Problem, SolutionGraph
from synapse.infrastructure.in_memory import InMemorySessionRepository
from synapse.infrastructure.session_maintenance import (
    cleanup,
    migrate_store,
    purge,
    scan,
    vacuum_store,
)
from synapse.infrastructure.snapshots import (
    SNAPSHOT_VERSION,
    SnapshotError,
    SnapshotVersionError,
    decode_problem,
    decode_session,
    encode_problem,
    encode_session,
    migrate_snapshot,
)
from synapse.infrastructure.sqlite_state import (
    SCHEMA_VERSION,
    SqliteProblemRepository,
    SqliteSessionRepository,
    StateSchemaError,
)


@contextmanager
def _sqlite(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _minimal_session(
    session_id: str = "S_STORE000001",
    *,
    problem_id: str = "P_FUNC_001",
    revision: int = 0,
) -> DialogueSession:
    return DialogueSession(
        session_id=session_id,
        problem_id=problem_id,
        state=DialogueState.PROBE,
        alignment=AlignmentResult(
            first_divergence="n3",
            matched_node_ids=("n1", "n2"),
            missing_node_ids=("n3",),
            evidence=("n1 已写",),
        ),
        hypotheses=HypothesisSet(),
        max_turns=6,
        created_at=datetime(2026, 10, 31, tzinfo=UTC),
        revision=revision,
    )


def _generated_problem(problem_id: str) -> Problem:
    return Problem(
        id=problem_id,
        title="清理测试题",
        text="清理测试题",
        graph=SolutionGraph(
            problem_id=problem_id,
            version="0.1",
            stem="清理测试题",
            nodes=(),
            edges=(),
        ),
        annotated=False,
    )


def _legacy_session(snapshot: dict[str, object]) -> dict[str, object]:
    legacy = copy.deepcopy(snapshot)
    legacy["version"] = "0.1"
    data = legacy["data"]
    assert isinstance(data, dict)
    data.pop("revision", None)
    return legacy


def _legacy_problem(snapshot: dict[str, object]) -> dict[str, object]:
    legacy = copy.deepcopy(snapshot)
    legacy["version"] = "0.1"
    return legacy


def _insert_session_row(
    path: Path,
    session_id: str,
    snapshot: dict[str, object],
    *,
    updated_at: str = "2026-10-01T00:00:00+00:00",
    revision: int = 0,
) -> None:
    with _sqlite(path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO sessions
                (session_id, problem_id, state, updated_at, revision, snapshot)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "P_FUNC_001",
                "PROBE",
                updated_at,
                revision,
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )


def _set_updated_at(path: Path, table: str, key_column: str, key: str, value: str) -> None:
    with _sqlite(path) as connection:
        connection.execute(
            f"UPDATE {table} SET updated_at = ? WHERE {key_column} = ?",
            (value, key),
        )


def _read_snapshot(path: Path, table: str, key_column: str, key: str) -> str:
    with _sqlite(path) as connection:
        row = connection.execute(
            f"SELECT snapshot FROM {table} WHERE {key_column} = ?",
            (key,),
        ).fetchone()
    assert row is not None
    return str(row["snapshot"])


def test_snapshot_round_trip_carries_version_and_revision() -> None:
    session = _minimal_session(revision=3)
    snapshot = encode_session(session)

    assert snapshot["version"] == SNAPSHOT_VERSION
    assert decode_session(snapshot).revision == 3


def test_legacy_session_snapshot_is_rejected_with_a_migration_hint() -> None:
    legacy = _legacy_session(encode_session(_minimal_session()))

    with pytest.raises(SnapshotVersionError) as caught:
        decode_session(legacy)

    assert caught.value.migratable is True
    assert "migrate" in str(caught.value)
    assert SNAPSHOT_VERSION in str(caught.value)


def test_unknown_snapshot_version_is_not_silently_accepted() -> None:
    snapshot = encode_session(_minimal_session())
    snapshot["version"] = "9.9"

    with pytest.raises(SnapshotVersionError) as caught:
        decode_session(snapshot)

    assert caught.value.migratable is False
    assert "no migration" in str(caught.value)


def test_migrate_snapshot_upgrades_a_legacy_session() -> None:
    legacy = _legacy_session(encode_session(_minimal_session()))
    assert "revision" not in legacy["data"]  # type: ignore[operator]

    migrated = migrate_snapshot(legacy)

    assert migrated["version"] == SNAPSHOT_VERSION
    restored = decode_session(migrated)
    assert restored.revision == 0
    assert restored.session_id == "S_STORE000001"


def test_migrate_snapshot_upgrades_a_legacy_problem() -> None:
    legacy = _legacy_problem(encode_problem(_generated_problem("P_LEGACY")))

    migrated = migrate_snapshot(legacy)

    assert migrated["version"] == SNAPSHOT_VERSION
    restored = decode_problem(migrated)
    assert restored.id == "P_LEGACY"


def test_legacy_file_is_structurally_upgraded_but_snapshots_need_migration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    session_id = "S_LEGACY000001"
    legacy = _legacy_session(encode_session(_minimal_session(session_id)))
    with _sqlite(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                snapshot TEXT NOT NULL
            );
            CREATE TABLE problems (
                problem_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                snapshot TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO sessions
                (session_id, problem_id, state, updated_at, snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "P_FUNC_001",
                "PROBE",
                "2026-10-01T00:00:00+00:00",
                json.dumps(legacy, ensure_ascii=False),
            ),
        )

    repo = SqliteSessionRepository(path)

    with _sqlite(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
    assert "revision" in columns

    with pytest.raises(SnapshotVersionError, match="migrate"):
        repo.get(session_id)

    report = migrate_store(path, apply=True)

    assert report.ok
    assert report.changes[0].from_version == "0.1"
    restored = repo.get(session_id)
    assert restored is not None
    assert restored.revision == 0
    # Migration must not extend the TTL window as a side effect.
    with _sqlite(path) as connection:
        updated_at = connection.execute(
            "SELECT updated_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    assert updated_at == "2026-10-01T00:00:00+00:00"


def test_api_reports_a_legacy_snapshot_with_the_migration_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNAPSE_SESSION_DB", str(tmp_path / "state.sqlite3"))
    app = create_app()
    session_id = "S_LEGACY000002"
    _insert_session_row(
        tmp_path / "state.sqlite3",
        session_id,
        _legacy_session(encode_session(_minimal_session(session_id))),
    )

    response = TestClient(app).get(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "migrate" in detail
    assert "session_store.py" in detail


def test_sqlite_save_rejects_a_stale_revision(tmp_path: Path) -> None:
    repo = SqliteSessionRepository(tmp_path / "state.sqlite3")
    session = _minimal_session()
    repo.add(session)
    first = repo.get(session.session_id)
    second = repo.get(session.session_id)
    assert first is not None
    assert second is not None

    first.turn = 2
    repo.save(first)

    with pytest.raises(SessionConflict, match="changed since it was read"):
        repo.save(second)

    stored = repo.get(session.session_id)
    assert stored is not None
    assert stored.turn == 2
    assert stored.revision == 1


def test_in_memory_save_rejects_a_stale_revision() -> None:
    repo = InMemorySessionRepository()
    session = _minimal_session()
    repo.add(session)
    first = repo.get(session.session_id)
    second = repo.get(session.session_id)
    assert first is not None
    assert second is not None

    first.turn = 2
    repo.save(first)

    with pytest.raises(SessionConflict, match="changed since it was read"):
        repo.save(second)

    stored = repo.get(session.session_id)
    assert stored is not None
    assert stored.turn == 2
    assert stored.revision == 1


@pytest.mark.parametrize("kind", ["sqlite", "memory"])
def test_add_rejects_a_duplicate_session_id(kind: str, tmp_path: Path) -> None:
    repo: Any
    if kind == "sqlite":
        repo = SqliteSessionRepository(tmp_path / "state.sqlite3")
    else:
        repo = InMemorySessionRepository()
    repo.add(_minimal_session())

    with pytest.raises(SessionConflict, match="already exists"):
        repo.add(_minimal_session())


def test_revision_column_mismatch_fails_loudly(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    session = _minimal_session()
    repo.add(session)

    with _sqlite(path) as connection:
        connection.execute(
            "UPDATE sessions SET revision = 7 WHERE session_id = ?",
            (session.session_id,),
        )

    with pytest.raises(SnapshotError, match="does not match"):
        repo.get(session.session_id)


def test_cleanup_is_dry_run_by_default_then_deletes_only_old_rows(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    repo.add(_minimal_session("S_OLD00000001"))
    repo.add(_minimal_session("S_NEW00000001"))
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat(timespec="seconds")
    _set_updated_at(path, "sessions", "session_id", "S_OLD00000001", old)

    preview = cleanup(path, older_than_days=30, apply=False)

    assert preview.session_ids == ("S_OLD00000001",)
    assert repo.get("S_OLD00000001") is not None

    applied = cleanup(path, older_than_days=30, apply=True)

    assert applied.session_ids == ("S_OLD00000001",)
    assert repo.get("S_OLD00000001") is None
    assert repo.get("S_NEW00000001") is not None


def test_cleanup_keeps_shared_problems_and_removes_only_orphans(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    sessions = SqliteSessionRepository(path)
    problems = SqliteProblemRepository(path)
    orphan = _generated_problem("P_ORPHAN00001")
    shared = _generated_problem("P_SHARED00001")
    problems.add(orphan)
    problems.add(shared)
    sessions.add(_minimal_session("S_SHARED000001", problem_id=shared.id))
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat(timespec="seconds")
    _set_updated_at(path, "problems", "problem_id", orphan.id, old)
    _set_updated_at(path, "problems", "problem_id", shared.id, old)

    without_flag = cleanup(
        path,
        older_than_days=30,
        apply=True,
        include_orphan_problems=False,
    )
    assert without_flag.problem_ids == ()

    applied = cleanup(
        path,
        older_than_days=30,
        apply=True,
        include_orphan_problems=True,
    )

    assert applied.problem_ids == (orphan.id,)
    reloaded = SqliteProblemRepository(path)
    assert reloaded.get(orphan.id) is None
    assert reloaded.get(shared.id) is not None


def test_purge_reports_missing_ids_and_requires_apply(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    repo.add(_minimal_session("S_PURGE000001"))

    preview = purge(path, session_ids=["S_PURGE000001", "S_MISSING0001"], apply=False)

    assert preview.session_ids == ("S_PURGE000001",)
    assert preview.missing_ids == ("S_MISSING0001",)
    assert repo.get("S_PURGE000001") is not None

    applied = purge(path, session_ids=["S_PURGE000001", "S_MISSING0001"], apply=True)

    assert applied.session_ids == ("S_PURGE000001",)
    assert repo.get("S_PURGE000001") is None


def test_vacuum_store_reclaims_after_a_purge(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    repo.add(_minimal_session("S_VACUUM000001"))
    purge(path, session_ids=["S_VACUUM000001"], apply=True)

    vacuum_store(path)

    assert path.is_file()
    assert scan(path).session_count == 0


def test_migration_aborts_on_an_unknown_version_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    session = _minimal_session()
    repo.add(session)
    unknown = {"version": "9.9", "kind": "session", "data": {}}
    with _sqlite(path) as connection:
        connection.execute(
            "UPDATE sessions SET snapshot = ? WHERE session_id = ?",
            (json.dumps(unknown), session.session_id),
        )
    before = _read_snapshot(path, "sessions", "session_id", session.session_id)

    report = migrate_store(path, apply=True)

    assert report.ok is False
    assert any("no migration" in error for error in report.errors)
    assert _read_snapshot(path, "sessions", "session_id", session.session_id) == before


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with _sqlite(path) as connection:
        connection.execute("PRAGMA user_version = 99")

    with pytest.raises(StateSchemaError, match="newer"):
        SqliteSessionRepository(path)


def test_stats_reports_current_and_legacy_versions(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    repo = SqliteSessionRepository(path)
    repo.add(_minimal_session("S_CURRENT00001"))
    _insert_session_row(
        path,
        "S_LEGACY000003",
        _legacy_session(encode_session(_minimal_session("S_LEGACY000003"))),
    )

    stats = scan(path)

    assert stats.schema_version == SCHEMA_VERSION
    assert stats.session_count == 2
    versions = {(item.kind, item.version): item.count for item in stats.versions}
    assert versions[("session", SNAPSHOT_VERSION)] == 1
    assert versions[("session", "0.1")] == 1


def test_api_maps_a_session_conflict_to_409(
    client: TestClient,
    sample_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    container = client.app.state.container

    def conflict(_session: object) -> None:
        raise SessionConflict("stale revision")

    monkeypatch.setattr(container.sessions, "save", conflict)

    response = client.post(f"/api/v1/sessions/{session_id}/exit")

    assert response.status_code == 409
    assert "刷新" in response.json()["detail"]
