"""Bounded, read-only tool trace for a generic intake (Phase 4, no state writes).

The trace is not a mind dump and not a diagnosis. It records *which bounded
tools ran*, what they were allowed to see, and a short summary. The first
(``check_structure``) and last (``ask_clarifying``) steps are rule-driven. The
middle step is too, unless an optional planner is wired: it may pick one tool
from a framework-specific whitelist. With ``SYNAPSE_LLM_MODE=off`` (the
default), the planner is not even constructed and the trace is byte-stable
apart from wall-clock durations.

Three boundaries are enforced here rather than left to the UI:

* at most three tools run;
* the answer store is never read and no tool can set dialogue state;
* code is executed only when the caller explicitly submits it to the run
  endpoint, and only for an EXECUTABLE framework. The runner never extracts
  code from the attempt or the problem statement, and ``run_code``/``run_tests``
  are not plannable.

A planner failure never changes the trace into a fake result: the rule choice
runs instead, and the trace says ``mode: rules`` with ``planner.status`` set to
``fallback`` (or ``off`` when the planner was never available).
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from synapse.application.diagnosis.agent_planner import (
    PLANNER_TOOLS,
    AgentPlanningTool,
    PlannerContext,
    PlannerRejected,
    ToolPlanner,
)
from synapse.application.diagnosis.domains import IntakeFramework
from synapse.application.diagnosis.intake import DomainIntake
from synapse.application.execution.service import (
    CodeExecutor,
    ExecutionBusy,
    RunCodeCommand,
)
from synapse.application.knowledge.service import KnowledgeService, KnowledgeUnavailable
from synapse.domain.knowledge.models import KnowledgeHit, KnowledgeKind
from synapse.domain.problem.generic import NodeKind
from synapse.domain.problem.models import Problem

AgentTool = Literal[
    "check_structure",
    "search_patterns",
    "search_sources",
    "compare_options",
    "ask_clarifying",
    "run_code",
    "run_tests",
]
AgentStepStatus = Literal["ok", "skipped", "failed"]
AgentSuggestionKind = Literal["structure", "source", "experiment", "clarify"]
AgentSuggestionSource = Literal["rule", "knowledge", "execution", "system"]
AgentPlannerStatus = Literal["off", "used", "fallback"]

MAX_AGENT_STEPS = 3
_NOTICE = "只读工具轨迹：不推进会话、不判断对错、不替你做选择，也没有读取答案。"
# Why the planner produced no choice. Stable codes, not student-facing copy.
_PLANNER_OFF = "planner_off"


class AgentUnavailable(RuntimeError):
    """The session has no generic intake, so there is nothing for this runner."""


class AgentInputRejected(ValueError):
    """Explicit code was malformed or offered for a non-executable framework."""


@dataclass(frozen=True, slots=True)
class AgentCitation:
    card_id: str
    title: str
    source_title: str
    source_url: str
    license: str


@dataclass(frozen=True, slots=True)
class AgentStep:
    index: int
    tool: AgentTool
    status: AgentStepStatus
    input_summary: str
    output_summary: str
    duration_ms: float
    citations: tuple[AgentCitation, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentSuggestion:
    kind: AgentSuggestionKind
    text: str
    source: AgentSuggestionSource


@dataclass(frozen=True, slots=True)
class AgentLimits:
    max_steps: int
    steps_used: int


@dataclass(frozen=True, slots=True)
class AgentReflection:
    """A two-line review; it reports coverage, not a diagnosis.

    ``focus`` may quote the first system-generated gap. It never quotes the
    student's attempt, ranks an option, or says the work is wrong.
    """

    focus: str
    next: str
    boundary: str


@dataclass(frozen=True, slots=True)
class AgentPlannerState:
    """Which tool the optional planner chose, and whether it was adopted.

    ``tool`` is present only for ``used``. ``fallback`` means a model call was
    attempted but produced no usable choice; ``off`` means it never ran (switch
    off, no key, shadow mode, RAG off, or an explicit-code request).
    """

    status: AgentPlannerStatus
    reason: str
    tool: AgentPlanningTool | None = None


@dataclass(frozen=True, slots=True)
class AgentTrace:
    version: Literal["0.3"]
    session_id: str
    mode: Literal["rules", "llm"]
    planner: AgentPlannerState
    steps: tuple[AgentStep, ...]
    suggestions: tuple[AgentSuggestion, ...]
    reflection: AgentReflection
    limits: AgentLimits
    notice: str


def run_agent_trace(
    session_id: str,
    problem: Problem,
    intake: DomainIntake,
    knowledge: KnowledgeService,
    executor: CodeExecutor | None,
    *,
    planner: ToolPlanner | None = None,
    planner_off_reason: str = _PLANNER_OFF,
    code: str | None = None,
    tests: str | None = None,
) -> AgentTrace:
    """Run at most three read-only tools and return their trace.

    ``code``/``tests`` are accepted only through the explicit run endpoint; a
    caller that does not pass them gets a trace with no execution step.

    ``planner`` is consulted only for the middle step and only when code was
    not explicitly submitted. It never executes anything itself.
    """

    if tests is not None and code is None:
        raise AgentInputRejected("tests require an explicit code submission")
    if code is not None and intake.profile.framework is not IntakeFramework.EXECUTABLE:
        raise AgentInputRejected("explicit code is only accepted for executable frameworks")

    steps: list[AgentStep] = []
    suggestions: list[AgentSuggestion] = []

    _add_check_structure(steps, suggestions, intake)

    if code is not None:
        # The caller already decided what to run; a model must not reorder it.
        planner_state = AgentPlannerState("off", "explicit_code")
        _add_execution(steps, suggestions, executor, code, tests or "")
    else:
        action, planner_state = _plan_action(planner, planner_off_reason, intake, knowledge)
        if action == "compare_options":
            _add_compare_options(steps, suggestions, intake)
        elif action == "search_sources":
            _add_search_sources(steps, suggestions, problem, intake, knowledge)
        else:
            _add_search_patterns(steps, suggestions, problem, intake, knowledge)

    _add_clarifying(steps, suggestions, intake)

    used = planner_state.status == "used"
    return AgentTrace(
        version="0.3",
        session_id=session_id,
        mode="llm" if used else "rules",
        planner=planner_state,
        steps=tuple(steps[:MAX_AGENT_STEPS]),
        suggestions=tuple(suggestions[:MAX_AGENT_STEPS]),
        reflection=_build_reflection(intake, suggestions),
        limits=AgentLimits(
            max_steps=MAX_AGENT_STEPS,
            steps_used=len(steps[:MAX_AGENT_STEPS]),
        ),
        notice=_NOTICE,
    )


def _rule_action(intake: DomainIntake) -> AgentPlanningTool:
    """The existing deterministic choice, unchanged when the planner is off."""

    if intake.profile.framework is IntakeFramework.DECISION:
        return "compare_options"
    if intake.profile.name in {"writing", "research"}:
        return "search_sources"
    return "search_patterns"


def _candidate_tools(
    intake: DomainIntake,
    knowledge: KnowledgeService,
) -> tuple[AgentPlanningTool, ...]:
    """Framework-appropriate tools that can actually produce a step now.

    Retrieval tools are only candidates while RAG is enabled, because the
    planner must not pick a tool whose only possible outcome is ``skipped``.
    ``check_structure``/``ask_clarifying`` are fixed steps and execution tools
    need an explicit submission, so none of them is offered to the planner.
    """

    if intake.profile.framework is IntakeFramework.DECISION:
        tools: tuple[AgentPlanningTool, ...] = ("compare_options",)
        return tools + (("search_patterns",) if knowledge.enabled else ())
    if intake.profile.name in {"writing", "research"}:
        tools = ("search_sources",) if knowledge.enabled else ()
        return tools + (("search_patterns",) if knowledge.enabled else ())
    return ("search_patterns",) if knowledge.enabled else ()


def _plan_action(
    planner: ToolPlanner | None,
    planner_off_reason: str,
    intake: DomainIntake,
    knowledge: KnowledgeService,
) -> tuple[AgentPlanningTool, AgentPlannerState]:
    """Ask the planner for one step, or use the rule choice.

    Every non-``used`` outcome returns the rule choice. The planner is skipped
    entirely when it was never constructed (flag off / no key / shadow), when
    RAG is off, or when no candidate tool could run.
    """

    fallback = _rule_action(intake)
    if planner is None:
        return fallback, AgentPlannerState("off", planner_off_reason)
    if not knowledge.enabled:
        return fallback, AgentPlannerState("off", "rag_off")

    tools = _candidate_tools(intake, knowledge)
    if fallback not in tools:
        # Defensive: the rule choice must stay available even if candidate
        # construction changes, otherwise a model failure could remove a step.
        tools = (fallback, *tools)
    if len(tools) <= 1:
        # Nothing to choose; do not pay for a model round trip.
        return fallback, AgentPlannerState("off", "single_tool")

    context = PlannerContext(
        domain=intake.profile.name,
        label=intake.profile.label,
        verification=intake.profile.verification.value,
        framework=intake.profile.framework.value,
        observed=tuple(intake.observed),
        gaps=tuple(intake.gaps),
        tools=tools,
        decision=intake.profile.framework is IntakeFramework.DECISION,
    )
    try:
        chosen = planner.choose(context)
    except PlannerRejected as exc:
        return fallback, AgentPlannerState("fallback", exc.reason)
    except Exception:  # tool boundary: a broken adapter must not crash the trace
        return fallback, AgentPlannerState("fallback", "unavailable")

    if chosen is None:
        return fallback, AgentPlannerState("fallback", "no_choice")
    if chosen not in tools or chosen not in PLANNER_TOOLS:
        return fallback, AgentPlannerState("fallback", "tool_not_allowed")
    return chosen, AgentPlannerState("used", "selected", chosen)


def _build_reflection(
    intake: DomainIntake,
    suggestions: list[AgentSuggestion],
) -> AgentReflection:
    if intake.clarifier:
        focus = "领域标签还不够确定；先回答一个澄清问题，再谈结构。"
    elif intake.gaps:
        focus = f"目前最明显的结构缺口：{intake.gaps[0]}"
    else:
        focus = "这一轮没有看到结构缺口；这只说明表达覆盖，不是诊断结论。"

    action = next((item.text for item in suggestions if item.kind != "structure"), "")
    next_step = action or intake.next_step
    return AgentReflection(
        focus=_clip(focus),
        next=_clip(next_step),
        boundary="复盘只引用结构缺口与工具状态；不判断对错，不替你做选择。",
    )


def _add_check_structure(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    intake: DomainIntake,
) -> None:
    started = perf_counter()
    observed = len(intake.observed)
    gaps = intake.gaps
    if not observed and not gaps:
        status: AgentStepStatus = "skipped"
        summary = "入口里还没有可检查的结构；先写一句你遇到什么。"
    else:
        status = "ok"
        summary = f"看到 {observed} 项结构，缺口 {len(gaps)} 个；缺口只说明没写到，不判断对错。"
    if gaps:
        suggestions.append(AgentSuggestion("structure", _clip(gaps[0]), "rule"))
    steps.append(
        AgentStep(
            index=len(steps) + 1,
            tool="check_structure",
            status=status,
            input_summary=(
                f"domain={intake.profile.name}; "
                f"verification={intake.profile.verification.value}; intake=generic"
            ),
            output_summary=summary,
            duration_ms=_elapsed_ms(started),
        )
    )


def _add_search_patterns(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    problem: Problem,
    intake: DomainIntake,
    knowledge: KnowledgeService,
) -> None:
    _add_knowledge_search(
        steps,
        suggestions,
        problem,
        intake,
        knowledge,
        tool="search_patterns",
        kind=None,
        source_only=False,
        query_suffix="方法 模式 检查",
        limit=2,
        no_rag="RAG 未开启；本轮没有外部知识卡，也不伪造引用。",
        empty="没有命中的知识卡；本轮不伪造引用。",
        found="检索到 {count} 张卡；只作参考，不替代你的判断。",
        suggestion="可参考：{title}（{source}）",
    )


def _add_search_sources(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    problem: Problem,
    intake: DomainIntake,
    knowledge: KnowledgeService,
) -> None:
    _add_knowledge_search(
        steps,
        suggestions,
        problem,
        intake,
        knowledge,
        tool="search_sources",
        kind="source",
        source_only=True,
        query_suffix="原始来源 论文 文献",
        limit=8,
        no_rag="RAG 未开启；本轮没有外部来源，也不伪造引用。",
        empty="没有命中来源卡；本轮不伪造引用。",
        found="检索到 {count} 个来源；只作参考，不替代你的判断。",
        suggestion="可参考来源：{source}（{title}）",
    )


def _add_knowledge_search(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    problem: Problem,
    intake: DomainIntake,
    knowledge: KnowledgeService,
    *,
    tool: Literal["search_patterns", "search_sources"],
    kind: KnowledgeKind | None,
    source_only: bool,
    query_suffix: str,
    limit: int,
    no_rag: str,
    empty: str,
    found: str,
    suggestion: str,
) -> None:
    started = perf_counter()
    if not knowledge.enabled:
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool=tool,
                status="skipped",
                input_summary=f"domain={intake.profile.name}; rag=off",
                output_summary=no_rag,
                duration_ms=_elapsed_ms(started),
            )
        )
        return

    subject = None if problem.subject == "generic" else problem.subject
    query = f"{intake.profile.label} {query_suffix}"
    try:
        result = knowledge.search(
            query,
            subject=subject,
            verification=intake.profile.verification.value,
            kind=kind,
            limit=limit,
        )
    except KnowledgeUnavailable:
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool=tool,
                status="failed",
                input_summary=f"domain={intake.profile.name}; query=concept-label",
                output_summary="检索运行时不可用；本轮没有引用，以下只保留结构线索。",
                duration_ms=_elapsed_ms(started),
            )
        )
        suggestions.append(
            AgentSuggestion(
                "source",
                "本轮没有可用的知识卡；不要把系统推断当成引用。",
                "system",
            )
        )
        return

    hits = (
        tuple(hit for hit in result.hits if hit.card.kind == "source")
        if source_only
        else result.hits
    )
    citations = tuple(_citation(hit) for hit in hits[:3])
    if not citations:
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool=tool,
                status="skipped",
                input_summary=f"domain={intake.profile.name}; query=concept-label",
                output_summary=empty,
                duration_ms=_elapsed_ms(started),
            )
        )
        return

    first = hits[0].card
    steps.append(
        AgentStep(
            index=len(steps) + 1,
            tool=tool,
            status="ok",
            input_summary=f"domain={intake.profile.name}; query=concept-label",
            output_summary=found.format(count=len(citations)),
            duration_ms=_elapsed_ms(started),
            citations=citations,
        )
    )
    suggestions.append(
        AgentSuggestion(
            "source",
            _clip(suggestion.format(title=first.title, source=first.source.title)),
            "knowledge",
        )
    )


def _add_compare_options(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    intake: DomainIntake,
) -> None:
    started = perf_counter()
    options = sum(1 for node in intake.graph if node.kind is NodeKind.DECISION)
    constraints = sum(1 for node in intake.graph if node.kind is NodeKind.CONSTRAINT)
    risks = sum(1 for node in intake.graph if node.kind is NodeKind.RISK)
    status: AgentStepStatus = "ok" if options >= 2 else "skipped"
    summary = (
        f"读到 {options} 个选项、{constraints} 条约束、{risks} 条代价；只并列，不排序，也不替你选。"
    )
    if options < 2:
        summary = "只读到少于两个选项；决策至少需要两个，含「什么都不做」。"
        suggestions.append(
            AgentSuggestion(
                "structure",
                "先至少摆出两个选项（含「什么都不做」），各写一句。",
                "rule",
            )
        )
    else:
        suggestions.append(
            AgentSuggestion(
                "experiment",
                "把每个选项在时间、钱、关系、不可逆性上各写一句；系统不替你排序。",
                "rule",
            )
        )
    steps.append(
        AgentStep(
            index=len(steps) + 1,
            tool="compare_options",
            status=status,
            input_summary=f"domain={intake.profile.name}; framework=decision",
            output_summary=summary,
            duration_ms=_elapsed_ms(started),
        )
    )


def _add_clarifying(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    intake: DomainIntake,
) -> None:
    started = perf_counter()
    if intake.probe is not None:
        question = intake.probe.question
        detail = (
            f"kind={intake.probe.kind.value}; answered={intake.probe.answered}/{intake.probe.limit}"
        )
        summary = "入口还有一个结构问题；一次只问一个，不推进会话。"
    elif intake.clarifier is not None:
        question = intake.clarifier
        detail = "clarifier=open"
        summary = "入口还有一个领域澄清问题；先回答它，再整理结构。"
    else:
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool="ask_clarifying",
                status="skipped",
                input_summary="questions=0",
                output_summary="没有待补的问题；不重复追问。",
                duration_ms=_elapsed_ms(started),
            )
        )
        return

    suggestions.append(AgentSuggestion("clarify", _clip(f"先回答：{question}"), "system"))
    steps.append(
        AgentStep(
            index=len(steps) + 1,
            tool="ask_clarifying",
            status="ok",
            input_summary=detail,
            output_summary=summary,
            duration_ms=_elapsed_ms(started),
        )
    )


def _add_execution(
    steps: list[AgentStep],
    suggestions: list[AgentSuggestion],
    executor: CodeExecutor | None,
    code: str,
    tests: str,
) -> None:
    started = perf_counter()
    tool: AgentTool = "run_tests" if tests else "run_code"
    input_summary = (
        f"language=python; code_chars={len(code)}; tests_chars={len(tests)}; explicit=true"
    )
    if executor is None:
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool=tool,
                status="skipped",
                input_summary=input_summary,
                output_summary="执行开关关闭：没有运行代码，也不把未运行当作通过。",
                duration_ms=_elapsed_ms(started),
            )
        )
        suggestions.append(
            AgentSuggestion(
                "experiment",
                "需要复现时，显式开启 SYNAPSE_EXEC=on 后再提交同一段代码；本轮未执行。",
                "system",
            )
        )
        return

    try:
        result = executor.run(RunCodeCommand(language="python", code=code, tests=tests))
    except ExecutionBusy:
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool=tool,
                status="failed",
                input_summary=input_summary,
                output_summary="执行槽被占用；代码没有运行，不据此判断对错。",
                duration_ms=_elapsed_ms(started),
            )
        )
        suggestions.append(
            AgentSuggestion(
                "experiment",
                "稍后重试；本轮没有执行，也没有产生运行结果。",
                "system",
            )
        )
        return
    except Exception as exc:  # tool boundary: a broken adapter must not crash the trace
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                tool=tool,
                status="failed",
                input_summary=input_summary,
                output_summary=(f"执行器失败（{type(exc).__name__}）；这次没有完成可解释的运行。"),
                duration_ms=_elapsed_ms(started),
            )
        )
        suggestions.append(
            AgentSuggestion(
                "experiment",
                "这次没有拿到运行结果；先检查执行器状态，不要把失败当成代码诊断。",
                "system",
            )
        )
        return

    summary = (
        f"运行状态={result.status}；退出码={result.exit_code}；"
        f"执行器耗时={result.duration_ms}ms；"
        f"stdout {len(result.stdout)} 字符，stderr {len(result.stderr)} 字符。"
    )
    if result.truncated:
        summary += " 输出已截断。"
    if result.detail:
        summary += f" {result.detail}"
    if result.stdout.strip():
        summary += f" stdout 摘要：{result.stdout.strip()}"
    if result.stderr.strip():
        summary += f" stderr 摘要：{result.stderr.strip()}"
    if result.findings:
        summary += " findings=" + ",".join(item.code for item in result.findings)

    steps.append(
        AgentStep(
            index=len(steps) + 1,
            tool=tool,
            status="ok",
            input_summary=input_summary,
            output_summary=summary[:600],
            duration_ms=_elapsed_ms(started),
        )
    )

    if result.status == "pass":
        text = "这次运行通过了；只说明这次输入/测试通过，不说明代码正确。"
    elif result.status == "fail":
        text = "先看失败断言或第一个异常，把输入缩到最小；这次运行不是最终判定。"
    elif result.status == "timeout":
        text = "运行超时；先缩小输入或加日志，不能据此判断对错。"
    else:
        text = "执行被静态闸门拒绝，代码没有运行；先移除被禁止的导入或调用。"
    suggestions.append(AgentSuggestion("experiment", text, "execution"))


def _citation(hit: KnowledgeHit) -> AgentCitation:
    card = hit.card
    return AgentCitation(
        card_id=card.id,
        title=card.title,
        source_title=card.source.title,
        source_url=card.source.url,
        license=card.source.license,
    )


def _clip(text: str, limit: int = 300) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 1)
