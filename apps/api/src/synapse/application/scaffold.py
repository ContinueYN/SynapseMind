"""Blank-attempt scaffolding: show one or two steps, then ask for the next.

This is the "example fading" entry from the learning-mechanism note: a student
who wrote nothing should not be handed a discriminating probe they cannot
answer. The example is deliberately short (at most two reference steps) and
never includes the final answer. Generated graphs have no reviewed steps, so
they get a generic reading/formula scaffold instead of model-written text.
"""

from __future__ import annotations

from dataclasses import dataclass

from synapse.domain.problem.models import Problem

MAX_SCAFFOLD_STEPS = 2
DISCLAIMER = "示例只展示起步，不是本题答案；写出一行后继续诊断。"

_NEXT_STEP = "照着上面的写法，把你的下一行过程写出来；不用写最终答案。"
_GENERIC_STEPS = (
    "把题目里的已知量和要求量分别写出来。",
    "找出连接已知与要求的公式或定理，写出它的名字。",
    "把已知量代入，先不化简，检查单位或量纲是否对得上。",
)


@dataclass(frozen=True, slots=True)
class ScaffoldStep:
    label: str
    text: str
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class Scaffold:
    steps: tuple[ScaffoldStep, ...]
    focus_node_id: str | None
    next_step: str
    disclaimer: str = DISCLAIMER


def build_scaffold(problem: Problem, level: int) -> Scaffold:
    """Build the example for ``level`` (1 = first step, 2 = first two)."""

    shown = max(1, min(level, MAX_SCAFFOLD_STEPS))
    if problem.annotated and problem.graph.nodes:
        nodes = problem.graph.nodes
        steps = tuple(
            ScaffoldStep(
                label=f"第 {index + 1} 步",
                text=_clip(node.text, 200),
                node_id=node.id,
            )
            for index, node in enumerate(nodes[:shown])
        )
        focus = nodes[shown].id if shown < len(nodes) else None
        return Scaffold(steps=steps, focus_node_id=focus, next_step=_NEXT_STEP)

    steps = tuple(
        ScaffoldStep(label=f"示例 {index + 1}", text=_clip(text, 200))
        for index, text in enumerate(_GENERIC_STEPS[:shown])
    )
    return Scaffold(
        steps=steps,
        focus_node_id=None,
        next_step="先写出第一行：题目给了什么、要求什么。",
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
