"""Leak-guard factory: the only adapter that reads the answer store."""

from __future__ import annotations

from synapse.application.ports import AnswerStore
from synapse.domain.guard.leak import AnswerLeakGuard


class AnswerStoreLeakGuardFactory:
    def __init__(self, answers: AnswerStore) -> None:
        self._answers = answers

    def for_problem(self, problem_id: str) -> AnswerLeakGuard:
        answer = self._answers.answer_for(problem_id)
        solution = self._answers.solution_for(problem_id)
        # Tokens are deliberately narrow: branch labels such as a≤0 are
        # pedagogical, while the final value/range is not.
        forbidden = (answer, "1/e", "a>=1/e", "a≥1/e")
        return AnswerLeakGuard(forbidden=forbidden, reference_solution=solution)
