"""The generic intake: what a domain with no reference graph can honestly say.

Phase 0 opened the entry without inventing a generic graph. When a submission has
no annotated graph and no plugin can build one (unknown domain, or
``SYNAPSE_LLM_MODE=off``), the session still starts — but it may only report:

* the resolved domain label and its verification mode;
* a checklist derived from that mode (goal / constraints / reproduction /
  trade-offs…), which is guidance, not a diagnosis;
* **v0.2**: which of those the submission actually *mentions* (``observed``), and
  which required pieces it does not (``gaps``), both computed from the student's
  own words by ``application/generic_slots.py`` + ``generic_check.py``;
* at most one clarifying question when the label was not confident;
* one next step, and a disclaimer naming what was **not** checked;
* **v0.5**: an optional ``review`` (``GenericReview``, contract v0.1) for the
  argumentative modes, composed from the same graph and gaps.

The gap list is still coverage, not correctness: "没看到约束" means the text never
mentions one, never that the constraint is wrong. An empty attempt produces no
gaps at all, because there is nothing to compare; the checklist alone is shown.

The review is composed only when there is an attempt to compare and the mode is
``ARGUMENTATIVE`` (writing/research/decision/generic). A formal, empirical or
executable problem has no honest structure review yet, so it keeps the old
intake untouched. Composition is best-effort: a composer failure is logged and
the intake keeps its previous fields with ``review=None``, rather than letting
the entry return 500 or inventing a ``not_checked`` line.

It must not claim the student missed a step in a *solution*, must not produce a
卡点卡, and for a decision it must not produce a single right answer. Those need
a verifier (Phase 1/2); this module is the honest floor until then.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from synapse.application.domain_detection import MIN_CONFIDENCE
from synapse.application.domains import (
    DomainProfile,
    IntakeFramework,
    VerificationMode,
)
from synapse.application.generic_check import StructureGap, structure_gaps
from synapse.application.generic_review import GenericReviewComposer
from synapse.application.generic_slots import CueSlotExtractor
from synapse.application.knowledge import KnowledgeService
from synapse.domain.problem.generic import (
    KIND_LABELS,
    ClaimCheck,
    ClaimKind,
    ClaimStatus,
    GenericGraph,
    NodeKind,
    NodeSource,
)
from synapse.domain.problem.generic_review import GenericReview
from synapse.domain.problem.models import Problem

VERSION: Literal["0.5"] = "0.5"

_LOGGER = logging.getLogger(__name__)
_REVIEW_COMPOSER = GenericReviewComposer()

# Shown as the closed session's notice so a client that only reads ``notice``
# still learns why there is no card.
INTAKE_NOTICE = "通用模式：这一轮只做结构整理和入口说明，不给出卡点结论。"

# At most three missing pieces at a time: a longer list is a checklist again, and
# the point of ``gaps`` is to name the next thing to write, not to grade.
_MAX_GAPS = 3

# A structural follow-up is one question at a time and stops after three. It is
# not a dialogue ladder: every answer is appended to the same local text and the
# intake is re-derived, so the session never leaves CLOSED and no card appears.
MAX_INTAKE_PROBES = 3

_EXTRACTOR = CueSlotExtractor()

_MODE_LABELS: dict[VerificationMode, str] = {
    VerificationMode.FORMAL: "形式验证",
    VerificationMode.EXECUTABLE: "可执行验证",
    VerificationMode.EMPIRICAL: "经验验证",
    VerificationMode.ARGUMENTATIVE: "论证结构",
}

_CLARIFIER = (
    "只问一个：这更像代码问题、决策问题，还是学习/证明题？"
    "可以在下面补一句；说清是哪一类，就会换到对应的检查方式。"
)

# One question per missing structure kind. They only ask the student to write a
# piece that is absent; none asks for an answer, a verdict or a recommendation.
_GAP_QUESTIONS: dict[NodeKind, str] = {
    NodeKind.GOAL: "先用一句话写下目标：这一轮你最想解决或得到什么？",
    NodeKind.GIVEN: "把你手上已经有的条件、材料或已知量写一句。",
    NodeKind.CONSTRAINT: "哪些条件不能动？写一句时间、范围或关系上的限制。",
    NodeKind.ASSUMPTION: "你依赖了哪个假设？写一句就行。",
    NodeKind.PLAN: "你打算按什么步骤做，或者用了哪条规则、定律？",
    NodeKind.ACTION: "你已经试过哪一步，结果如何？",
    NodeKind.EVIDENCE: "有哪些事实、数据或引文在支撑你的结论？",
    NodeKind.CHECK: "什么算「解决了」，或者你打算怎么检查？",
    NodeKind.DECISION: "先摆出两个选项（含「什么都不做」），各写一句。",
    NodeKind.RISK: "每个选项最怕失去什么？",
    NodeKind.NEXT: "1–2 周内能先做哪个可逆的小实验？",
}

_PROBE_NEXT_STEP = "用下面这一个问题补一句；不用重交整题，也不会判定对错。"


@dataclass(frozen=True, slots=True)
class _IntakeCopy:
    summary: str
    checklist: tuple[str, ...]
    next_step: str
    disclaimer: str


_COPY: dict[IntakeFramework, _IntakeCopy] = {
    IntakeFramework.FORMAL: _IntakeCopy(
        summary="能查的是符号、反例和边界；当前这一轮没有参考结构，所以先不判断卡点。",
        checklist=(
            "目标：最终要证明或求出什么",
            "已知：可用的条件与取值范围",
            "约束：定义域、参数范围、边界情形",
            "尝试：写到哪一步，卡在哪一行",
        ),
        next_step="把条件、目标和你写到的最后一行补全再交一次；有式子就原样贴进来。",
        disclaimer="本节没有做任何符号验证，也没有把这一步判成对或错。",
    ),
    IntakeFramework.EXECUTABLE: _IntakeCopy(
        summary="能跑的验证是可执行验证，但当前环境还没接代码执行，这一节不跑代码。",
        checklist=(
            "目标：这段代码或算法应该做到什么",
            "复现：最小片段、输入和完整报错",
            "预期与实际：你以为什么、实际发生了什么",
            "环境：语言版本、依赖、平台",
            "已试过：改过哪几处，结果如何",
        ),
        next_step="把最小复现和完整 traceback 贴进来再交一次；没跑过的地方会标「未执行」。",
        disclaimer="未执行任何代码；这里只给排查结构，不保证定位到 bug。",
    ),
    IntakeFramework.EMPIRICAL: _IntakeCopy(
        summary="能查的是单位、量纲、数量级和一致性；当前这一轮没有参考结构。",
        checklist=(
            "目标：要解释或预测哪个量",
            "已知：给了哪些量、单位是什么",
            "模型：用了哪条定律或假设，适用条件是什么",
            "检查：量纲、数量级、极端情况",
        ),
        next_step="把已知量、单位和你用的公式写出来再交一次；有数值就带上单位。",
        disclaimer="本节没有校验单位或数值，也不替代真实实验。",
    ),
    IntakeFramework.ARGUMENTATIVE: _IntakeCopy(
        summary="这里只看结构、证据和推理跳跃，不判断观点对错，也不给分数。",
        checklist=(
            "结论：你想让读者接受什么",
            "证据：哪些事实或引文在支撑它",
            "推理：从证据到结论之间，哪一步是跳过去的",
            "反方：最强的反对意见是什么",
            "受众：写给谁、希望他们做什么",
        ),
        next_step="先补上结论和支撑证据各一句，再交一次；缺证据的地方会被标出来。",
        disclaimer="不判断观点对错、不评分、不代写；只说结构缺口。",
    ),
    IntakeFramework.DECISION: _IntakeCopy(
        summary="这是决策问题：不替你选，只把目标、约束、选项、取舍与风险摆开。",
        checklist=(
            "目标：你最看重什么（先只选一个）",
            "约束：时间、钱、关系、不可逆性",
            "选项：至少两个，包含「什么都不做」",
            "代价与风险：每个选项会失去什么",
            "可逆实验：1–2 周内能先试哪一步",
        ),
        next_step="写下最看重的约束和一个可逆的小实验，再交一次；不急着做最终决定。",
        disclaimer="不提供唯一正确答案，也不提供医疗、法律或金融专业建议。",
    ),
    IntakeFramework.GENERIC: _IntakeCopy(
        summary="系统还没有把握把它归到某个领域，先按通用结构理清，不硬贴标签。",
        checklist=(
            "目标：这次希望得到什么结果",
            "已知：手上有哪些材料或事实",
            "约束：哪些条件不能动",
            "尝试：已经试过什么，结果如何",
            "判定：什么算「解决了」",
        ),
        next_step="把这些补成三五句再交一次；确定领域的话，在入口的「领域」里写一个词。",
        disclaimer="通用模式不判断对错，也不生成卡点卡；这是入口整理，不是诊断结论。",
    ),
}


def checklist_for(profile: DomainProfile) -> tuple[str, ...]:
    """The domain's start checklist.

    Shared by the intake card and the coach's "怎么开始" plan so a reference-free
    session with no intake still gets the same goal/known/constraint wording.
    """

    return _COPY[profile.framework].checklist


@dataclass(frozen=True, slots=True)
class IntakeNode:
    """One node of the structure shown on the intake card.

    ``source`` is the honesty label: ``student`` was copied from the submission,
    ``system`` was organised by the model. Neither says the node is correct.
    """

    kind: NodeKind
    label: str
    text: str
    source: NodeSource


@dataclass(frozen=True, slots=True)
class IntakeProbe:
    """One structural follow-up question, not a diagnostic probe.

    It targets a missing node kind (goal, constraint, option…), is answered at
    most ``MAX_INTAKE_PROBES`` times, and never advances the dialogue state.
    """

    kind: NodeKind
    question: str
    answered: int
    limit: int


@dataclass(frozen=True, slots=True)
class IntakeVerification:
    """One verifier's outcome, or ``unknown`` when it never ran."""

    kind: ClaimKind
    status: ClaimStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DomainIntake:
    """The view a reference-free session returns; derived, never stored.

    ``observed``/``gaps`` are computed from the submitted attempt on every read,
    so a reloaded session shows the same words without the snapshot storing them.
    ``graph`` is either the generated structure (system) or the cue extraction
    (student); ``verifications`` exists only for modes that have a verifier.
    ``review`` is the v0.5 optional structure/decision composition; it is absent
    when there is no attempt to compare, when the mode has no honest review, or
    when composition failed.
    """

    version: Literal["0.5"]
    profile: DomainProfile
    confidence: float
    one_line: str
    checklist: tuple[str, ...]
    observed: tuple[str, ...]
    gaps: tuple[str, ...]
    origin: NodeSource | None
    graph: tuple[IntakeNode, ...]
    verifications: tuple[IntakeVerification, ...]
    clarifier: str | None
    probe: IntakeProbe | None
    next_step: str
    disclaimer: str
    review: GenericReview | None = None


_GENERATED_SUMMARY = "系统整理了一张结构图（未验证）；它只说明问题由什么组成，不是诊断结论。"
_GENERATED_DISCLAIMER = "结构图由模型整理、未经人工审核；不判断对错。"
_NO_FORMAL = "没有可验证的形式化声明（需要“恒成立求参数区间”一类问题），本轮未做符号检查。"
_NO_FORMAL_CHECK = "有形式化声明，但这次没有运行形式验证器；不把它当作已检查。"
_NO_EMPIRICAL = "没有结构化方程/单位输入，本轮未做量纲检查。"
_NO_EMPIRICAL_CHECK = "有结构化声明，但这次没有运行经验验证器；不把它当作已检查。"


def build_domain_intake(
    problem: Problem,
    profile: DomainProfile,
    attempt: str = "",
    *,
    session_id: str = "",
    clarifier_answered: bool = False,
    probe_count: int = 0,
    knowledge: KnowledgeService | None = None,
) -> DomainIntake:
    """Compose the intake for a reference-free problem.

    ``problem.domain_confidence`` carries the detector's confidence from intake;
    it decides the single clarifying question, not whether the session may start.
    ``attempt`` is the student's own text; when it is blank no gap is reported,
    because there is nothing to compare and "你什么都没写" is not a finding.
    ``session_id`` is required by the ``GenericReview`` contract; when it is not
    supplied (direct unit calls) no review is composed, because inventing an id
    would make the review claim a session that does not exist.

    A generated graph (``problem.generic``) is displayed separately from
    ``observed``/``gaps``: those two describe the student's words, while the
    generated graph organises the problem. Mixing them would let a model's
    reading masquerade as something the student wrote.

    ``knowledge`` is optional and read-only. When it is a live service, the
    review may add up to two retrieved knowledge cards as top-level evidence;
    when it is absent or disabled, the review is composed exactly as before.
    """

    copy = _COPY[profile.framework]
    confidence = max(0.0, min(1.0, problem.domain_confidence))
    observed: tuple[str, ...] = ()
    structured_gaps: tuple[StructureGap, ...] = ()
    student_graph: GenericGraph | None = None
    if attempt.strip():
        student_graph = _EXTRACTOR.extract(problem.id, attempt)
        observed = tuple(KIND_LABELS[kind] for kind in student_graph.kinds())
        structured_gaps = structure_gaps(profile.framework, student_graph)
    gaps = tuple(gap.text for gap in structured_gaps[:_MAX_GAPS])

    generated = problem.generic
    structure = generated if generated is not None and generated.nodes else student_graph
    if generated is not None and generated.nodes:
        origin: NodeSource | None = "system"
    elif student_graph is not None and student_graph.nodes:
        origin = "student"
    else:
        origin = None

    one_line = f"按「{profile.label}」处理（{_MODE_LABELS[profile.verification]}）。"
    one_line += _GENERATED_SUMMARY if origin == "system" else copy.summary
    disclaimer = copy.disclaimer
    if origin == "system":
        disclaimer += _GENERATED_DISCLAIMER

    clarifier = _CLARIFIER if confidence < MIN_CONFIDENCE and not clarifier_answered else None
    # One question at a time: the domain clarifier comes first, then the first
    # missing structure piece. The count is stored per session, not per read.
    probe = _gap_probe(structured_gaps, probe_count) if clarifier is None else None
    # The review cites node ids, so it reads the same graph the card displays:
    # the generated structure when there is one, the cue extraction otherwise.
    review = _compose_review(
        session_id=session_id,
        problem=problem,
        profile=profile,
        attempt=attempt,
        graph=structure,
        gaps=structured_gaps,
        knowledge=knowledge,
    )
    return DomainIntake(
        version=VERSION,
        profile=profile,
        confidence=confidence,
        one_line=one_line,
        checklist=copy.checklist,
        observed=observed,
        gaps=gaps,
        origin=origin,
        graph=_intake_nodes(structure),
        verifications=_verifications(profile, structure, problem.generic_checks),
        clarifier=clarifier,
        probe=probe,
        next_step=_PROBE_NEXT_STEP if probe is not None else copy.next_step,
        disclaimer=disclaimer,
        review=review,
    )


def _compose_review(
    *,
    session_id: str,
    problem: Problem,
    profile: DomainProfile,
    attempt: str,
    graph: GenericGraph | None,
    gaps: tuple[StructureGap, ...],
    knowledge: KnowledgeService | None = None,
) -> GenericReview | None:
    """Best-effort structure/decision review; never fail the entry over it.

    The composer only knows the argumentative branches, and the contract needs a
    real session id. A formal/empirical/executable problem therefore keeps the
    pre-v0.5 intake with ``review=None``. If composition raises, the intake is
    still served with its old fields; the failure is logged, not rewritten as a
    ``not_checked`` line or a notice. A live ``knowledge`` service is passed only
    to the composer; it cannot change the review's findings or its evidence refs.
    """

    if not session_id or not attempt.strip() or graph is None:
        return None
    if profile.verification is not VerificationMode.ARGUMENTATIVE:
        return None
    # A disabled service keeps the shared composer (and its monkeypatch point);
    # a live one is injected so retrieval can add top-level evidence. Either way
    # the review's findings and refs are composed by the same code.
    composer = (
        GenericReviewComposer(knowledge=knowledge)
        if knowledge is not None and knowledge.enabled
        else _REVIEW_COMPOSER
    )
    try:
        return composer.compose(
            session_id=session_id,
            problem_id=problem.id,
            domain_name=profile.name,
            domain_label=profile.label,
            verification=profile.verification,
            graph=graph,
            gaps=gaps,
            initial_answer=attempt,
            framework=profile.framework,
        )
    except Exception:
        # No student text in the log line: the attempt stays in the session.
        _LOGGER.exception(
            "generic review composition failed; serving the intake without it (session=%s)",
            session_id,
        )
        return None


def _gap_probe(
    gaps: tuple[StructureGap, ...],
    probe_count: int,
) -> IntakeProbe | None:
    """Pick the first answerable gap, unless the three-question budget is used."""

    if probe_count >= MAX_INTAKE_PROBES:
        return None
    for gap in gaps:
        if gap.kind is None:
            continue
        question = gap.question or _GAP_QUESTIONS.get(gap.kind)
        if question is not None:
            return IntakeProbe(
                kind=gap.kind,
                question=question,
                answered=probe_count,
                limit=MAX_INTAKE_PROBES,
            )
    return None


def _intake_nodes(graph: GenericGraph | None) -> tuple[IntakeNode, ...]:
    if graph is None:
        return ()
    return tuple(
        IntakeNode(
            kind=node.kind,
            label=KIND_LABELS[node.kind],
            text=node.text,
            source=node.source,
        )
        for node in graph.nodes
    )


def _verifications(
    profile: DomainProfile,
    graph: GenericGraph | None,
    checks: tuple[ClaimCheck, ...],
) -> tuple[IntakeVerification, ...]:
    """Only the modes with a real verifier get a line; no claim means unknown."""

    stored = {check.kind: check for check in checks}
    results: list[IntakeVerification] = []
    if profile.verification is VerificationMode.FORMAL:
        check = stored.get("formal")
        if check is None:
            check = ClaimCheck(
                kind="formal",
                status="unknown",
                detail=_NO_FORMAL_CHECK if graph is not None and graph.formal else _NO_FORMAL,
            )
        results.append(
            IntakeVerification(kind=check.kind, status=check.status, detail=check.detail)
        )
    elif profile.verification is VerificationMode.EMPIRICAL:
        check = stored.get("empirical")
        if check is None:
            check = ClaimCheck(
                kind="empirical",
                status="unknown",
                detail=(
                    _NO_EMPIRICAL_CHECK if graph is not None and graph.empirical else _NO_EMPIRICAL
                ),
            )
        results.append(
            IntakeVerification(kind=check.kind, status=check.status, detail=check.detail)
        )
    return tuple(results)
