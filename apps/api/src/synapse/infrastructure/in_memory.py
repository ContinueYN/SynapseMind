"""In-memory adapters for the walking skeleton.

No database yet; the Protocols in ``application.ports`` are the seam for
PostgreSQL/Alembic in M2.
"""

from __future__ import annotations

from threading import RLock

from synapse.application.ports import ProblemRepository
from synapse.application.subject import SubjectRegistry
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem
from synapse.infrastructure.seed import SAMPLE_ANSWER, SAMPLE_PROBLEM, SAMPLE_SOLUTION
from synapse.infrastructure.subjects.math import MathPlugin


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._items: dict[str, DialogueSession] = {}
        self._lock = RLock()

    def add(self, session: DialogueSession) -> None:
        with self._lock:
            self._items[session.session_id] = session

    def get(self, session_id: str) -> DialogueSession | None:
        with self._lock:
            return self._items.get(session_id)

    def save(self, session: DialogueSession) -> None:
        with self._lock:
            self._items[session.session_id] = session


class InMemoryProblemRepository(ProblemRepository):
    def __init__(
        self,
        problems: tuple[Problem, ...] = (SAMPLE_PROBLEM,),
        plugins: SubjectRegistry | None = None,
    ) -> None:
        self._problems = {problem.id: problem for problem in problems}
        self._plugins = plugins or SubjectRegistry((MathPlugin(self._problems),))

    @property
    def plugins(self) -> SubjectRegistry:
        return self._plugins

    def get(self, problem_id: str) -> Problem | None:
        return self._problems.get(problem_id)

    def find_for(self, text: str) -> Problem | None:
        # Identification now goes through the subject plugin (M2.5 S2). M1 had
        # one annotated problem; do not silently diagnose a different stem with
        # the sample graph — an explicit 422 is still safer.
        hit = self._plugins.identify(text)
        if hit is None:
            return None
        return self._problems.get(hit[1].problem_id)


class InMemoryAnswerStore:
    def __init__(
        self,
        answers: dict[str, str] | None = None,
        solutions: dict[str, str] | None = None,
    ) -> None:
        self._answers = answers or {SAMPLE_PROBLEM.id: SAMPLE_ANSWER}
        self._solutions = solutions or {SAMPLE_PROBLEM.id: SAMPLE_SOLUTION}

    def answer_for(self, problem_id: str) -> str:
        return self._answers[problem_id]

    def solution_for(self, problem_id: str) -> str:
        return self._solutions[problem_id]
