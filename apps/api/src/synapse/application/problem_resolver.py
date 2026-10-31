"""Resolve a submitted stem to a servable problem.

Two ways a problem can exist (M2.5 S5 ②):

1. it is in the annotated catalog — identification is a strict "the submission
   contains the annotated stem" check (S3), so the wrong graph is never used;
2. it is not, and a subject plugin can generate a graph for it — if the caller
   did not declare ``subject``, a conservative detector picks the plugin; the
   graph then goes through the same structure rules, schema and claim
   verification as the S4 evaluation run, and is stored *unannotated* so later
   turns of the same session can look it up.

Refusing is a first-class outcome: no generator (``SYNAPSE_LLM_MODE=off``, no
API key, a subject that cannot build graphs) means the entry keeps returning
422 rather than diagnosing a problem with a made-up graph.
"""

from __future__ import annotations

import hashlib

from synapse.application.errors import ProblemNotSupported
from synapse.application.graph import GraphBuildFailed
from synapse.application.ports import MutableProblemRepository, ProblemRepository
from synapse.application.subject import SubjectRegistry
from synapse.application.subject_detection import (
    MIN_CONFIDENCE,
    HeuristicSubjectDetector,
    SubjectDetector,
)
from synapse.domain.problem.alignment import normalize
from synapse.domain.problem.models import Problem, ProblemDraft

_TITLE_LIMIT = 32


def generated_id(text: str) -> str:
    """Stable id for a stem, so the same problem is not generated twice.

    Same shape as the annotated ids (``P_...``) because the generator's draft
    validation requires it.
    """

    digest = hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()
    return f"P_GEN_{digest[:12].upper()}"


class ProblemResolver:
    def __init__(
        self,
        problems: ProblemRepository,
        subjects: SubjectRegistry | None,
        *,
        store: MutableProblemRepository | None = None,
        detector: SubjectDetector | None = None,
    ) -> None:
        self._problems = problems
        self._subjects = subjects
        self._store = store
        self._detector = detector or HeuristicSubjectDetector()

    def resolve(self, text: str, declared_subject: str | None = None) -> Problem:
        annotated = self._problems.find_for(text)
        if annotated is not None:
            if declared_subject is not None and declared_subject != annotated.subject:
                # A declared subject we cannot serve is an explicit boundary,
                # not a silently ignored field (M2.5 S1).
                raise ProblemNotSupported(
                    f"subject {declared_subject!r} has no annotated problem yet"
                )
            return annotated
        return self._generate(text, declared_subject)

    def _generate(self, text: str, declared_subject: str | None) -> Problem:
        if not text.strip():
            raise ProblemNotSupported("题目文本为空，无法识别或建图")
        if self._subjects is None or self._store is None:
            raise ProblemNotSupported(_NO_GENERATOR)
        if declared_subject is not None:
            subject = declared_subject
        else:
            detected = self._detector.detect(text)
            if detected.subject is None or detected.confidence < MIN_CONFIDENCE:
                raise ProblemNotSupported(_LOW_CONFIDENCE)
            subject = detected.subject
        plugin = self._subjects.for_subject(subject)
        if plugin is None:
            raise ProblemNotSupported(f"subject {subject!r} has no annotated problem yet")

        problem_id = generated_id(text)
        existing = self._problems.get(problem_id)
        if existing is not None:
            return existing

        draft = ProblemDraft(id=problem_id, text=text.strip(), subject=subject)
        try:
            graph = plugin.build_graph(draft)
        except GraphBuildFailed as exc:
            if exc.reason == "disabled":
                # "disabled" is exactly "this deployment cannot build graphs".
                raise ProblemNotSupported(_NO_GENERATOR) from exc
            raise ProblemNotSupported(f"建图失败：{exc.reason}{_detail(exc)}") from exc

        problem = Problem(
            id=problem_id,
            title=_title(text),
            text=text.strip(),
            graph=graph,
            subject=subject,
            annotated=False,
        )
        self._store.add(problem)
        return problem


_NO_GENERATOR = "这道题没有标注解法图，当前环境也不能建图（SYNAPSE_LLM_MODE=off 或缺少 API key）"
_LOW_CONFIDENCE = "无法可靠识别这道题的学科；请在题面里补一句学科线索（如“函数/受力/阅读”）"


def _detail(exc: GraphBuildFailed) -> str:
    return f": {exc.detail}" if getattr(exc, "detail", "") else ""


def _title(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _TITLE_LIMIT else f"{flat[:_TITLE_LIMIT]}…"
