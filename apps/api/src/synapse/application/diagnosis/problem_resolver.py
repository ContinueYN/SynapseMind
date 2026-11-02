"""Resolve a submitted stem to a servable problem.

A submitted stem always becomes *something* servable:

1. it may be in the annotated catalog — identification is a strict "the
   submission contains the annotated stem" check, so the wrong graph is never
   used; the annotation owns its domain, and an incoming label is only a hint;
2. it may resolve to a domain whose plugin can generate a graph (math /
   physics / chinese) — the graph then goes through the same structure rules,
   schema and claim verification as before;
3. it may resolve to an open domain with no plugin (programming, research,
   decision, work, an unknown label) — Phase 0 serves it as a *reference-free*
   problem: no graph, no card, and the generic intake view. This is the product
   floor, not an error: an unknown domain never becomes a 422.

``SYNAPSE_LLM_MODE=off`` still means "cannot build a graph", so an unseen math
problem is still refused with an explanation. The difference is that the
refusal is now scoped to a *known* domain whose plugin cannot serve it, not to
"we could not classify you".
"""

from __future__ import annotations

import hashlib

from synapse.application.diagnosis.domains import DomainResolver, ResolvedDomain
from synapse.application.diagnosis.generic_graph import (
    GenericGraphBuildFailed,
    GenericGraphDraft,
    GenericGraphGenerator,
)
from synapse.application.diagnosis.graph import GraphBuildFailed
from synapse.application.shared.errors import ProblemNotSupported
from synapse.application.shared.ports import MutableProblemRepository, ProblemRepository
from synapse.application.shared.subject import SubjectPlugin, SubjectRegistry
from synapse.domain.problem.alignment import normalize
from synapse.domain.problem.generic import ClaimCheck
from synapse.domain.problem.models import Problem, ProblemDraft, SolutionGraph

_TITLE_LIMIT = 32
# A reference-free problem carries an explicitly empty graph. The version is
# distinct from generated annotated graphs ("g1") so nothing downstream can
# mistake it for a reviewed or generated structure.
REFERENCE_FREE_GRAPH_VERSION = "g0"


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
        domains: DomainResolver | None = None,
        generic_generator: GenericGraphGenerator | None = None,
    ) -> None:
        self._problems = problems
        self._subjects = subjects
        self._store = store
        self._domains = domains or DomainResolver()
        self._generic_generator = generic_generator

    def resolve(
        self,
        text: str,
        declared_subject: str | None = None,
        *,
        answer: str = "",
        work: str = "",
    ) -> Problem:
        annotated = self._problems.find_for(text)
        if annotated is not None:
            # The annotated graph is reviewed material: it owns its domain. A
            # client-side label is a hint and cannot make the seed a physics
            # problem, but it also must not block the entry.
            return annotated
        if not text.strip():
            raise ProblemNotSupported(_EMPTY)

        resolved = self._domains.resolve(text, declared_subject)
        plugin = self._subjects.for_subject(resolved.name) if self._subjects is not None else None
        if plugin is None:
            return self._reference_free(text, resolved, answer=answer, work=work)
        return self._generate(text, resolved, plugin)

    def _generate(
        self,
        text: str,
        resolved: ResolvedDomain,
        plugin: SubjectPlugin,
    ) -> Problem:
        if self._subjects is None or self._store is None:
            raise ProblemNotSupported(_NO_GENERATOR)

        subject = resolved.name
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
            raise ProblemNotSupported(
                _GENERATION_FAILURES.get(exc.reason, f"建图失败：{exc.reason}")
            ) from exc

        problem = Problem(
            id=problem_id,
            title=_title(text),
            text=text.strip(),
            graph=graph,
            subject=subject,
            annotated=False,
            domain_confidence=resolved.confidence,
            domain_method=resolved.method,
        )
        self._store.add(problem)
        return problem

    def _reference_free(
        self,
        text: str,
        resolved: ResolvedDomain,
        *,
        answer: str = "",
        work: str = "",
    ) -> Problem:
        """Open domain with no plugin yet: keep the label, drop the false graph.

        The empty **solution** graph is a deliberate "no reference structure",
        not a degenerate solution. Phase 1b may attach a *generic* graph beside
        it; that graph has its own contract and never becomes a solution chain.
        A failed generation degrades to the Phase 0 floor instead of a 422.
        """

        if self._store is None:
            # A reference-free problem still has to be registered: the service
            # reloads it by id on every turn and on exit.
            raise ProblemNotSupported(_NO_STORE)
        problem_id = generated_id(text)
        existing = self._problems.get(problem_id)
        if existing is not None:
            return existing

        generic = None
        checks: tuple[ClaimCheck, ...] = ()
        if self._generic_generator is not None:
            draft = GenericGraphDraft(
                id=problem_id,
                text=text.strip(),
                label=resolved.profile.label,
                verification=resolved.profile.verification,
                framework=resolved.profile.framework,
                answer=answer,
                work=work,
            )
            try:
                built = self._generic_generator.generate(draft)
            except GenericGraphBuildFailed:
                # The product floor: an open domain still starts, with the
                # intake view. Losing the structure is better than inventing one.
                pass
            else:
                generic = built.graph
                checks = built.checks

        problem = Problem(
            id=problem_id,
            title=_title(text),
            text=text.strip(),
            graph=SolutionGraph(
                problem_id=problem_id,
                version=REFERENCE_FREE_GRAPH_VERSION,
                stem=text.strip(),
                nodes=(),
                edges=(),
            ),
            subject=resolved.name,
            annotated=False,
            domain_confidence=resolved.confidence,
            domain_method=resolved.method,
            generic=generic,
            generic_checks=checks,
        )
        self._store.add(problem)
        return problem


_EMPTY = "题目文本为空，无法识别或建图"
_NO_GENERATOR = "这道题没有标注解法图，当前环境也不能建图（SYNAPSE_LLM_MODE=off 或缺少 API key）"
_NO_STORE = "当前环境没有题目存储，无法登记这道题；这是部署配置问题，不是题目本身。"
_GENERATION_FAILURES = {
    "timeout": "建图超时：模型没在预算内返回；这道题暂时不能拆成可验证步骤。",
    "transport": "建图服务暂时不可达：这是环境问题，不是题目本身；稍后再试。",
    "bad_json": "建图失败：模型返回的格式不合法；这道题暂时不能拆成可验证步骤。",
    "schema_invalid": "建图失败：生成的步骤不满足结构约束；先不生成卡点。",
    "degenerate": "这道题拆不出足够可验证的步骤；先不生成卡点。",
    "invalid_draft": "建图失败：题目标识不合法；没有生成卡点。",
}


def _title(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _TITLE_LIMIT else f"{flat[:_TITLE_LIMIT]}…"
