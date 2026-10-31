"""Explicit maintenance for the optional SQLite session store.

SQLite has no TTL. Nothing here runs on a timer and the API never deletes a
session on its own: every destructive action is a CLI call that reports what
it would do unless ``--apply`` is passed. The store contains student probe
answers and work findings, so retention is an operator decision, not a default
buried in the server.

The one non-destructive migration is snapshot *format*. Reading still refuses
an old payload; ``migrate_store`` is the explicit entry point that rewrites it.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from synapse.infrastructure.snapshots import (
    SNAPSHOT_VERSION,
    SnapshotError,
    SnapshotVersionError,
    migrate_snapshot,
)
from synapse.infrastructure.sqlite_state import (
    SCHEMA_VERSION,
    StateSchemaError,
    ensure_schema,
)

_TABLES = (("sessions", "session_id"), ("problems", "problem_id"))


@dataclass(frozen=True, slots=True)
class SnapshotVersionCount:
    kind: str
    version: str
    count: int


@dataclass(frozen=True, slots=True)
class StoreStats:
    path: Path
    schema_version: int
    session_count: int
    problem_count: int
    oldest_session_at: str | None
    newest_session_at: str | None
    versions: tuple[SnapshotVersionCount, ...]
    file_bytes: int


@dataclass(frozen=True, slots=True)
class CleanupReport:
    path: Path
    cutoff: datetime
    session_ids: tuple[str, ...]
    problem_ids: tuple[str, ...]
    apply: bool
    include_orphan_problems: bool


@dataclass(frozen=True, slots=True)
class PurgeReport:
    path: Path
    session_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    problem_ids: tuple[str, ...]
    apply: bool


@dataclass(frozen=True, slots=True)
class MigrationChange:
    kind: str
    from_version: str
    to_version: str
    count: int


@dataclass(frozen=True, slots=True)
class MigrationReport:
    path: Path
    apply: bool
    changes: tuple[MigrationChange, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"session store not found: {path}")


@contextmanager
def _open(path: Path) -> Iterator[sqlite3.Connection]:
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


def _schema_version(connection: sqlite3.Connection, path: Path) -> int:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise StateSchemaError(
            f"{path}: SQLite schema version {version} is newer than this build "
            f"supports ({SCHEMA_VERSION}); use a matching build or back up the file"
        )
    return version


def _json_payload(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _version_of(raw: object) -> tuple[str, str]:
    payload = _json_payload(raw)
    if payload is None:
        return ("unknown", "invalid")
    kind = payload.get("kind")
    version = payload.get("version")
    return (
        kind if isinstance(kind, str) else "unknown",
        version if isinstance(version, str) else "invalid",
    )


def _parse_time(value: object) -> datetime:
    # An unreadable timestamp is never treated as old: deleting the wrong row
    # is worse than leaving a row for a human to inspect.
    unreadable = datetime.max.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return unreadable
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return unreadable
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def scan(path: Path) -> StoreStats:
    """Read-only summary; does not create or upgrade the file."""

    _require_file(path)
    with _open(path) as connection:
        schema = _schema_version(connection, path)
        session_count = int(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        problem_count = int(connection.execute("SELECT COUNT(*) FROM problems").fetchone()[0])
        span = connection.execute(
            "SELECT MIN(updated_at) AS oldest, MAX(updated_at) AS newest FROM sessions"
        ).fetchone()
        oldest = span["oldest"] if isinstance(span["oldest"], str) else None
        newest = span["newest"] if isinstance(span["newest"], str) else None
        counts: Counter[tuple[str, str]] = Counter()
        for table, _key in _TABLES:
            rows = connection.execute(f"SELECT snapshot FROM {table}").fetchall()
            for row in rows:
                counts[_version_of(row["snapshot"])] += 1
    versions = tuple(
        SnapshotVersionCount(kind=kind, version=version, count=count)
        for (kind, version), count in sorted(counts.items())
    )
    return StoreStats(
        path=path,
        schema_version=schema,
        session_count=session_count,
        problem_count=problem_count,
        oldest_session_at=oldest,
        newest_session_at=newest,
        versions=versions,
        file_bytes=path.stat().st_size,
    )


def cleanup(
    path: Path,
    *,
    older_than_days: float,
    apply: bool,
    include_orphan_problems: bool = False,
) -> CleanupReport:
    """Select sessions whose last write is older than the cutoff.

    ``updated_at`` is the TTL signal: a session that keeps being used is never
    old, regardless of when it was created. Only sessions and, optionally,
    generated problems no surviving session references are removed.
    """

    if older_than_days <= 0:
        raise ValueError("older_than_days must be positive")
    _require_file(path)
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    with _open(path) as connection:
        _schema_version(connection, path)
        session_rows = connection.execute("SELECT session_id, updated_at FROM sessions").fetchall()
        stale = tuple(
            sorted(
                str(row["session_id"])
                for row in session_rows
                if _parse_time(row["updated_at"]) < cutoff
            )
        )
        stale_set = set(stale)
        problem_ids: tuple[str, ...] = ()
        if include_orphan_problems:
            referenced = {
                str(row["problem_id"])
                for row in connection.execute("SELECT session_id, problem_id FROM sessions")
                if str(row["session_id"]) not in stale_set
            }
            problem_rows = connection.execute(
                "SELECT problem_id, updated_at FROM problems"
            ).fetchall()
            problem_ids = tuple(
                sorted(
                    str(row["problem_id"])
                    for row in problem_rows
                    if str(row["problem_id"]) not in referenced
                    and _parse_time(row["updated_at"]) < cutoff
                )
            )
        if apply:
            connection.executemany(
                "DELETE FROM sessions WHERE session_id = ?",
                [(session_id,) for session_id in stale],
            )
            connection.executemany(
                "DELETE FROM problems WHERE problem_id = ?",
                [(problem_id,) for problem_id in problem_ids],
            )
    return CleanupReport(
        path=path,
        cutoff=cutoff,
        session_ids=stale,
        problem_ids=problem_ids,
        apply=apply,
        include_orphan_problems=include_orphan_problems,
    )


def purge(
    path: Path,
    *,
    session_ids: Sequence[str],
    apply: bool,
    include_orphan_problems: bool = False,
) -> PurgeReport:
    """Delete named sessions; useful for a single-student privacy request."""

    wanted = tuple(dict.fromkeys(session_ids))
    if not wanted:
        raise ValueError("at least one session id is required")
    _require_file(path)
    with _open(path) as connection:
        _schema_version(connection, path)
        existing = {
            str(row["session_id"]) for row in connection.execute("SELECT session_id FROM sessions")
        }
        found = tuple(session_id for session_id in wanted if session_id in existing)
        missing = tuple(session_id for session_id in wanted if session_id not in existing)
        problem_ids: tuple[str, ...] = ()
        if include_orphan_problems:
            remaining = existing - set(found)
            referenced = {
                str(row["problem_id"])
                for row in connection.execute("SELECT session_id, problem_id FROM sessions")
                if str(row["session_id"]) in remaining
            }
            problem_ids = tuple(
                sorted(
                    str(row["problem_id"])
                    for row in connection.execute("SELECT problem_id FROM problems")
                    if str(row["problem_id"]) not in referenced
                )
            )
        if apply:
            connection.executemany(
                "DELETE FROM sessions WHERE session_id = ?",
                [(session_id,) for session_id in found],
            )
            connection.executemany(
                "DELETE FROM problems WHERE problem_id = ?",
                [(problem_id,) for problem_id in problem_ids],
            )
    return PurgeReport(
        path=path,
        session_ids=found,
        missing_ids=missing,
        problem_ids=problem_ids,
        apply=apply,
    )


def vacuum_store(path: Path) -> None:
    """Reclaim free pages after a delete (also drops residual row bytes).

    SQLite DELETE does not zero the old pages. This is not secure erase on a
    copy-on-write filesystem or an SSD, but it removes the text from the file
    a local operator would hand to someone else.
    """

    _require_file(path)
    with _open(path) as connection:
        connection.execute("VACUUM")


def migrate_store(path: Path, *, apply: bool) -> MigrationReport:
    """Rewrite legacy snapshot versions; abort without writes on any unknown.

    Structural schema changes are safe and automatic, so ``apply`` upgrades the
    columns before touching payloads. Snapshot payloads are different: the plan
    is validated in full first, and one unknown or corrupt row prevents every
    write, leaving the operator a concrete error instead of a half-migrated
    file.
    """

    _require_file(path)
    if apply:
        ensure_schema(path)
    changes: Counter[tuple[str, str]] = Counter()
    errors: list[str] = []
    pending: list[tuple[str, str, dict[str, object]]] = []
    with _open(path) as connection:
        _schema_version(connection, path)
        for table, key_column in _TABLES:
            rows = connection.execute(
                f"SELECT {key_column} AS key, snapshot FROM {table}"
            ).fetchall()
            for row in rows:
                key = str(row["key"])
                payload = _json_payload(row["snapshot"])
                if payload is None:
                    errors.append(f"{table}:{key}: snapshot is not a JSON object")
                    continue
                kind, version = _version_of(row["snapshot"])
                try:
                    migrated = migrate_snapshot(payload)
                except SnapshotVersionError as exc:
                    errors.append(f"{table}:{key}: {exc}")
                    continue
                except SnapshotError as exc:
                    errors.append(f"{table}:{key}: {exc}")
                    continue
                if version == SNAPSHOT_VERSION:
                    continue
                changes[(kind, version)] += 1
                pending.append((table, key, migrated))
        if apply and not errors:
            for table, key, migrated in pending:
                snapshot = json.dumps(
                    migrated,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if table == "sessions":
                    revision = _migrated_revision(migrated)
                    connection.execute(
                        "UPDATE sessions SET snapshot = ?, revision = ? WHERE session_id = ?",
                        (snapshot, revision, key),
                    )
                else:
                    connection.execute(
                        "UPDATE problems SET snapshot = ? WHERE problem_id = ?",
                        (snapshot, key),
                    )
    change_rows = tuple(
        MigrationChange(
            kind=kind,
            from_version=version,
            to_version=SNAPSHOT_VERSION,
            count=count,
        )
        for (kind, version), count in sorted(changes.items())
    )
    return MigrationReport(
        path=path,
        apply=apply,
        changes=change_rows,
        errors=tuple(errors),
    )


def _migrated_revision(migrated: dict[str, object]) -> int:
    data = migrated.get("data")
    if not isinstance(data, dict):
        raise SnapshotError("session snapshot has no data object")
    value = data.get("revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SnapshotError("session snapshot has no valid revision")
    return value
