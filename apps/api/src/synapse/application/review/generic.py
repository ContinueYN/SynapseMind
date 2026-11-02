"""Compose the structure and decision branches of a generic review, without a model.

T0 pinned the product shape in ``domain/problem/generic_review.py``. This module
turns that shape into a review for a writing/research/unknown submission
(structure) or a life/work decision (decision); the execution branch is still
absent (T4).

The composer does not decide what is missing. ``application/diagnosis/generic_check.py``
already did that; its ``StructureGap`` tuple is the input. The job here is to
attach real evidence to each gap and to avoid two failure modes:

* a finding with no evidence. A gap's kind is absent *by definition*, so there
  is no node of that kind to cite. We cite a related existing node (the claim
  that lacks evidence, the two ends of a missing inference step, the assumption
  without a check) and/or the student's own text (``source="student"``,
  ``ref="student"``). A graph node id is only ever copied from the graph; none
  is invented;
* a checklist pretending to be a review. With an empty graph or no attempt at
  all there is nothing to compare, so the review carries ``not_checked`` and one
  follow-up question instead of manufacturing findings.

The decision branch follows the same rule for a different artifact. Options are
copied from the submission's own ``DECISION`` nodes, plus the structural
baseline "什么都不做" if the student did not write it. A cost, risk or reversible
test is attached only when the graph puts it in the *same sentence* as exactly
one option — the graph is flat, so that co-mention is the strongest attribution
the text supports. Anything weaker stays empty and is reported as
``option_without_cost`` / ``option_without_risk`` / ``missing_reversible_test``.
Nothing is scored, ranked or recommended, and a submission with fewer than two
options returns a structure review that says the frame is incomplete instead of
inventing the missing option.

Every sentence is a coverage statement: "没看到…" / "看到了…". There is no
verdict, no score, no recommendation, and no model call. Passing a verification
mode other than ``argumentative`` raises: a structure review is not an honest
shell for a formal, empirical or executable problem.

T5 adds one optional, read-only source: when a ``KnowledgeService`` is wired and
the domain has fixed concept labels, the composer asks retrieval for at most two
cards and attaches them as **top-level** evidence (``source="knowledge"``,
``ref=card id``, ``excerpt=title``). They are not findings, they are not ranked
and they are never fabricated: RAG off, no hit and retrieval failure all leave
the review exactly as it was. The query never contains the student's attempt or
a finding summary — only the resolved domain label and the fixed labels below.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import replace

from synapse.application.diagnosis.domains import IntakeFramework, VerificationMode
from synapse.application.diagnosis.generic_check import StructureGap
from synapse.application.knowledge.service import KnowledgeService
from synapse.domain.knowledge.models import KnowledgeCard
from synapse.domain.problem.generic import GenericGraph, GenericNode, NodeKind
from synapse.domain.problem.generic_review import (
    MAX_EVIDENCE,
    MAX_FINDINGS,
    MAX_NOT_CHECKED,
    MAX_OPTIONS,
    NO_ACTION_OPTION,
    EvidenceSource,
    FindingSeverity,
    GenericEvidence,
    GenericFinding,
    GenericReview,
    ReviewDomain,
    ReviewKind,
    ReviewOption,
    ReviewVerification,
)

_MAX_EXCERPT = 200
_MAX_SUMMARY = 240
_MAX_HEADLINE = 200
_MAX_NEXT_STEP = 240
_MAX_NOT_CHECKED = 240
_MAX_LABEL = 40
_MAX_DOMAIN = 40

_LOGGER = logging.getLogger(__name__)

# At most two cards: a review is a frame, not a reading list. The published
# evidence cap still applies when a decision review already cites many nodes.
_MAX_KNOWLEDGE_HITS = 2

# Fixed concept labels per registered argumentative domain. A retrieval query is
# built only from the resolved domain label plus these labels; the student's
# attempt, ``initial_answer`` and every finding summary stay out of the model.
# An open or unknown label has no entry, so it gets no cards instead of an
# off-domain source: "no source" is honest, a nearby-but-wrong card is not.
_KNOWLEDGE_CONCEPTS: dict[str, str] = {
    "writing": "论证 证据 推理 反方",
    "research": "研究 样本 证据 方法 文献",
    "decision": "决策 目标 约束 选项 代价 风险 可逆实验",
    "work": "决策 目标 约束 选项 代价 风险 可逆实验",
}

# Deliberately no "卡点卡": this product is a structure review, not a diagnosis.
_STRUCTURE_DISCLAIMER = (
    "这是结构复盘：只说明这次提交里写到或没写到哪些结构，不判断观点对错，也不给分。"
)

_NOT_CHECKED_STRUCTURE = (
    "没有判断内容对错；这里只检查这次提交里有没有写到这些结构。",
    "没有核对证据来源是否真实，也没有评价语言、篇幅和段落安排。",
)

_DEFAULT_QUESTION = "先用一句话补上你想解决的目标，好吗？"

# Fallback questions for gaps whose rule table does not carry one (GENERIC).
# They are questions, never advice; each contains exactly one "？".
_QUESTIONS: dict[NodeKind, str] = {
    NodeKind.GOAL: "先用一句话写下目标：这一轮你最想解决或得到什么？",
    NodeKind.GIVEN: "把你手上已有的条件、材料或已知量写一句，好吗？",
    NodeKind.CONSTRAINT: "哪些条件不能动：时间、范围还是关系？",
    NodeKind.ASSUMPTION: "你依赖了哪个假设？写一句就行。",
    NodeKind.PLAN: "从证据到结论之间那一步是什么？",
    NodeKind.ACTION: "你已经试过哪一步，结果如何？",
    NodeKind.EVIDENCE: "有哪些事实、数据或引文在支撑它？",
    NodeKind.CHECK: "什么算「解决了」，或者你打算怎么检查？",
    NodeKind.DECISION: "先摆出两个选项（含「什么都不做」），各写一句。",
    NodeKind.RISK: "最强的反对意见是什么？",
    NodeKind.NEXT: "1–2 周内能先做哪个可逆的小实验？",
}

# Open snake_case labels, per plan §7.2. One gap kind maps to one finding kind;
# the label is the short user-facing name, the summary comes from the gap text.
_GAP_COPY: dict[NodeKind, tuple[str, str]] = {
    NodeKind.GOAL: ("missing_goal", "缺目标"),
    NodeKind.GIVEN: ("missing_given", "缺已知"),
    NodeKind.CONSTRAINT: ("missing_constraint", "缺约束"),
    NodeKind.ASSUMPTION: ("missing_assumption", "缺假设"),
    NodeKind.PLAN: ("reasoning_jump", "推理未写出"),
    NodeKind.ACTION: ("missing_attempt", "缺尝试"),
    NodeKind.EVIDENCE: ("missing_evidence", "缺证据"),
    NodeKind.CHECK: ("missing_check", "缺检查"),
    NodeKind.DECISION: ("missing_options", "缺选项"),
    NodeKind.RISK: ("missing_counter_argument", "缺反方"),
    NodeKind.NEXT: ("missing_next_step", "缺下一步"),
}

# The decision frame reuses the decision rule table but names its gaps after the
# artifact the student will see, not after the writing checklist. These labels are
# open snake_case strings, so no contract bump is needed (plan §7.2).
_DECISION_GAP_COPY: dict[NodeKind, tuple[str, str]] = {
    NodeKind.GOAL: ("missing_goal", "缺目标"),
    NodeKind.CONSTRAINT: ("missing_constraint", "缺约束"),
    NodeKind.DECISION: ("missing_options", "缺选项"),
    NodeKind.RISK: ("missing_cost_or_risk", "缺代价与风险"),
    NodeKind.NEXT: ("missing_reversible_test", "缺可逆实验"),
}

# Deliberately no "卡点卡" and no ranking: this is a decision frame.
_DECISION_DISCLAIMER = (
    "这是决策框：只列选项、代价、风险与可逆实验，不排序、不推荐，也不替你做选择。"
)

_NOT_CHECKED_DECISION = (
    "没有判断哪个选项更好，也没有排序或推荐。",
    "没有核对选项之外的现实信息，比如收入、合同条款或家庭安排。",
    "只记录你写到的代价与风险，没有替你评估它们的大小。",
)

# Same words as the DECISION rule in generic_check.py, so the fallback review and
# the intake checklist do not describe the missing frame differently.
_DECISION_NEEDS_TWO_OPTIONS = "决策框需要至少两个选项（含「什么都不做」），这次{}。"

_MAX_OPTION_LABEL = 80
_MAX_OPTION_ITEM = 80
_MAX_OPTION_TEST = 200
_MAX_TRADEOFF = 300

# A cost/risk/test copied from the text is attributed to an option only when the
# clause and the option share one sentence that names exactly one option. Two
# markers are enough: the cue table already recorded the clause as a RISK node,
# so this only decides whether it reads like a stated cost or an uncertainty.
_RISK_MARKERS = ("风险", "担心", "怕", "隐患", "最坏", "后果", "万一", "副作用")
_COST_MARKERS = ("代价", "成本", "花费", "花钱", "损失", "失去", "牺牲", "占用")

# Options are usually written inside a longer clause ("我在纠结接受 A 还是 B").
# Strip only the deliberation lead-in so the label names the option itself; the
# rest of the sentence is copied verbatim and the full node text stays in
# evidence. Never strip "不" or a content word: that would change the meaning.
_OPTION_LEAD_RE = re.compile(
    r"^(?:"
    r"我(?:现在|目前)?(?:在|还)?(?:要|想|得)?(?:纠结|犹豫|考虑|决定|选择|盘算|权衡)"
    r"|要么|或者|还是|也可以"
    r"|要不要|是否|该不该"
    r"|选择|决定"
    r")"
)
_OPTION_TRIM = " \t\r\n：:，,、"

# Sentences, not clauses: a cost is usually in the same sentence as its option,
# and the Chinese comma often separates the two ("接受北京的工作，代价是异地").
_SENTENCE_SPLIT = re.compile(r"[。！？；!?;\n]+")


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip())


def _option_label(text: str) -> str:
    """The option a DECISION node names, without its deliberation lead-in."""

    label = text.strip(_OPTION_TRIM)
    for _ in range(3):
        stripped = _OPTION_LEAD_RE.sub("", label, count=1).strip(_OPTION_TRIM)
        if stripped == label:
            break
        label = stripped
    if len(label) < 2:
        return _clip(text.strip(_OPTION_TRIM), _MAX_OPTION_LABEL)
    return _clip(label, _MAX_OPTION_LABEL)


def _option_fields(
    *,
    label: str,
    graph: GenericGraph,
    sentences: tuple[str, ...],
    labels: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], str, tuple[GenericNode, ...]]:
    """Copy a sentence's cost/risk/test clauses onto the option it names.

    The graph is flat: no edge says "this risk belongs to that option". The only
    attribution the text supports is co-mention — the clause and the option are
    in the same sentence, and that sentence names exactly one option. When a
    sentence names two options ("要么 A 要么 B，但担心 X") the attribution would
    be a guess, so that sentence contributes nothing and a finding reports the
    empty field. An option can be named in several sentences ("A 还是 B。A 的代价
    是…"), so every unambiguous host sentence is read.
    """

    hosts = [sentence for sentence in sentences if label in sentence]
    if not hosts:
        return (), (), "", ()

    costs: list[str] = []
    risks: list[str] = []
    cited: list[GenericNode] = []
    test = ""
    for sentence in hosts:
        # A sentence that names two options cannot say which one the cost is
        # about; skipping it is the same choice as not copying anything.
        if sum(1 for other in labels if other in sentence) != 1:
            continue
        for node in graph.of_kind(NodeKind.RISK):
            if node.text not in sentence:
                continue
            item = _clip(node.text, _MAX_OPTION_ITEM)
            if item in costs or item in risks:
                continue
            if any(marker in node.text for marker in _RISK_MARKERS) and len(risks) < 2:
                risks.append(item)
                cited.append(node)
            elif any(marker in node.text for marker in _COST_MARKERS) and len(costs) < 2:
                costs.append(item)
                cited.append(node)
        if not test:
            for node in graph.of_kind(NodeKind.NEXT):
                if node.text in sentence:
                    test = _clip(node.text, _MAX_OPTION_TEST)
                    cited.append(node)
                    break
    return tuple(costs), tuple(risks), test, tuple(cited)


def _tradeoff_question(options: tuple[ReviewOption, ...]) -> str:
    """A question about the trade-off, never a recommendation between options."""

    if len(options) == 2:
        left = _clip(options[0].label, 40)
        right = _clip(options[1].label, 40)
        question = (
            f"如果更看重「{left}」，你愿意接受「{right}」的代价吗？"
            f"反过来，如果更看重「{right}」呢？"
        )
    else:
        question = "在列出的几个选项之间，你更看重哪一边；为了那一边，你愿意接受另一边的哪些代价？"
    return _clip(question, _MAX_TRADEOFF)


def _decision_next_step(
    options: tuple[ReviewOption, ...],
    gaps: tuple[StructureGap, ...],
) -> str:
    """Ask for the most useful missing piece, in the same order as the findings."""

    # The synthetic "什么都不做" has no student text behind it, so it cannot be
    # the reason the next step is about a different option.
    named = tuple(option for option in options if NO_ACTION_OPTION not in option.label) or options
    if any(not option.reversible_test for option in named):
        return "先挑一个选项，写一个 1–2 周内能撤回的小实验，好吗？"
    if any(not option.costs for option in named):
        return "挑一个选项，写一句它会让你失去什么，好吗？"
    if any(not option.risks for option in named):
        return "挑一个选项，写一句什么情况会让它变差，好吗？"
    for gap in gaps:
        if gap.kind is NodeKind.CONSTRAINT and gap.question:
            return _clip(gap.question, _MAX_NEXT_STEP)
    return "把每个选项的代价和风险各写一句，再回来看这个取舍问题，好吗？"


def _clip(text: str, limit: int) -> str:
    """Collapse whitespace and fit the published schema's maxLength.

    The schema limits ``headline``, ``summary``, ``next_step``,
    ``not_checked[]`` and ``evidence.excerpt``. Truncating here keeps a generated
    review schema-valid without letting a long node text push the payload out.
    """

    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _first(graph: GenericGraph, kind: NodeKind) -> tuple[GenericNode, ...]:
    return graph.of_kind(kind)[:1]


def _related_nodes(kind: NodeKind | None, graph: GenericGraph) -> tuple[GenericNode, ...]:
    """Existing nodes a missing kind can honestly be tied to.

    The gap kind itself is absent, so this never returns a node of that kind.
    It returns the node(s) the missing piece would connect to, which is why the
    finding can cite a graph ref instead of only the whole submission.
    """

    if kind is NodeKind.EVIDENCE:
        return _first(graph, NodeKind.GOAL) or _first(graph, NodeKind.PLAN)
    if kind is NodeKind.PLAN:
        return _first(graph, NodeKind.GOAL) + _first(graph, NodeKind.EVIDENCE)
    if kind is NodeKind.RISK:
        return _first(graph, NodeKind.GOAL) or _first(graph, NodeKind.EVIDENCE)
    if kind is NodeKind.CHECK:
        return _first(graph, NodeKind.ASSUMPTION) or _first(graph, NodeKind.PLAN)
    if kind in (NodeKind.GIVEN, NodeKind.CONSTRAINT, NodeKind.ACTION):
        return _first(graph, NodeKind.GOAL)
    if kind is NodeKind.GOAL:
        return _first(graph, NodeKind.EVIDENCE) or _first(graph, NodeKind.PLAN)
    if kind in (NodeKind.DECISION, NodeKind.NEXT):
        return _first(graph, NodeKind.GOAL)
    return ()


def _copy_for(
    gap: StructureGap,
    graph: GenericGraph,
    table: Mapping[NodeKind, tuple[str, str]] | None = None,
) -> tuple[str, str]:
    if gap.kind is None:
        return "structure_gap", "结构缺口"
    if gap.kind is NodeKind.CHECK and graph.has(NodeKind.ASSUMPTION):
        return "assumption_without_check", "假设未检查"
    return (table or _GAP_COPY)[gap.kind]


def _first_question(gaps: tuple[StructureGap, ...]) -> str:
    for gap in gaps:
        if gap.question:
            return gap.question
        if gap.kind is not None:
            fallback = _QUESTIONS.get(gap.kind)
            if fallback is not None:
                return fallback
    return _DEFAULT_QUESTION


def _knowledge_query(domain_name: str, domain_label: str) -> str | None:
    """The only query retrieval ever sees for a review.

    ``None`` means this domain has no fixed concept labels (an open or unknown
    label), so no query is made. The labels are constants, not student text.
    """

    concepts = _KNOWLEDGE_CONCEPTS.get(domain_name)
    if concepts is None:
        return None
    return f"{domain_label} {concepts}"


class _EvidencePool:
    """Assign stable local evidence ids as nodes are cited.

    One student item (the submission) plus one item per cited graph node. The
    ids are local to the review (``ev1``…), so no graph node id has to be a
    valid evidence token; the node id lives in ``ref`` where the schema expects
    it.
    """

    def __init__(self) -> None:
        self._items: list[GenericEvidence] = []
        self._by_node: dict[str, GenericEvidence] = {}

    @property
    def items(self) -> tuple[GenericEvidence, ...]:
        return tuple(self._items)

    @property
    def has_room(self) -> bool:
        """False once the published cap would be exceeded by another item."""

        return len(self._items) < MAX_EVIDENCE

    def add_student(self, text: str) -> GenericEvidence | None:
        if not text.strip():
            return None
        evidence = GenericEvidence(
            id=f"ev{len(self._items) + 1}",
            source=EvidenceSource.STUDENT,
            ref="student",
            excerpt=_clip(text, _MAX_EXCERPT),
        )
        self._items.append(evidence)
        return evidence

    def add_node(self, node: GenericNode) -> GenericEvidence:
        existing = self._by_node.get(node.id)
        if existing is not None:
            return existing
        evidence = GenericEvidence(
            id=f"ev{len(self._items) + 1}",
            source=EvidenceSource.GRAPH,
            ref=node.id,
            excerpt=_clip(node.text, _MAX_EXCERPT),
        )
        self._items.append(evidence)
        self._by_node[node.id] = evidence
        return evidence


class GenericReviewComposer:
    """Turn a graph and its gaps into the T0 ``GenericReview``.

    ``framework`` selects the branch: ``DECISION`` composes the decision frame,
    everything else (and the default ``None``) composes the structure review, so
    the T1 callers keep working unchanged. The branch is chosen by the intake
    framework, never by the verification mode — a decision is still
    ``argumentative``.
    """

    def __init__(self, knowledge: KnowledgeService | None = None) -> None:
        """``knowledge`` is optional and read-only.

        It may add sourced cards to the evidence list; it cannot add findings,
        change a finding's refs, or turn a failed/empty lookup into a citation.
        """

        self._knowledge = knowledge

    def compose(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain_name: str,
        domain_label: str,
        verification: VerificationMode,
        graph: GenericGraph,
        gaps: tuple[StructureGap, ...],
        initial_answer: str,
        framework: IntakeFramework | None = None,
    ) -> GenericReview:
        if verification is not VerificationMode.ARGUMENTATIVE:
            raise ValueError(
                "GenericReviewComposer composes the argumentative structure and "
                f"decision branches only; got verification={verification.value!r}"
            )

        domain = ReviewDomain(
            name=_clip(domain_name, _MAX_DOMAIN),
            label=_clip(domain_label, _MAX_DOMAIN),
            verification=ReviewVerification(verification.value),
        )
        attempt = initial_answer.strip()

        if framework is IntakeFramework.DECISION:
            review = self._compose_decision(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
                graph=graph,
                gaps=gaps,
                attempt=attempt,
            )
        elif not attempt:
            return self._without_attempt(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
                gaps=gaps,
            )
        elif not graph.nodes:
            review = self._empty_graph(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
                gaps=gaps,
            )
        elif not gaps:
            review = self._without_gaps(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
            )
        else:
            review = self._with_findings(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
                graph=graph,
                gaps=gaps,
                attempt=attempt,
            )
        # Retrieval is queried only for a real submission. A blank attempt has
        # nothing to compare, so it also gets no card.
        return self._with_knowledge(review, domain=domain, has_attempt=bool(attempt))

    def _with_knowledge(
        self,
        review: GenericReview,
        *,
        domain: ReviewDomain,
        has_attempt: bool,
    ) -> GenericReview:
        """Attach at most two retrieved cards as top-level evidence.

        The cards never become findings: they do not say the student missed or
        got something wrong, and they are not sorted or scored. Every failure is
        a silent skip — disabled RAG, no hit, an unavailable model, or any other
        retrieval error leaves the review byte-identical, with no invented ref.
        """

        if not has_attempt or self._knowledge is None or not self._knowledge.enabled:
            return review
        query = _knowledge_query(domain.name, domain.label)
        if query is None:
            return review
        try:
            result = self._knowledge.search(
                query,
                verification="argumentative",
                limit=_MAX_KNOWLEDGE_HITS,
            )
        except Exception:
            # The query is a constant label, not student text; nothing sensitive
            # is logged, and the review is still served.
            _LOGGER.debug("knowledge lookup skipped; serving the review without cards")
            return review

        room = MAX_EVIDENCE - len(review.evidence)
        if room <= 0:
            return review
        cards: tuple[KnowledgeCard, ...] = tuple(
            hit.card for hit in result.hits[:_MAX_KNOWLEDGE_HITS]
        )
        if not cards:
            return review
        offset = len(review.evidence)
        added = tuple(
            GenericEvidence(
                id=f"ev{offset + index}",
                source=EvidenceSource.KNOWLEDGE,
                ref=card.id,
                excerpt=_clip(card.title, _MAX_EXCERPT),
            )
            for index, card in enumerate(cards[:room], start=1)
        )
        return replace(review, evidence=review.evidence + added)

    def _without_attempt(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain: ReviewDomain,
        gaps: tuple[StructureGap, ...],
    ) -> GenericReview:
        return GenericReview(
            session_id=session_id,
            problem_id=problem_id,
            kind=ReviewKind.STRUCTURE,
            domain=domain,
            headline="还没有可比较的作答文本，先把目标或结论写一句。",
            next_step=_clip(_first_question(gaps), _MAX_NEXT_STEP),
            disclaimer=_STRUCTURE_DISCLAIMER,
            not_checked=(
                "没有提交作答文字，所以没有可比较的结构。",
                "没有判断对错，也没有评分。",
            ),
        )

    def _empty_graph(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain: ReviewDomain,
        gaps: tuple[StructureGap, ...],
    ) -> GenericReview:
        return GenericReview(
            session_id=session_id,
            problem_id=problem_id,
            kind=ReviewKind.STRUCTURE,
            domain=domain,
            headline="这段文字里还没有识别出可用的结构项，先补一个目标或结论。",
            next_step=_clip(_first_question(gaps), _MAX_NEXT_STEP),
            disclaimer=_STRUCTURE_DISCLAIMER,
            not_checked=(
                "没有识别出结构项，所以没有生成带证据的 finding。",
                "没有判断这段文字的观点是否成立，也没有评分。",
            ),
        )

    def _without_gaps(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain: ReviewDomain,
    ) -> GenericReview:
        return GenericReview(
            session_id=session_id,
            problem_id=problem_id,
            kind=ReviewKind.STRUCTURE,
            domain=domain,
            headline="这次提交里没有发现结构缺口；这不等于内容正确。",
            next_step="挑一处最想加强的地方，补一个具体例子或一句反方，再交一次。",
            disclaimer=_STRUCTURE_DISCLAIMER,
            not_checked=(
                "没有发现要补的结构项，但这不代表论点、证据或推理已经成立。",
                "没有判断内容对错，也没有评分。",
            ),
        )

    def _with_findings(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain: ReviewDomain,
        graph: GenericGraph,
        gaps: tuple[StructureGap, ...],
        attempt: str,
    ) -> GenericReview:
        pool = _EvidencePool()
        student = pool.add_student(attempt)
        findings: list[GenericFinding] = []
        skipped: list[str] = []

        for gap in gaps:
            finding = self._finding_for(
                gap=gap,
                graph=graph,
                pool=pool,
                student=student,
                index=len(findings) + 1,
            )
            if finding is None:
                skipped.append(_clip(gap.text, _MAX_NOT_CHECKED))
                continue
            findings.append(finding)

        if not findings:
            return self._empty_graph(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
                gaps=gaps,
            )

        not_checked = list(_NOT_CHECKED_STRUCTURE)
        not_checked.extend(skipped)

        return GenericReview(
            session_id=session_id,
            problem_id=problem_id,
            kind=ReviewKind.STRUCTURE,
            domain=domain,
            headline=(f"看到了部分结构，但还有 {len(findings)} 处没有写到；逐条列在下面。"),
            findings=tuple(findings),
            evidence=pool.items,
            not_checked=tuple(not_checked),
            next_step=_clip(_first_question(gaps), _MAX_NEXT_STEP),
            disclaimer=_STRUCTURE_DISCLAIMER,
        )

    @staticmethod
    def _finding_for(
        *,
        gap: StructureGap,
        graph: GenericGraph,
        pool: _EvidencePool,
        student: GenericEvidence | None,
        index: int,
        copy_table: Mapping[NodeKind, tuple[str, str]] | None = None,
    ) -> GenericFinding | None:
        kind, label = _copy_for(gap, graph, copy_table)

        refs: list[str] = []
        if student is not None:
            refs.append(student.id)
        for node in _related_nodes(gap.kind, graph):
            refs.append(pool.add_node(node).id)
        refs = list(dict.fromkeys(refs))

        if not refs:
            # No evidence at all: the observation belongs in not_checked.
            return None

        return GenericFinding(
            id=f"f{index}",
            kind=kind,
            label=_clip(label, _MAX_LABEL),
            severity=FindingSeverity(gap.severity),
            summary=_clip(gap.text, _MAX_SUMMARY),
            evidence_refs=tuple(refs),
        )

    # --- T2: the decision frame ------------------------------------------------
    #
    # A decision is still argumentative: the product never says which option is
    # better. It shows the options the student wrote, the costs/risks/reversible
    # tests the student wrote next to them, and a finding for every field that is
    # empty. The one option the composer adds is the structural baseline
    # "什么都不做"; it is never decorated with text the student did not write.

    def _compose_decision(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain: ReviewDomain,
        graph: GenericGraph,
        gaps: tuple[StructureGap, ...],
        attempt: str,
    ) -> GenericReview:
        option_nodes = graph.of_kind(NodeKind.DECISION)
        if len(option_nodes) < 2:
            return self._decision_without_two_options(
                session_id=session_id,
                problem_id=problem_id,
                domain=domain,
                graph=graph,
                gaps=gaps,
                attempt=attempt,
                option_count=len(option_nodes),
            )

        labels = tuple(_option_label(node.text) for node in option_nodes)
        sentences = _sentences(attempt)

        pool = _EvidencePool()
        student = pool.add_student(attempt)
        built: list[tuple[ReviewOption, str | None]] = []
        for node, label in zip(option_nodes, labels, strict=True):
            costs, risks, test, cited = _option_fields(
                label=label,
                graph=graph,
                sentences=sentences,
                labels=labels,
            )
            option = ReviewOption(label=label, costs=costs, risks=risks, reversible_test=test)
            built.append((option, pool.add_node(node).id))
            for cited_node in cited:
                if pool.has_room:
                    pool.add_node(cited_node)

        has_no_action = any(NO_ACTION_OPTION in option.label for option, _ in built)
        if has_no_action:
            shown = built[:MAX_OPTIONS]
            if not any(NO_ACTION_OPTION in option.label for option, _ in shown):
                no_action = next(item for item in built if NO_ACTION_OPTION in item[0].label)
                shown = built[: MAX_OPTIONS - 1] + [no_action]
        else:
            shown = built[: MAX_OPTIONS - 1]
        truncated = len(built) > len(shown)

        described = list(shown)
        if not has_no_action:
            described.append(
                (
                    ReviewOption(label=f"{NO_ACTION_OPTION}（先不决定）"),
                    None if student is None else student.id,
                )
            )
        options = tuple(option for option, _ in described)

        findings: list[GenericFinding] = []
        skipped: list[str] = []
        for gap in gaps:
            # The per-option findings below are more precise than these three
            # frame-wide gaps, so the frame-wide version is not repeated.
            if gap.kind in (NodeKind.DECISION, NodeKind.RISK, NodeKind.NEXT):
                continue
            if len(findings) >= MAX_FINDINGS:
                break
            finding = self._finding_for(
                gap=gap,
                graph=graph,
                pool=pool,
                student=student,
                index=len(findings) + 1,
            )
            if finding is None:
                skipped.append(_clip(gap.text, _MAX_NOT_CHECKED))
                continue
            findings.append(finding)

        suppressed = 0
        for option, option_ref in described:
            if option_ref is None:
                # No student text and no node: there is nothing honest to cite.
                continue
            checks = (
                (
                    bool(option.costs),
                    "option_without_cost",
                    "选项缺代价",
                    f"「{option.label}」没有写代价：这个选项会让你失去什么，还没有写。",
                ),
                (
                    bool(option.risks),
                    "option_without_risk",
                    "选项缺风险",
                    f"「{option.label}」没有写风险：什么情况会让它变差，还没有写。",
                ),
                (
                    bool(option.reversible_test),
                    "missing_reversible_test",
                    "缺可逆实验",
                    f"「{option.label}」没有可逆小实验：怎么先用一小步试，还没有写。",
                ),
            )
            for present, kind, label, summary in checks:
                if present:
                    continue
                if len(findings) >= MAX_FINDINGS:
                    suppressed += 1
                    continue
                findings.append(
                    GenericFinding(
                        id=f"f{len(findings) + 1}",
                        kind=kind,
                        label=label,
                        severity=FindingSeverity.NOTABLE,
                        summary=_clip(summary, _MAX_SUMMARY),
                        evidence_refs=(option_ref,),
                    )
                )

        with_cost = sum(1 for option in options if option.costs)
        with_risk = sum(1 for option in options if option.risks)
        with_test = sum(1 for option in options if option.reversible_test)
        headline = (
            f"整理出 {len(options)} 个选项（含「{NO_ACTION_OPTION}」）："
            f"{with_cost} 个写了代价，{with_risk} 个写了风险，{with_test} 个写了可逆实验。"
        )

        not_checked = list(_NOT_CHECKED_DECISION)
        if truncated:
            not_checked.append(
                f"选项超过 {MAX_OPTIONS} 个，这里只展开了 {len(shown)} 个；其余没有逐条展开。"
            )
        if suppressed:
            not_checked.append(f"另有 {suppressed} 条选项缺口没有逐条展开。")
        not_checked.extend(skipped)
        not_checked = not_checked[:MAX_NOT_CHECKED]

        return GenericReview(
            session_id=session_id,
            problem_id=problem_id,
            kind=ReviewKind.DECISION,
            domain=domain,
            headline=_clip(headline, _MAX_HEADLINE),
            findings=tuple(findings),
            evidence=pool.items,
            not_checked=tuple(not_checked),
            next_step=_clip(_decision_next_step(options, gaps), _MAX_NEXT_STEP),
            disclaimer=_DECISION_DISCLAIMER,
            options=options,
            tradeoff_question=_tradeoff_question(options),
        )

    def _decision_without_two_options(
        self,
        *,
        session_id: str,
        problem_id: str,
        domain: ReviewDomain,
        graph: GenericGraph,
        gaps: tuple[StructureGap, ...],
        attempt: str,
        option_count: int,
    ) -> GenericReview:
        """Fewer than two options: say the frame is incomplete, never invent one.

        A second option written by the composer would be the system's preference
        dressed as the student's words, so this returns a structure review with
        the requirement in ``not_checked`` and a question about the second option.
        """

        pool = _EvidencePool()
        student = pool.add_student(attempt)
        findings: list[GenericFinding] = []
        if attempt:
            for gap in gaps:
                finding = self._finding_for(
                    gap=gap,
                    graph=graph,
                    pool=pool,
                    student=student,
                    index=len(findings) + 1,
                    copy_table=_DECISION_GAP_COPY,
                )
                if finding is not None:
                    findings.append(finding)

        if option_count == 0:
            need = _DECISION_NEEDS_TWO_OPTIONS.format("还没有看到选项")
            headline = "这段文字里还没有识别出可比较的选项，先摆出两个（含「什么都不做」）。"
            next_step = "先写出两个选项（含「什么都不做」），各写一句，好吗？"
        else:
            need = _DECISION_NEEDS_TWO_OPTIONS.format(f"只看到 {option_count} 个")
            headline = (
                f"看到了 {option_count} 个选项，但决策框需要至少两个（含「什么都不做」）；"
                "先补第二个。"
            )
            next_step = "先补上第二个选项（含「什么都不做」），各写一句，好吗？"

        return GenericReview(
            session_id=session_id,
            problem_id=problem_id,
            kind=ReviewKind.STRUCTURE,
            domain=domain,
            headline=_clip(headline, _MAX_HEADLINE),
            findings=tuple(findings),
            evidence=pool.items,
            not_checked=(need, *_NOT_CHECKED_DECISION),
            next_step=_clip(next_step, _MAX_NEXT_STEP),
            disclaimer=_STRUCTURE_DISCLAIMER,
        )
