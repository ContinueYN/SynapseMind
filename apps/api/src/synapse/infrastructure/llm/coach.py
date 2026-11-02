"""Optional LLM narrator for the process coach (``coach-v1``).

The model is asked for **process observations only**: what is missing in the
student's reasoning, what to check, and how to start. It never sees
``AnswerStore``, a solution or a correct option; its user message is built from
the problem text, the student's own text and the intake/domain metadata.

Strictness is deliberate:

* one JSON object, validated with Pydantic (extra fields rejected);
* 2–4 points, each with one of the published kind strings and a basis from
  ``problem`` / ``attempt`` / ``intake``;
* a point may only cite ``attempt`` when the student actually wrote something,
  and a blank attempt may not produce ``missing_*`` observations — that would be
  a fabricated diagnosis;
* final-answer, score, rank and ability wording is rejected;
* timeout, transport failure, bad JSON, schema violation or a rejected phrase
  raise :class:`CoachUnavailable`; the application service returns the rule
  result with ``mode="rules"`` and says it fell back.

There is no retry: the coach endpoint is a short, user-triggered call, and a
second long generation would break the 4s budget without adding honesty.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from synapse.application.diagnosis.coach import (
    ALLOWED_POINT_KINDS,
    CoachContext,
    CoachFocus,
    CoachNarrative,
    CoachPoint,
    CoachUnavailable,
    PointKind,
)
from synapse.application.shared.llm import (
    LLMCallFailed,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
)
from synapse.infrastructure.llm.settings import LLMSettings

COACH_PROMPT_VERSION = "coach-v1"
COACH_TIMEOUT_S = 4.0
COACH_MAX_TOKENS = 500
COACH_MAX_PROBLEM_CHARS = 1200
COACH_MAX_ATTEMPT_CHARS = 1400
COACH_MAX_FINDINGS = 6

_BASES = frozenset({"problem", "attempt", "intake"})
_MAX_HEADLINE = 100
_MAX_POINT_TEXT = 160
_MAX_QUESTION = 120

# Assertions, not mentions: "这不是最终答案" is allowed, "答案是" is not.
_FORBIDDEN = (
    "正确答案是",
    "最终答案是",
    "答案是",
    "解法是",
    "得分",
    "评分",
    "能力分",
    "智商",
    "IQ",
    "天赋",
    "排名",
)

# The provider-facing schema mirrors the Pydantic validator; the validator is
# still authoritative because not every provider honors a response schema.
_COACH_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(ALLOWED_POINT_KINDS)},
                    "text": {"type": "string"},
                    "basis": {
                        "type": "string",
                        "enum": ["problem", "attempt", "intake"],
                    },
                },
                "required": ["kind", "text", "basis"],
                "additionalProperties": False,
            },
        },
        "next_question": {"type": "string"},
    },
    "required": ["headline", "points", "next_question"],
    "additionalProperties": False,
}

COACH_SYSTEM_PROMPT = """你是学习过程复盘教练。你只给过程反馈，不给解答。
硬性要求：
1. 只输出一个 JSON 对象，不要 markdown、代码块或解释：
   {"headline": "一句话总览",
    "points": [{"kind": "process_note", "text": "过程观察", "basis": "attempt"}],
    "next_question": "一个以问号结尾的问题"}
2. points 为 2–4 条过程观察。kind 只能是：
   missing_evidence 缺证据 / missing_reasoning 缺推理 / missing_constraint 缺约束 /
   no_attempt 还没有过程 / next_step 下一步 / process_note 过程提示。
3. basis 只能是 problem（题面）/ attempt（学生自己的作答或过程）/ intake（结构整理）。
   引用 attempt 时只能复述学生原话里的短句，不要替学生补写答案。
4. 不要判断对错，不要写“你错了”“正确答案”“最终答案”“解法”，
   不要给分、排名、智力或能力评价。用“你这段过程里，可能是……”“这里缺的是……”这类措辞。
5. 如果学生没有作答或没有写过程：不要编造缺失项（不要用 missing_*），
   改成 no_attempt / next_step，给一个从目标、已知、约束、下一步出发的起步计划。
6. headline 不超过 60 字；每条 text 不超过 120 字；next_question 只问一个问题，以问号结尾。
7. 你只看到题面、学生自己的文字和结构标签；没有答案库，也不要猜答案。"""


class _PointPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    text: str
    basis: str


class _CoachPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    points: list[_PointPayload]
    next_question: str


class LLMCoachNarrator:
    """Provider adapter; the application service owns the fallback decision."""

    def __init__(self, client: LLMClient, *, settings: LLMSettings) -> None:
        self._client = client
        self._settings = settings

    def narrate(self, context: CoachContext, focus: CoachFocus) -> CoachNarrative:
        if not self._settings.llm_enabled or self._settings.mode == "shadow":
            raise CoachUnavailable("unavailable", "coach requires a live model path")

        request = build_request(context, focus)
        try:
            response = self._client.complete(request, timeout_s=COACH_TIMEOUT_S)
        except LLMTimeout as exc:
            raise CoachUnavailable("timeout", str(exc)) from exc
        except LLMCallFailed as exc:
            raise CoachUnavailable("transport", str(exc)) from exc
        return parse_narrative(response, context)


def build_request(context: CoachContext, focus: CoachFocus) -> LLMRequest:
    """Only problem text, the student's own text and structure metadata."""

    findings = context.review.findings if context.review is not None else ()
    finding_lines = "\n".join(
        f"- [{finding.kind}] {finding.summary}" for finding in findings[:COACH_MAX_FINDINGS]
    )
    observed = "、".join(context.observed) or "（暂时没有）"
    gaps = "；".join(context.gaps) or "（暂时没有）"
    checklist = "；".join(context.checklist) or "（暂时没有）"
    attempt = context.attempt_text.strip() or "（没有作答，也没有写过程）"
    question = "我错在哪" if focus == "where_wrong" else "怎么开始"
    user = (
        f"领域标签：{context.domain_label}（{context.domain_name}）\n"
        f"验证方式：{context.verification}\n"
        f"检查框架：{context.framework}\n"
        f"问题：\n{context.problem_text[:COACH_MAX_PROBLEM_CHARS].strip()}\n\n"
        f"学生自己的作答与过程：\n{attempt[:COACH_MAX_ATTEMPT_CHARS]}\n\n"
        f"结构整理已看到：{observed}\n"
        f"结构整理还缺：{gaps}\n"
        f"这个领域的起步清单：{checklist}\n"
        f"已有的结构化复盘发现：\n{finding_lines or '（没有结构化复盘）'}\n\n"
        f"学生这次问的是：{question}。\n"
        "请只输出 JSON。"
    )
    return LLMRequest(
        purpose="coach",
        system=COACH_SYSTEM_PROMPT,
        user=user,
        schema_name="coach_process_feedback",
        json_schema=_COACH_SCHEMA,
        max_tokens=COACH_MAX_TOKENS,
    )


def parse_narrative(response: LLMResponse, context: CoachContext) -> CoachNarrative:
    """Validate one model answer; never repairs it into a fake observation."""

    try:
        raw = json.loads(response.text)
    except (TypeError, ValueError) as exc:
        raise CoachUnavailable("bad_json", str(exc)) from exc
    if not isinstance(raw, dict):
        raise CoachUnavailable("bad_json", "response is not a JSON object")

    try:
        payload = _CoachPayload.model_validate(raw)
    except ValidationError as exc:
        raise CoachUnavailable("schema_invalid", str(exc)) from exc

    headline = payload.headline.strip()
    next_question = payload.next_question.strip()
    if not 1 <= len(headline) <= _MAX_HEADLINE:
        raise CoachUnavailable("schema_invalid", "headline length")
    if not 1 <= len(next_question) <= _MAX_QUESTION:
        raise CoachUnavailable("schema_invalid", "next_question length")
    if not next_question.endswith(("？", "?")):
        raise CoachUnavailable("schema_invalid", "next_question must be a question")
    if not 2 <= len(payload.points) <= 4:
        raise CoachUnavailable("schema_invalid", "2-4 points required")

    points: list[CoachPoint] = []
    for item in payload.points:
        kind = _point_kind(item.kind.strip())
        text = item.text.strip()
        basis = item.basis.strip().lower()
        if basis not in _BASES:
            raise CoachUnavailable("schema_invalid", f"unknown basis: {basis}")
        if not 1 <= len(text) <= _MAX_POINT_TEXT:
            raise CoachUnavailable("schema_invalid", "point text length")
        if basis == "attempt" and not context.has_attempt:
            raise CoachUnavailable("schema_invalid", "attempt basis without an attempt")
        if basis == "intake" and not (context.review or context.gaps or context.checklist):
            raise CoachUnavailable("schema_invalid", "intake basis without intake data")
        if not context.has_attempt and kind.startswith("missing_"):
            raise CoachUnavailable("rejected", "no-attempt diagnosis")
        if _forbidden(headline) or _forbidden(text) or _forbidden(next_question):
            raise CoachUnavailable("rejected", "final-answer or ability wording")
        points.append(
            CoachPoint(
                kind=kind,
                text=text,
                basis=f"llm:{basis}",
            )
        )

    if not context.has_attempt and not any(
        point.kind in {"no_attempt", "next_step"} for point in points
    ):
        raise CoachUnavailable("rejected", "no-attempt plan missing")

    try:
        return CoachNarrative(
            headline=headline,
            points=points,
            next_question=next_question,
        )
    except ValueError as exc:
        raise CoachUnavailable("schema_invalid", str(exc)) from exc


def _forbidden(text: str) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in _FORBIDDEN)


__all__ = [
    "COACH_PROMPT_VERSION",
    "COACH_TIMEOUT_S",
    "COACH_SYSTEM_PROMPT",
    "LLMCoachNarrator",
    "build_request",
    "parse_narrative",
]


def _point_kind(value: str) -> PointKind:
    """Narrowing helper kept next to the validator (mypy-friendly)."""

    for kind in ALLOWED_POINT_KINDS:
        if kind == value:
            return kind
    raise CoachUnavailable("schema_invalid", f"unknown kind: {value}")
