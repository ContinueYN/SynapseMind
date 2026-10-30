"""Build the structure hint for a NONE-tier subject (M2.5 S7).

The hint is derived, never stored: it is a pure function of the alignment and
the graph, so ``GET /sessions/{id}`` rebuilds the same text without adding a
field to the dialogue aggregate (the state machine stays untouched).

What it may say is bounded by what the aligner can actually see. The aligner is
an *existence* check — did the process mention this step at all, and since S8
did it mention only one clause of a multi-clause step — so the wording reports
"看起来没有写到 / 只写到一部分", and the fixed disclaimer rules out reading it
as "you got this wrong". Hypothesis ids, posteriors and confidence are never
read here; a hint that mentioned them would be a diagnosis in disguise.
"""

from __future__ import annotations

from typing import Literal

from synapse.domain.diagnosis.hint import HintStep, StructureHint
from synapse.domain.dialogue.session import DialogueSession
from synapse.domain.problem.models import Problem

_VERSION: Literal["0.2"] = "0.2"

DISCLAIMER = (
    "该学科没有可自动验证的标准答案：这里只按线索词与分句重合判断"
    "「这一步有没有被写到」或「只写到一部分」，不判断写得对不对，也不定位卡点。"
)


def build_structure_hint(
    session: DialogueSession,
    problem: Problem,
    *,
    level: str,
) -> StructureHint:
    """Describe coverage only; ``focus_node_id`` is where to look next.

    ``partial`` is carried through as its own status rather than folded into
    ``covered``: the point of S8's clause matcher is that "写了前半句" is
    visible without pretending the whole step was done.
    """

    matched_ids = set(session.alignment.matched_node_ids)
    partial_ids = set(session.alignment.partial_node_ids)
    steps = tuple(
        HintStep(
            node_id=node.id,
            text=node.text,
            status=(
                "covered"
                if node.id in matched_ids
                else "partial"
                if node.id in partial_ids
                else "missing"
            ),
        )
        for node in problem.graph.nodes
    )

    total = len(steps)
    focus = next((step for step in steps if step.status != "covered"), None)
    if focus is not None and focus.status == "partial":
        one_line = f"这道题拆成 {total} 步；你的过程里看起来只写到了「{focus.text}」的一部分。"
        next_step = f"先把「{focus.text}」补全，再回来按结构自查。"
    elif focus is not None:
        one_line = f"这道题拆成 {total} 步；你的过程里看起来没有写到「{focus.text}」。"
        next_step = f"先补上「{focus.text}」这一步，再回来按结构自查。"
    else:
        one_line = f"这道题拆成 {total} 步；你的过程里每一步都提到了。"
        next_step = "按顺序对照这些步骤，确认每一步的结论都成立。"

    return StructureHint(
        version=_VERSION,
        session_id=session.session_id,
        problem_id=problem.id,
        subject=problem.subject,
        level=level,
        one_line=one_line,
        steps=steps,
        focus_node_id=focus.node_id if focus is not None else None,
        next_step=next_step,
        disclaimer=DISCLAIMER,
    )
