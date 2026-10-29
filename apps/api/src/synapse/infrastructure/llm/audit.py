"""Audit sinks: JSONL for a real deployment, in-memory for tests."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from synapse.application.audit import AuditEntry


class InMemoryCallAuditor:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._lock = Lock()

    def record(self, entry: AuditEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class NullCallAuditor:
    def record(self, entry: AuditEntry) -> None:
        del entry


class JsonlCallAuditor:
    """Append-only JSONL; one file per environment is enough for M2."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: AuditEntry) -> None:
        line = json.dumps(entry.as_dict(), ensure_ascii=False)
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    @property
    def path(self) -> Path:
        return self._path