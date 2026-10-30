"""Build the diagnosis card from a converged hypothesis set.

Two shapes, one entry point:

* an **annotated** problem has a reviewed reference solution, so the card may
  make a specific claim about which step the student skipped (``_ONE_LINE``);
* a **generated** problem (M2.5 S5 ②) has no reviewed reference, so the card is
  built from what actually happened in the dialogue: the probe answer that
  moved the posterior, the node it belongs to, and the node's own text. When
  there is no such evidence the wording falls back to "no step for this",
  never to a canned misconception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from synapse.domain.diagnosis.models import DiagnosisCard, Layer
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem, SolutionNode

_FALLBACK_ONE_LINE = "当前最可能卡在这一步，仍需一道迁移题确认。"
_ONE_LINE_MAX = 200  # CardOut.one_line is capped at 200 characters
_FORMULA_MAX = 80


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _work_one_line(session: DialogueSession) -> str:
    """One sentence quoting the student's own broken equals sign, or ``""``.

    Empty unless the equality-check flag put a finding on the session, so the
    flag-off baseline never reaches this function's output.
    """

    if not session.work_findings:
        return ""
    finding = session.work_findings[0]
    formula = _clip(f"{finding.left} = {finding.right}", _FORMULA_MAX)
    summary = finding.summary or finding.counterexample
    sentence = f"你写的「{formula}」这一步等号不成立"
    if summary:
        sentence += f"：{summary}"
    return _clip(sentence + "。", _ONE_LINE_MAX)


def _work_evidence(session: DialogueSession, limit: int = 2) -> tuple[str, ...]:
    """The student's formula plus the concrete numbers behind the claim."""

    lines: list[str] = []
    for finding in session.work_findings[:limit]:
        detail = finding.summary or finding.counterexample
        line = f"等式：{finding.left} = {finding.right}"
        if detail:
            line += f"；{detail}"
        lines.append(line)
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class _Head:
    top_id: str
    label: str
    layer: Layer
    confidence: float
    confidence_label: Literal["high", "medium", "low"]


_ONE_LINE = {
    "H_L2": (
        "你能走完 a>0 的最值，但没有检查 a≤0：题目要求对所有 x>0 成立，a≤0 这一支必须单独排除。"
    ),
    "H_L1": ("你把“对所有 x>0 成立”直接当成了求导，但还没有把它转成“最大值≤0”这个可计算的判定。"),
    "H_L4": ("思路方向是对的，但最值计算/等号处理有一处执行错误；先回代检查临界点。"),
}


def build_diagnosis_card(session: DialogueSession, problem: Problem) -> DiagnosisCard:
    if problem.annotated:
        return _annotated_card(session, problem)
    return _generated_card(session, problem)


def _common(session: DialogueSession, problem: Problem) -> _Head:
    """The head every card shares: which hypothesis won, and how sure we are."""

    del problem  # kept in the signature so both branches read the same way
    top_id, confidence = session.hypotheses.top()
    top = session.hypotheses.states[top_id].hypothesis
    return _Head(
        top_id=top_id,
        label=top.label,
        layer=top.layer,
        confidence=confidence,
        confidence_label=session.hypotheses.confidence_label(),
    )


def _evidence_lines(
    session: DialogueSession,
    *,
    leading: tuple[str, ...] = (),
    extra: tuple[str, ...] = (),
) -> tuple[str, ...]:
    evidence = list(leading)
    evidence.extend(session.evidence.latest("probe", limit=1))
    evidence.extend(session.evidence.claims(limit=3))
    evidence.extend(extra)
    evidence = list(dict.fromkeys(evidence))[:4]
    return tuple(evidence) or ("本轮证据不足，按当前最高假设出卡",)


def _excluded_lines(session: DialogueSession) -> tuple[str, ...]:
    excluded = list(session.alignment.excluded)[:4]
    return tuple(excluded) or ("本次探针未支持其他假设",)


def _annotated_card(session: DialogueSession, problem: Problem) -> DiagnosisCard:
    head = _common(session, problem)
    return DiagnosisCard(
        version="0.1",
        session_id=session.session_id,
        problem_id=problem.id,
        layer=head.layer,
        label=head.label,
        node_id=session.hypotheses.states[head.top_id].hypothesis.node_id,
        one_line=_work_one_line(session) or _ONE_LINE.get(head.top_id, _FALLBACK_ONE_LINE),
        evidence=_evidence_lines(session, leading=_work_evidence(session)),
        excluded=_excluded_lines(session),
        confidence=round(head.confidence, 2),
        confidence_label=head.confidence_label,
        next_action={
            "type": "micro_lesson",
            "concept_id": "param_case",
            "duration_min": 3,
            "task_id": "T_FUNC_001",
        },
        verify={
            "type": "transfer",
            "due_hours": 24,
            "item_id": "V_FUNC_001",
        },
        disagree=False,
    )


def _generated_card(session: DialogueSession, problem: Problem) -> DiagnosisCard:
    head = _common(session, problem)
    graph = problem.graph
    node, option_text = _decisive_turn(session, problem, head.top_id)
    if node is None:
        node = _alignment_node(session, problem)

    if node is None:
        one_line = _FALLBACK_ONE_LINE
        node_id = graph.nodes[0].id if graph.nodes else ""
        evidence = _evidence_lines(session, leading=_work_evidence(session))
    elif option_text:
        one_line = (
            f"你在「{node.text}」这一步选了「{option_text}」，"
            f"这道题更像是「{head.label}」层面的问题。"
        )
        node_id = node.id
        evidence = _evidence_lines(session, leading=_work_evidence(session))
    else:
        # Alignment only notices *omitted* steps, so the card must say exactly
        # that: the process does not show this step, not "you got it wrong".
        one_line = f"你的过程里没有出现「{node.text}」这一步，先回到这里确认，再往下走。"
        node_id = node.id
        evidence = _evidence_lines(
            session,
            leading=_work_evidence(session),
            extra=(f"对齐：{node.text}",),
        )

    # A proved broken equals sign is more specific than "this step is missing";
    # it becomes the one-line conclusion, with the formula kept in evidence.
    one_line = _work_one_line(session) or one_line

    return DiagnosisCard(
        version="0.1",
        session_id=session.session_id,
        problem_id=problem.id,
        layer=head.layer,
        label=head.label,
        node_id=node_id,
        one_line=one_line,
        evidence=evidence,
        excluded=_excluded_lines(session),
        confidence=round(head.confidence, 2),
        confidence_label=head.confidence_label,
        next_action={
            "type": "micro_lesson",
            "concept_id": f"node:{node_id}",
            "duration_min": 3,
            "task_id": f"node:{node_id}",
        },
        verify={
            "type": "transfer",
            "due_hours": 24,
            "item_id": f"verify:{problem.id}",
        },
        disagree=False,
    )


def _decisive_turn(
    session: DialogueSession, problem: Problem, top_id: str
) -> tuple[SolutionNode | None, str]:
    """The last answered probe that positively supported the top hypothesis.

    Returns the node it belongs to and the option text the student chose. This
    is what makes a generated card specific without inventing anything: the
    wording quotes the student's own choice.
    """

    for record in reversed(session.history):
        if record.option_id is None or record.is_unknown:
            continue
        if top_id not in session.hypotheses.supported_by(record.probe_id, record.option_id):
            continue
        try:
            probe = problem.graph.probe(record.probe_id)
        except KeyError:
            continue
        index = "ABCD".find(record.option_id)
        if not 0 <= index < len(probe.options):
            continue
        node = _node_of(problem, record.probe_id)
        if node is None:
            continue
        return node, probe.options[index]
    return None, ""


def _alignment_node(session: DialogueSession, problem: Problem) -> SolutionNode | None:
    divergence = session.alignment.first_divergence
    for node in problem.graph.nodes:
        if node.id == divergence:
            return node
    return None


def _node_of(problem: Problem, probe_id: str) -> SolutionNode | None:
    for node in problem.graph.nodes:
        if any(probe.id == probe_id for probe in node.probes):
            return node
    return None
