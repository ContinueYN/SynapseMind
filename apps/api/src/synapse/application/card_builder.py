"""Build the diagnosis card from a converged hypothesis set."""

from __future__ import annotations

from synapse.domain.diagnosis.models import DiagnosisCard
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem

_ONE_LINE = {
    "H_L2": ("你能走完 a>0 的最值，但没有检查 a≤0：题目要求对所有 x>0 成立，边界也在范围内。"),
    "H_L1": ("你把“对所有 x>0 成立”直接当成了求导，但还没有把它转成“最大值≤0”这个可计算的判定。"),
    "H_L4": ("思路方向是对的，但最值计算/等号处理有一处执行错误；先回代检查临界点。"),
}


def build_diagnosis_card(session: DialogueSession, problem: Problem) -> DiagnosisCard:
    top_id, confidence = session.hypotheses.top()
    top = session.hypotheses.states[top_id].hypothesis
    evidence = list(session.alignment.evidence)
    if session.history:
        last = session.history[-1]
        evidence.append(
            f"第 {last.turn} 轮探针回答支持“{top.label}”假设"
            if not last.is_unknown
            else f"第 {last.turn} 轮说“不知道”，因此降低了对已掌握该步的置信"
        )
    evidence = evidence[:4] or ["本轮证据不足，按当前最高假设出卡"]

    excluded = list(session.alignment.excluded)[:4]
    if not excluded:
        excluded = ["本次探针未支持其他假设"]

    confidence_label = session.hypotheses.confidence_label()
    card = DiagnosisCard(
        version="0.1",
        session_id=session.session_id,
        problem_id=problem.id,
        layer=top.layer,
        label=top.label,
        node_id=top.node_id,
        one_line=_ONE_LINE.get(top.id, "当前最可能卡在这一步，仍需一道迁移题确认。"),
        evidence=tuple(evidence),
        excluded=tuple(excluded),
        confidence=round(confidence, 2),
        confidence_label=confidence_label,
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
    return card
