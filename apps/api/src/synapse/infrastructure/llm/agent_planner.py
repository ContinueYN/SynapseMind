"""LLM-backed tool planner for the bounded agent trace (Phase 4).

The model sees only system labels: domain, verification mode, the fixed
observed/gaps labels and which whitelisted tools can run. It never sees the
problem statement or the student's attempt. Its entire output contract is one
JSON object with a tool name from the provided list (or ``null``); the runner
still executes the tool through the deterministic rule implementation.

Failure is not repaired into a choice. A timeout, transport error, bad JSON or
an unlisted tool raises :class:`PlannerRejected`; the runner keeps the rule
choice and records ``planner.status=fallback``. A valid ``null`` means "no
opinion" and is also a fallback, not an invented tool.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from synapse.application.diagnosis import trace
from synapse.application.diagnosis.agent_planner import (
    PLANNER_TOOLS,
    AgentPlanningTool,
    PlannerContext,
    PlannerRejected,
)
from synapse.application.shared.audit import AuditEntry, CallAuditor
from synapse.application.shared.llm import (
    LLMCallFailed,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
)
from synapse.infrastructure.llm.settings import LLMSettings

AGENT_PLANNER_MAX_TOKENS = 160
AGENT_PLANNER_CACHE_SIZE = 64

AGENT_PLANNER_SYSTEM_PROMPT = """你是只读工具规划器。你只决定“下一步调用哪一个工具”，
不解题、不判断对错、不推进会话、不读写答案。
硬性要求：
1. 只输出一个 JSON 对象：{"tool": "工具名", "reason": "不超过 20 字"}
   不要 markdown、代码块或解释；不要输出其他字段。
2. tool 只能从用户消息里的“可选工具”中原样选一个。没有合适工具时输出
   {"tool": null}，不要编一个工具名。
3. 只依据领域标签、验证方式、已看到/还缺的结构项和工具可用性做选择。
   不要转述或推测学生原文，不要解题，不要排序、推荐或给出唯一答案。
4. reason 只写选择工具的结构理由，不是诊断结论，不要写“你应该选”。
5. 你不能创建工具，也不能选择运行代码：run_code / run_tests 不在可选列表里。"""

_TOOL_DESCRIPTIONS: dict[AgentPlanningTool, str] = {
    "search_patterns": "查方法/模式知识卡；只作参考，不替代判断",
    "search_sources": "查写作/研究的来源卡；只给有出处的来源",
    "compare_options": "并列选项、约束与代价；不排序，也不替你选",
}


def build_request(context: PlannerContext) -> LLMRequest:
    """One short request built exclusively from system labels."""

    observed = "、".join(context.observed) or "（暂时没有）"
    gaps = "；".join(context.gaps) or "（暂时没有）"
    tool_lines = "\n".join(f"- {tool}：{_TOOL_DESCRIPTIONS[tool]}" for tool in context.tools)
    user = (
        f"领域标签：{context.label}（{context.domain}）\n"
        f"验证方式：{context.verification}\n"
        f"检查框架：{context.framework}\n"
        f"已看到的结构项：{observed}\n"
        f"还缺的结构项：{gaps}\n"
        f"可选工具：\n{tool_lines}\n"
        "请只选择一个下一步工具，输出 JSON。"
    )
    return LLMRequest(
        purpose="agent_plan",
        system=AGENT_PLANNER_SYSTEM_PROMPT,
        user=user,
        schema_name="agent_tool_plan",
        json_schema=None,
        max_tokens=AGENT_PLANNER_MAX_TOKENS,
    )


class LLMToolPlanner:
    def __init__(
        self,
        client: LLMClient,
        *,
        settings: LLMSettings,
        auditor: CallAuditor | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._auditor = auditor
        # Repeated reads of an unchanged intake return the same choice without
        # paying for another call. Only successful choices are cached; a
        # timeout or bad JSON is retried on the next read.
        self._cache: dict[PlannerContext, AgentPlanningTool | None] = {}

    def choose(self, context: PlannerContext) -> AgentPlanningTool | None:
        if not self._settings.llm_enabled:
            raise PlannerRejected("unavailable", "planner requires a live model path")

        if context in self._cache:
            return self._cache[context]
        chosen = self._choose_uncached(context)
        if len(self._cache) >= AGENT_PLANNER_CACHE_SIZE:
            self._cache.clear()
        self._cache[context] = chosen
        return chosen

    def _choose_uncached(self, context: PlannerContext) -> AgentPlanningTool | None:
        request = build_request(context)
        try:
            response = self._client.complete(
                request,
                timeout_s=self._settings.agent_planner_timeout_s,
            )
        except LLMTimeout as exc:
            self._audit(None, schema_ok=False, reason="timeout")
            raise PlannerRejected("timeout", str(exc)) from exc
        except LLMCallFailed as exc:
            self._audit(None, schema_ok=False, reason="transport")
            raise PlannerRejected("transport", str(exc)) from exc

        try:
            chosen = parse_choice(response.text, context.tools)
        except PlannerRejected as exc:
            self._audit(response, schema_ok=False, reason=exc.reason)
            raise
        self._audit(
            response,
            schema_ok=True,
            reason=None if chosen is not None else "no_choice",
            tool=chosen or "",
        )
        return chosen

    def _audit(
        self,
        response: LLMResponse | None,
        *,
        schema_ok: bool,
        reason: str | None,
        tool: str = "",
    ) -> None:
        if self._auditor is None:
            return
        context = trace.current()
        self._auditor.record(
            AuditEntry(
                kind="agent_plan",
                session_id=context.session_id if context else "",
                turn=context.turn if context else 0,
                model=response.model if response else self._settings.model,
                prompt_version=self._settings.agent_planner_prompt_version,
                latency_ms=response.latency_ms if response else 0,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                schema_ok=schema_ok,
                fallback_reason=reason,
                agent_tool=tool,
            )
        )


def parse_choice(
    text: str,
    allowed: Sequence[AgentPlanningTool],
) -> AgentPlanningTool | None:
    """Validate one planner answer; never returns a tool outside ``allowed``."""

    try:
        raw: object = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise PlannerRejected("bad_json", str(exc)) from exc
    if not isinstance(raw, Mapping):
        raise PlannerRejected("bad_json", "response is not a JSON object")

    value = raw.get("tool")
    if value is None:
        return None
    if not isinstance(value, str):
        raise PlannerRejected("bad_json", "tool must be a string or null")
    normalized = value.strip().lower()
    if normalized not in allowed or normalized not in PLANNER_TOOLS:
        raise PlannerRejected("tool_not_allowed", normalized[:40])
    return normalized
