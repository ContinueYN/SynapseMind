"""SQLite adapters for session snapshots and generated problems.

The in-memory adapters stay the default for tests and evaluation scripts. The
HTTP app opts in by setting ``SYNAPSE_SESSION_DB`` (``scripts/dev/run.py`` does
this), so a local restart can restore a dialogue without bringing PostgreSQL or
an ORM into the walking skeleton.

Sessions are stored as versioned JSON snapshots (``snapshots.py``). One SQLite
connection per operation keeps the adapter thread-safe. Writes are
compare-and-swap on the ``revision`` column: a caller that read revision N can
only save while the row is still at N, otherwise it gets ``SessionConflict``
instead of overwriting a newer turn. That protects one writer from another, but
it is not a multi-user transaction boundary: the service still does
read-modify-write and deliberately does not retry a conflicting request.

Schema changes (columns/indexes) are applied automatically so an existing
local file keeps working. Snapshot *format* changes are not: a row whose JSON
version is not current raises ``SnapshotVersionError`` and must be migrated
with ``scripts/dev/session_store.py``. Reading never upgrades data silently.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from synapse.application.errors import SessionConflict
from synapse.application.subject import SubjectRegistry
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem
from synapse.infrastructure.in_memory import InMemoryProblemRepository
from synapse.infrastructure.seed import SAMPLE_PROBLEM
from synapse.infrastructure.snapshots import (
    SnapshotError,
    SnapshotVersionError,
    decode_problem,
    decode_session,
    encode_problem,
    encode_session,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    snapshot TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_updated_at ON sessions(updated_at);

CREATE TABLE IF NOT EXISTS problems (
    problem_id TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    snapshot TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS problems_updated_at ON problems(updated_at);
"""


class StateSchemaError(RuntimeError):
    """The SQLite file was written by a newer schema than this build knows."""


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
def connect(path: Path) -> Iterator[sqlite3.Connection]:
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


def ensure_schema(path: Path) -> int:
    """Create or structurally upgrade the store; return the schema version.

    This is intentionally limited to columns and indexes. It never rewrites a
    snapshot payload: format migration needs an explicit operator command.
    """

    _ensure_file(path)
    with connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise StateSchemaError(
                f"{path}: SQLite schema version {version} is newer than this build "
                f"supports ({SCHEMA_VERSION}); use a matching build or back up the file"
            )
        connection.executescript(_SCHEMA)
        columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(sessions)")}
        if "revision" not in columns:
            # Local file from the 0.1 snapshot era: the column was absent.
            # Two processes can reach this branch together; losing the race is
            # harmless as long as the other process added the same column.
            try:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return SCHEMA_VERSION


def _load[T](snapshot: object, key: str, decode: Callable[[object], T]) -> T:
    if not isinstance(snapshot, str):
        raise SnapshotError(f"{key}: snapshot column is not text")
    try:
        payload = json.loads(snapshot)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{key}: snapshot is not valid JSON") from exc
    try:
        return decode(payload)
    except SnapshotVersionError as exc:
        # Keep the type (and its migration hint) intact for the route handler
        # and the maintenance command; only prefix the row key.
        raise SnapshotVersionError(
            f"{key}: {exc}",
            version=exc.version,
            kind=exc.kind,
            migratable=exc.migratable,
        ) from exc
    except SnapshotError as exc:
        raise SnapshotError(f"{key}: {exc}") from exc


class SqliteSessionRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        ensure_schema(path)

    def add(self, session: DialogueSession) -> None:
        """Insert a brand-new session at revision 0.

        ``add`` is not an upsert: a duplicate id means the caller is trying to
        replay a creation, and overwriting the stored dialogue would be the
        exact lost update this adapter is meant to stop.
        """

        with connect(self._path) as connection:
            existing = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
            if existing is not None:
                raise SessionConflict(
                    f"session {session.session_id} already exists; reload it instead of adding"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO sessions
                        (session_id, problem_id, state, updated_at, revision, snapshot)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (
                        session.session_id,
                        session.problem_id,
                        session.state.value,
                        _now(),
                        _dumps(encode_session(session, revision=0)),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # Lost a race between the check and the insert.
                raise SessionConflict(
                    f"session {session.session_id} was created concurrently"
                ) from exc
        session.revision = 0

    def save(self, session: DialogueSession) -> None:
        """Compare-and-swap the snapshot on ``session.revision``.

        A stale object raises ``SessionConflict`` and leaves the stored row
        untouched. The aggregate's revision is advanced only after SQLite
        confirms exactly one row changed.
        """

        expected = session.revision
        new_revision = expected + 1
        snapshot = _dumps(encode_session(session, revision=new_revision))
        with connect(self._path) as connection:
            cursor = connection.execute(
                """
                UPDATE sessions
                SET problem_id = ?, state = ?, updated_at = ?, revision = ?, snapshot = ?
                WHERE session_id = ? AND revision = ?
                """,
                (
                    session.problem_id,
                    session.state.value,
                    _now(),
                    new_revision,
                    snapshot,
                    session.session_id,
                    expected,
                ),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT revision FROM sessions WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()
                if row is None:
                    raise SessionConflict(
                        f"session {session.session_id} no longer exists; "
                        "it may have been removed by an explicit purge"
                    )
                raise SessionConflict(
                    f"session {session.session_id} changed since it was read "
                    f"(stored revision {row['revision']}, this copy is {expected}); "
                    "reload before retrying"
                )
        session.revision = new_revision

    def get(self, session_id: str) -> DialogueSession | None:
        with connect(self._path) as connection:
            row = connection.execute(
                "SELECT revision, snapshot FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        session = _load(row["snapshot"], session_id, decode_session)
        if session.session_id != session_id:
            raise SnapshotError(f"{session_id}: snapshot belongs to {session.session_id}")
        if session.revision != row["revision"]:
            raise SnapshotError(
                f"{session_id}: snapshot revision {session.revision} does not match "
                f"row revision {row['revision']}"
            )
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
        ensure_schema(path)
        self._load()

    def _load(self) -> None:
        with connect(self._path) as connection:
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
        with connect(self._path) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO problems (problem_id, updated_at, snapshot)
                VALUES (?, ?, ?)
                """,
                (problem.id, _now(), _dumps(encode_problem(problem))),
            )
