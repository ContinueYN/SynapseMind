"""Optional LLM tool planner port (Phase 4, second slice).

The planner chooses **one** tool: the middle step of the bounded trace. The
first step (``check_structure``) and the last step (``ask_clarifying``) stay
rule-driven, and only the runner executes the chosen tool through the same
rule implementation. The planner therefore cannot:

* add or remove steps, or raise the three-step cap;
* change the session, the diagnosis, the probe budget or the answer store;
* choose ``get_answer``/``set_state`` or any tool outside the whitelist;
* submit code: ``run_code``/``run_tests`` are deliberately not plannable, since
  execution only happens for code the caller explicitly pastes;
* see the student's text. The context carries system labels (domain,
  verification mode, observed/gaps from a fixed table) and tool availability.

A model answer is a *suggestion*, never an authority: the runner falls back to
the existing rule choice on timeout, bad JSON, an illegal tool, RAG being off,
or a missing key. Nothing here writes state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

AgentPlanningTool = Literal[
    "search_patterns",
    "search_sources",
    "compare_options",
]

# The only tools a planner may ever pick. ``check_structure`` and
# ``ask_clarifying`` are fixed rule steps, and the execution tools require an
# explicit caller submission, so they are not in this set.
PLANNER_TOOLS: tuple[AgentPlanningTool, ...] = (
    "search_patterns",
    "search_sources",
    "compare_options",
)

PlannerFailureReason = Literal[
    "timeout",
    "transport",
    "bad_json",
    "tool_not_allowed",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class PlannerContext:
    """What the planner is allowed to know.

    Every field is a system label or a fixed-table phrase. The student's
    problem statement and attempt are not part of this contract, so an adapter
    cannot forward them by accident.
    """

    domain: str
    label: str
    verification: str
    framework: str
    observed: tuple[str, ...]
    gaps: tuple[str, ...]
    tools: tuple[AgentPlanningTool, ...]
    decision: bool


class PlannerRejected(RuntimeError):
    """The planner produced no usable choice; the runner must use the rules.

    ``reason`` is a stable code for the trace/audit, not a student-facing
    sentence. ``detail`` is for the audit log and never includes student text.
    """

    def __init__(self, reason: PlannerFailureReason, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


class ToolPlanner(Protocol):
    """A model may suggest one whitelisted tool, or nothing (``None``)."""

    def choose(self, context: PlannerContext) -> AgentPlanningTool | None: ...
