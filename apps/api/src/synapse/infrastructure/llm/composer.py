"""LLM-backed ``ProbeComposer`` (T3).

It lives in ``infrastructure`` although chapter 12 lists ``application/
composer.py``: the import contract forbids ``application`` from importing a
model client, and the composer itself must call one. It implements the same
Protocol, so callers cannot tell the difference.

What the model may change: the wording of ``probe.question``.
What it may not change: options, action, hint level, reason code, state.
"""

from __future__ import annotations

from collections.abc import Mapping

from synapse.application import trace
from synapse.application.audit import AuditEntry, CallAuditor
from synapse.application.composer import CompositionFailed, ProbePrompt
from synapse.application.llm import LLMCallFailed, LLMClient, LLMRequest, LLMResponse, LLMTimeout
from synapse.domain.problem.models import Probe, Problem
from synapse.infrastructure.llm.schema import SchemaRejected, parse_rewrite
from synapse.infrastructure.llm.settings import LLMSettings

SYSTEM_PROMPT = """你是中学数学诊断对话的措辞改写器。唯一任务：把给定问题写得更自然、更像真人老师。
严格遵守：
1. 只输出一个 JSON 对象：{"question": "..."}；
2. question 里恰好一个问号，一句话，不超过 60 个汉字，不含换行；
3. 不得给出答案、答案范围或“所以……”式结论；不得新增、删除或改写选项；
4. 不得要求重解整题，不得引入题目以外的条件；
5. 不写客套话，不称呼学生。"""

_REWRITE_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}

_TONE = {
    0: "直接提问，不给提示",
    1: "给一点方向，但不点破关键条件",
    2: "只问更小的一步，降低难度",
    3: "只确认一个最低门槛",
}


def build_request(
    problem: Problem,
    probe: Probe,
    *,
    hint_level: int,
) -> LLMRequest:
    """Only the stem and the probe are sent.

    ``node.text`` and ``common_errors`` stay out on purpose: they contain the
    reference step ("...所以不满足恒成立") and the misconception label, which
    are exactly what a leaking prompt would reveal.
    """
    options = "\n".join(
        f"{chr(ord('A') + index)}. {option}"
        for index, option in enumerate(probe.options)
    )
    tone = _TONE[min(max(hint_level, 0), 3)]
    user = (
        f"题目：{problem.graph.stem}\n\n"
        f"要改写的问题：{probe.question}\n\n"
        f"选项（不得改动）：\n{options}\n\n"
        f"语气：{tone}"
    )
    return LLMRequest(
        purpose="probe_rewrite",
        system=SYSTEM_PROMPT,
        user=user,
        schema_name="probe_rewrite",
        json_schema=_REWRITE_SCHEMA,
    )


class LLMProbeComposer:
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

    def compose(
        self,
        problem: Problem,
        probe: Probe,
        *,
        confidence: float,
        hint_level: int = 0,
    ) -> ProbePrompt:
        request = build_request(problem, probe, hint_level=hint_level)
        attempts = max(1, self._settings.max_attempts)

        for attempt in range(attempts):
            response = self._call(request, probe)
            try:
                question = parse_rewrite(response.text)
            except SchemaRejected as exc:
                self._audit(
                    probe,
                    response=response,
                    schema_ok=False,
                    retried=attempt > 0,
                    fallback_reason=exc.reason,
                )
                continue
            self._audit(
                probe,
                response=response,
                schema_ok=True,
                retried=attempt > 0,
            )
            return ProbePrompt(
                action="ask" if hint_level == 0 else "hint",
                question=question,
                options=probe.options,
                hint_level=hint_level,
                reason_code="DISCRIMINATE_HYPOTHESIS",
                confidence=round(confidence, 2),
            )

        raise CompositionFailed("schema_invalid", schema_ok=False)

    def _call(self, request: LLMRequest, probe: Probe) -> LLMResponse:
        try:
            return self._client.complete(request, timeout_s=self._settings.timeout_s)
        except LLMTimeout as exc:
            self._audit(probe, schema_ok=False, fallback_reason="timeout")
            raise CompositionFailed("timeout", schema_ok=False) from exc
        except LLMCallFailed as exc:
            self._audit(probe, schema_ok=False, fallback_reason="transport")
            raise CompositionFailed("transport", schema_ok=False) from exc

    def _audit(
        self,
        probe: Probe,
        *,
        response: LLMResponse | None = None,
        schema_ok: bool,
        retried: bool = False,
        fallback_reason: str | None = None,
    ) -> None:
        if self._auditor is None:
            return
        context = trace.current()
        self._auditor.record(
            AuditEntry(
                kind="llm_call",
                session_id=context.session_id if context else "",
                turn=context.turn if context else 0,
                model=response.model if response else self._settings.model,
                prompt_version=self._settings.prompt_version,
                latency_ms=response.latency_ms if response else 0,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                retried=retried,
                fallback_reason=fallback_reason,
                schema_ok=schema_ok,
                probe_id=probe.id,
            )
        )