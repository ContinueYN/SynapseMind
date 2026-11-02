"""Request-scoped trace, so audit rows know which session/turn they belong to.

``ProbeComposer.compose`` must keep its signature (chapter 12 §4.3), so the
session id cannot be a parameter. A context variable keeps the seam explicit:
the service binds it, adapters read it, nothing changes in the protocol.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Trace:
    session_id: str
    turn: int


_current: ContextVar[Trace | None] = ContextVar("synapse_trace", default=None)


@contextmanager
def tracing(session_id: str, turn: int) -> Iterator[None]:
    token = _current.set(Trace(session_id=session_id, turn=turn))
    try:
        yield
    finally:
        _current.reset(token)


def current() -> Trace | None:
    return _current.get()
