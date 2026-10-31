"""SQLite adapters for session snapshots and generated problems.

The in-memory adapters stay the default for tests and evaluation scripts. The
HTTP app opts in by setting ``SYNAPSE_SESSION_DB`` (``scripts/dev/run.py`` does
this), so a local restart can restore a dialogue without bringing PostgreSQL or
an ORM into the walking skeleton.

Sessions are stored as versioned JSON snapshots (``snapshots.py``). One SQLite
connection per operation keeps the adapter thread-safe; there is no
read-modify-write lock, so concurrent requests for the same session are
last-write-wins. That is a known local-tool boundary, not a claim of safe
multi-user concurrency.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from synapse.application.subject import SubjectRegistry
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem
from synapse.infrastructure.in_memory import InMemoryProblemRepository
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.snapshots import (
    SnapshotError,
    decode_problem,
    decode_session,
    encode_problem,
    encode_session,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    snapshot TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problems (
    problem_id TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dumps(snapshot: dict[str, object]) -> str:
    return json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _ensure_file(path: Path) -> None:
    if str(path) == ":memory:":
        raise ValueError("state DB path must be a file: each operation opens its own connection")
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _ensure_schema(path: Path) -> None:
    _ensure_file(path)
    with _connection(path) as connection:
        connection.executescript(_SCHEMA)


def _load[T](snapshot: object, key: str, decode: Callable[[object], T]) -> T:
    if not isinstance(snapshot, str):
        raise SnapshotError(f"{key}: snapshot column is not text")
    try:
        payload = json.loads(snapshot)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{key}: snapshot is not valid JSON") from exc
    try:
        return decode(payload)
    except SnapshotError as exc:
        raise SnapshotError(f"{key}: {exc}") from exc


class SqliteSessionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        _ensure_schema(path)

    def add(self, session: DialogueSession) -> None:
        self._write(session)

    def save(self, session: DialogueSession) -> None:
        self._write(session)

    def _write(self, session: DialogueSession) -> None:
        with _connection(self._path) as connection:
            connection.execute(
                """
                INSERT INTO sessions
                    (session_id, problem_id, state, updated_at, snapshot)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    problem_id = excluded.problem_id,
                    state = excluded.state,
                    updated_at = excluded.updated_at,
                    snapshot = excluded.snapshot
                """,
                (
                    session.session_id,
                    session.problem_id,
                    session.state.value,
                    _now(),
                    _dumps(encode_session(session)),
                ),
            )

    def get(self, session_id: str) -> DialogueSession | None:
        with _connection(self._path) as connection:
            row = connection.execute(
                "SELECT snapshot FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        session = _load(row["snapshot"], session_id, decode_session)
        if session.session_id != session_id:
            raise SnapshotError(f"{session_id}: snapshot belongs to {session.session_id}")
        return session


class SqliteProblemRepository(InMemoryProblemRepository):
    """Generated problems survive a restart alongside their sessions.

    Only generated problems are written: the annotated catalog comes from
    ``seed.py`` and must not be shadowed by an old copy. Loading happens before
    the container builds subject plugins, so ``catalog`` already contains the
    restored graphs. The first write wins; delete the file to regenerate a
    graph after changing its generator or prompt.
    """

    def __init__(
        self,
        path: Path,
        *,
        problems: tuple[Problem, ...] = (SAMPLE_PROBLEM,),
        plugins: SubjectRegistry | None = None,
    ) -> None:
        super().__init__(problems=problems, plugins=plugins)
        self._path = path
        _ensure_schema(path)
        self._load()

    def _load(self) -> None:
        with _connection(self._path) as connection:
            rows = connection.execute(
                "SELECT problem_id, snapshot FROM problems ORDER BY problem_id"
            ).fetchall()
        for row in rows:
            key = row["problem_id"]
            problem = _load(row["snapshot"], key, decode_problem)
            if problem.id != key:
                raise SnapshotError(f"{key}: snapshot belongs to {problem.id}")
            self.catalog.setdefault(problem.id, problem)

    def add(self, problem: Problem) -> None:
        # ``setdefault`` in the base class is the collision guard: a restored
        # problem must not be replaced by a different graph with the same id.
        existed = problem.id in self.catalog
        super().add(problem)
        if existed or problem.annotated:
            return
        with _connection(self._path) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO problems (problem_id, updated_at, snapshot)
                VALUES (?, ?, ?)
                """,
                (problem.id, _now(), _dumps(encode_problem(problem))),
            )
