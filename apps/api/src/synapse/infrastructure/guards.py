"""Leak-guard factory: the only adapter that reads the answer store."""

from __future__ import annotations

from synapse.application.ports import AnswerStore
from synapse.domain.guard.leak import AnswerLeakGuard

# A generated problem has no stored answer, so there is nothing to match. These
# are the phrases that would hand an answer over regardless of what it is; the
# composer prompt carries the rest of the prohibition (documented gap: with no
# stored answer the n-gram rule cannot fire).
_NO_ANSWER_FORBIDDEN = ("答案是", "答案为", "最终答案", "所以答案", "正确答案")


class AnswerStoreLeakGuardFactory:
    def __init__(self, answers: AnswerStore) -> None:
        self._answers = answers

    def for_problem(self, problem_id: str) -> AnswerLeakGuard:
        try:
            answer = self._answers.answer_for(problem_id)
            solution = self._answers.solution_for(problem_id)
        except KeyError:
            # M2.5 S5 ②: the problem was generated for this session, so no
            # reviewed answer exists. Never invent one — degrade to the generic
            # phrases instead of pretending the guard is fully armed.
            return AnswerLeakGuard(forbidden=_NO_ANSWER_FORBIDDEN)
        # Tokens are deliberately narrow: branch labels such as a≤0 are
        # pedagogical, while the final value/range is not.
        forbidden = (answer, "1/e", "a>=1/e", "a≥1/e")
        return AnswerLeakGuard(forbidden=forbidden, reference_solution=solution)
