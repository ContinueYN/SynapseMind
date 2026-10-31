"""Local, durable review queue.

SQLite is deliberate: one file under ``var/`` (ignored), no server, no
migration framework. It is enough to make a teacher review pass possible before
the product has PostgreSQL and authentication.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from synapse.application.review import ReviewItem

_SCHEMA = """
CREATE TABLE IF NOT EXISTS card_disagreements (
    session_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    label TEXT NOT NULL,
    node_id TEXT NOT NULL,
    one_line TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL
)
"""


class SqliteReviewQueue:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, item: ReviewItem) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(_SCHEMA)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO card_disagreements
                    (session_id, problem_id, layer, label, node_id, one_line,
                     confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.session_id,
                        item.problem_id,
                        item.layer,
                        item.label,
                        item.node_id,
                        item.one_line,
                        item.confidence,
                        item.created_at,
                    ),
                )
        finally:
            connection.close()

    def items(self) -> list[ReviewItem]:
        if not self._path.exists():
            return []
        connection = self._connect()
        try:
            with connection:
                connection.execute(_SCHEMA)
            rows = connection.execute(
                """
                SELECT session_id, problem_id, layer, label, node_id, one_line,
                       confidence, created_at
                FROM card_disagreements
                ORDER BY created_at DESC, session_id
                """
            ).fetchall()
        finally:
            connection.close()
        return [
            ReviewItem(
                session_id=row["session_id"],
                problem_id=row["problem_id"],
                layer=row["layer"],
                label=row["label"],
                node_id=row["node_id"],
                one_line=row["one_line"],
                confidence=row["confidence"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


class InMemoryReviewQueue:
    """Small test double; the service never depends on SQLite directly."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}

    def record(self, item: ReviewItem) -> None:
        self._items[item.session_id] = item

    def items(self) -> list[ReviewItem]:
        return list(reversed(self._items.values()))
