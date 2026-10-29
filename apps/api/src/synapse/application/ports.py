"""Application ports.

The domain and use cases depend on these Protocols, never on databases,
FastAPI or an LLM SDK. Adapters live in ``synapse.infrastructure``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem


class SessionRepository(Protocol):
    def add(self, session: DialogueSession) -> None: ...

    def get(self, session_id: str) -> DialogueSession | None: ...

    def save(self, session: DialogueSession) -> None: ...


class ProblemRepository(Protocol):
    def get(self, problem_id: str) -> Problem | None: ...

    def find_for(self, text: str) -> Problem | None: ...


class MutableProblemRepository(ProblemRepository, Protocol):
    """A catalog that also accepts a problem generated on demand (M2.5 S5 ②)."""

    def add(self, problem: Problem) -> None: ...


class AnswerStore(Protocol):
    """Physically separate from the prompt builder.

    The answer is only read when constructing the leak guard; it is never put
    in a learning-mode response.
    """

    def answer_for(self, problem_id: str) -> str: ...

    def solution_for(self, problem_id: str) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_session_id(self) -> str: ...
