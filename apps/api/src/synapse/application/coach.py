"""The "问 AI：我错在哪 / 怎么开始" coach: process feedback, never a solution.

The coach exists for the two moments the rest of the product cannot serve well:
a student who already wrote something and wants a second pair of eyes, and a
student who has not started at all. It is deliberately not a tutor:

* it gives **process** feedback (what is missing, what to check, where to start)
  and never a final answer, a solution, a score, a rank, a diagnosis or a claim
  about the student's ability;
* it never reads or reveals ``AnswerStore``: this module has no answer port and
  the request it builds carries only the problem text, the student's own text and
  the domain/structure metadata;
* it does not claim "you are wrong". There is no correctness check on this path,
  so the wording is "你这段过程里，可能是……" / "这里缺的是……" and every result
  carries a non-empty ``not_claimed`` list;
* with no model configured it is a deterministic rule-based coach (``mode:
  "rules"``). With a live model it may be ``mode: "llm"``; a timeout, transport
  error, invalid JSON or rejected content is not repaired into a fake model
  answer, it falls back to the rule result and says so in the disclaimer.

The point kinds are a small, stable vocabulary (see ``ALLOWED_POINT_KINDS``):
``missing_evidence``, ``missing_reasoning``, ``missing_constraint``,
``no_attempt``, ``next_step`` and ``process_note``. They describe the process,
not the person.

This module imports no FastAPI, no SQL, no provider SDK and no answer store. The
optional model adapter is an infrastructure implementation of ``CoachNarrator``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from synapse.application.domains import DomainProfile
from synapse.domain.problem.generic_review import GenericFinding, GenericReview

_LOGGER = logging.getLogger(__name__)

VERSION: Literal["0.1"] = "0.1"

CoachFocus = Literal["where_wrong", "how_to_start"]
CoachMode = Literal["rules", "llm"]
PointKind = Literal[
    "missing_evidence",
    "missing_reasoning",
    "missing_constraint",
    "no_attempt",
    "next_step",
    "process_note",
]

ALLOWED_FOCUSES: tuple[CoachFocus, ...] = ("where_wrong", "how_to_start")
# Stable wire vocabulary. Adding a kind is a contract change; the UI has a label
# table for exactly these strings.
ALLOWED_POINT_KINDS: tuple[PointKind, ...] = (
    "missing_evidence",
    "missing_reasoning",
    "missing_constraint",
    "no_attempt",
    "next_step",
    "process_note",
)

# Reason codes for the honest degradation. The API never turns one of these into
# a 500 and never hides it: the result says it fell back to the rule coach.
CoachFallbackReason = Literal[
    "timeout",
    "transport",
    "bad_json",
    "schema_invalid",
    "rejected",
    "unavailable",
    "unexpected",
]

_FALLBACK_LABELS: dict[str, str] = {
    "timeout": "超时",
    "transport": "连接模型失败",
    "bad_json": "返回的不是合法 JSON",
    "schema_invalid": "返回的结构不符合要求",
    "rejected": "返回内容触碰了边界",
    "unavailable": "模型路径不可用",
    "unexpected": "模型调用出现异常",
}

_RULES_DISCLAIMER = (
    "规则版：按固定规则从题面和你的作答里取证据，没有调用模型；这是过程反馈，不是解法。"
)
_LLM_DISCLAIMER = "模型版：措辞由模型整理，依据只来自题面和你的作答；不判断对错，不给解法。"

_BASE_NOT_CLAIMED: tuple[str, ...] = (
    "没有判断这段过程或答案的对错：这一轮没有做正确性检查。",
    "没有给出解法、评分或排名。",
    "没有评价你的能力、智力或天赋。",
)
_START_NOT_CLAIMED: tuple[str, ...] = (
    "没有判断对错，也没有定位卡点：这一轮只是起步计划。",
    "没有给出解法、评分或排名。",
    "没有评价你的能力、智力或天赋。",
)
_NO_ATTEMPT_NOTE = "没有看到可分析的过程，所以没有做任何诊断。"
_NO_ATTEMPT_POINT = "这一轮没看到你的作答或过程，所以不判断对错，也不猜卡点。"

# A sentence boundary, used to keep a quoted excerpt short. The quote is always
# copied from the student's own text; this module never paraphrases their answer
# into a "solution".
_SENTENCE_SPLIT = re.compile(r"[。！？；!?;\n]+")
_SPACE = re.compile(r"\s+")

# "不会/不知道" is an answer to the interface, not process text. A line that is
# only one of these markers is treated as a blank attempt; a longer sentence
# that happens to contain the marker still counts as an attempt.
_NON_ATTEMPT_MARKERS = ("完全不会", "不知道", "没思路", "不确定", "不会")
_TRIM = "。，,.！!？?；;：:、 "

# GenericReview finding kinds that express exactly one of the coach's process
# kinds. Everything else (missing goal/options/check, option without cost…) is
# still useful, but it is a process note rather than a fabricated diagnosis.
_FINDING_TO_POINT: dict[str, PointKind] = {
    "missing_evidence": "missing_evidence",
    "missing_constraint": "missing_constraint",
    "reasoning_jump": "missing_reasoning",
    "missing_assumption": "missing_reasoning",
}

# ``intake.gaps`` are human strings, not typed findings. This is the same cue
# table the intake already uses ("没看到证据", "没看到推理", "没看到约束").
_GAP_CUES: tuple[tuple[str, PointKind], ...] = (
    ("证据", "missing_evidence"),
    ("推理", "missing_reasoning"),
    ("约束", "missing_constraint"),
)

_GOAL_LABELS = ("目标", "结论")
_CONSTRAINT_LABELS = ("约束", "限制", "边界")
_KNOWN_LABELS = ("已知", "证据", "复现")
_ACTION_LABELS = ("尝试", "复现", "下一步", "可逆", "检查", "受众", "模型", "选项")


class CoachUnavailable(RuntimeError):
    """The model path could not produce a usable narrative.

    Carries a stable reason code; the service turns it into a rule result and a
    visible "fell back" note. It is never raised to the HTTP layer.
    """

    def __init__(self, reason: CoachFallbackReason, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CoachRequest:
    focus: CoachFocus

    def __post_init__(self) -> None:
        if self.focus not in ALLOWED_FOCUSES:
            raise ValueError(f"unsupported coach focus: {self.focus!r}")


@dataclass(frozen=True, slots=True)
class CoachPoint:
    """One process observation. ``basis`` names where it came from."""

    kind: PointKind
    text: str
    basis: str

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_POINT_KINDS:
            raise ValueError(f"unsupported coach point kind: {self.kind!r}")
        if not self.text.strip():
            raise ValueError("coach point text must not be empty")
        if not self.basis.strip():
            raise ValueError("coach point basis must not be empty")


@dataclass(frozen=True, slots=True)
class CoachOut:
    """The wire shape (v0.1). It has no answer, solution, score or rank field."""

    version: Literal["0.1"]
    mode: CoachMode
    focus: CoachFocus
    headline: str
    points: tuple[CoachPoint, ...]
    next_question: str
    not_claimed: tuple[str, ...]
    disclaimer: str

    def __post_init__(self) -> None:
        if self.version != VERSION:
            raise ValueError(f"unsupported coach version: {self.version!r}")
        if self.mode not in ("rules", "llm"):
            raise ValueError(f"unsupported coach mode: {self.mode!r}")
        if self.focus not in ALLOWED_FOCUSES:
            raise ValueError(f"unsupported coach focus: {self.focus!r}")
        if not self.headline.strip():
            raise ValueError("coach headline must not be empty")
        if not 1 <= len(self.points) <= 4:
            raise ValueError("coach needs 1-4 points")
        if not self.next_question.strip():
            raise ValueError("coach needs one next_question")
        if not self.not_claimed:
            raise ValueError("coach must say what it did not claim")
        if not self.disclaimer.strip():
            raise ValueError("coach disclaimer must not be empty")


@dataclass(frozen=True, slots=True)
class CoachContext:
    """Everything the coach may see.

    It is built from the stored session/problem and the derived intake. There is
    deliberately no solved answer, no solution and no ``AnswerStore`` reference.
    """

    problem_text: str
    domain_name: str
    domain_label: str
    verification: str
    framework: str
    checklist: tuple[str, ...] = ()
    answer_text: str = ""
    work_text: str = ""
    attempt_text: str = ""
    observed: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    review: GenericReview | None = None
    session_id: str = ""

    @property
    def has_attempt(self) -> bool:
        return _meaningful(self.attempt_text)


class CoachNarrative:
    """The small result the optional model adapter may return.

    It is not the wire shape: the service attaches the version, mode, focus and
    the ``not_claimed``/``disclaimer`` honesty fields itself, so a model cannot
    drop them.
    """

    def __init__(
        self,
        *,
        headline: str,
        points: Sequence[CoachPoint],
        next_question: str,
    ) -> None:
        if not 2 <= len(points) <= 4:
            raise ValueError("a model coach narrative needs 2-4 points")
        self.headline = headline
        self.points = tuple(points)
        self.next_question = next_question


class CoachNarrator(Protocol):
    """Optional model portrait of the same process feedback (infrastructure)."""

    def narrate(self, context: CoachContext, focus: CoachFocus) -> CoachNarrative: ...


class CoachService:
    """Rule coach plus an optional, strictly-validated model narrator."""

    def __init__(self, narrator: CoachNarrator | None = None) -> None:
        self._narrator = narrator

    def coach(self, context: CoachContext, request: CoachRequest) -> CoachOut:
        rule = build_rule_coach(context, request.focus)
        if self._narrator is None:
            return rule
        try:
            narrative = self._narrator.narrate(context, request.focus)
            return _llm_out(rule, narrative)
        except CoachUnavailable as exc:
            return _fallback(rule, exc.reason)
        except Exception:  # noqa: BLE001 - a coach bug must not become a 500
            _LOGGER.exception(
                "coach narrator failed; falling back to rules (session=%s)",
                context.session_id,
            )
            return _fallback(rule, "unexpected")


def _llm_out(rule: CoachOut, narrative: CoachNarrative) -> CoachOut:
    points = tuple(narrative.points)
    if not 2 <= len(points) <= 4:
        raise CoachUnavailable("schema_invalid", "narrative point count")
    return CoachOut(
        version=VERSION,
        mode="llm",
        focus=rule.focus,
        headline=narrative.headline.strip(),
        points=points,
        next_question=narrative.next_question.strip(),
        not_claimed=rule.not_claimed,
        disclaimer=_LLM_DISCLAIMER,
    )


def _fallback(rule: CoachOut, reason: str) -> CoachOut:
    label = _FALLBACK_LABELS.get(reason, _FALLBACK_LABELS["unexpected"])
    return replace(
        rule,
        mode="rules",
        disclaimer=(f"{_RULES_DISCLAIMER}（模型调用没有完成：{label}；本次回退规则版。）"),
        not_claimed=rule.not_claimed + ("模型这次没有参与；下面全部由规则版生成。",),
    )


def build_coach_context(
    *,
    session_id: str,
    problem_text: str,
    profile: DomainProfile,
    checklist: Sequence[str],
    answer_text: str = "",
    work_text: str = "",
    scaffold_work: str = "",
    observed: Sequence[str] = (),
    gaps: Sequence[str] = (),
    review: GenericReview | None = None,
) -> CoachContext:
    """Join the student's stored text and drop a duplicated work field.

    The reference-free path stores the short answer and the work together in
    ``initial_answer``; an annotated session stores them separately. Both end up
    as one ``attempt_text`` here, without repeating the same paragraph twice.
    """

    answer = answer_text.strip()
    work = work_text.strip()
    if work and work in answer:
        answer = answer.replace(work, "", 1).strip()

    parts: list[str] = [answer] if answer else []
    for extra in (work, scaffold_work.strip()):
        if extra and extra not in "\n".join(parts):
            parts.append(extra)

    return CoachContext(
        problem_text=problem_text,
        domain_name=profile.name,
        domain_label=profile.label,
        verification=profile.verification.value,
        framework=profile.framework.value,
        checklist=tuple(item.strip() for item in checklist if item.strip()),
        answer_text=answer,
        work_text=work,
        attempt_text="\n".join(parts).strip(),
        observed=tuple(observed),
        gaps=tuple(gaps),
        review=review,
        session_id=session_id,
    )


def build_rule_coach(context: CoachContext, focus: CoachFocus) -> CoachOut:
    """Deterministic path. Always available, even with no model configured."""

    if focus == "how_to_start" or not context.has_attempt:
        return _start_plan(context, focus)
    return _where_wrong(context)


# --- where_wrong -------------------------------------------------------------


def _where_wrong(context: CoachContext) -> CoachOut:
    findings = context.review.findings if context.review is not None else ()
    mapped: list[CoachPoint] = []
    for finding in findings:
        mapped.append(
            CoachPoint(
                kind=_point_kind_for_finding(finding),
                text=_finding_line(finding),
                basis=f"intake.review:{finding.id}",
            )
        )
    if not mapped:
        for index, gap in enumerate(context.gaps[:2]):
            mapped.append(
                CoachPoint(
                    kind=_point_kind_for_gap(gap),
                    text=_gap_line(gap),
                    basis=f"intake.gaps[{index}]",
                )
            )

    excerpts = _excerpts(context)
    quote = excerpts[0] if excerpts else ""
    points: list[CoachPoint] = mapped[:2]
    if quote:
        points.append(
            CoachPoint(
                kind="process_note",
                text=(
                    f"你写到「{quote}」。可以先核对："
                    "这一步用到的依据（定义、公式或规则）有没有写出来。"
                ),
                basis="attempt.quote",
            )
        )
    else:
        points.append(
            CoachPoint(
                kind="process_note",
                text="你提交了一段过程，但这里读不到可以引用的原句；可以先核对每一步的依据。",
                basis="attempt",
            )
        )

    if not mapped:
        second = excerpts[1] if len(excerpts) > 1 else quote
        if second:
            points.append(
                CoachPoint(
                    kind="process_note",
                    text=(
                        f"再看「{second}」。可以先核对："
                        "这一步的结果是怎么从上一句推出来的，中间缺没缺一句话。"
                    ),
                    basis="attempt.quote",
                )
            )
        else:
            points.append(
                CoachPoint(
                    kind="process_note",
                    text="再看结尾：这一步的结果是怎么从上一句推出来的，中间有没有一句省掉了。",
                    basis="attempt",
                )
            )

    headline = (
        f"先不判对错：这段过程里有 {len(mapped)} 处可以补写或自查的地方。"
        if mapped
        else "先不判对错：可以从你写的这段过程里核对两处。"
    )
    return CoachOut(
        version=VERSION,
        mode="rules",
        focus="where_wrong",
        headline=headline,
        points=tuple(points[:4]),
        next_question=_question_for(points[0].kind),
        not_claimed=_BASE_NOT_CLAIMED,
        disclaimer=_RULES_DISCLAIMER,
    )


def _point_kind_for_finding(finding: GenericFinding) -> PointKind:
    return _FINDING_TO_POINT.get(finding.kind, "process_note")


def _point_kind_for_gap(gap: str) -> PointKind:
    for cue, kind in _GAP_CUES:
        if cue in gap:
            return kind
    return "process_note"


def _finding_line(finding: GenericFinding) -> str:
    return _process_line(finding.summary)


def _gap_line(gap: str) -> str:
    return _process_line(gap)


def _process_line(summary: str) -> str:
    text = summary.strip()
    if text.startswith("没看到"):
        return _ensure_period(f"这里缺的是{text[3:]}")
    return _ensure_period(f"你这段过程里，可能是：{text}")


def _question_for(kind: PointKind) -> str:
    if kind == "missing_evidence":
        return "支撑你这一句的事实、数据或引文，你能补上哪一条？"
    if kind == "missing_reasoning":
        return "从你写的上一句到这一句，中间跳过了哪一步？"
    if kind == "missing_constraint":
        return "哪个条件不能动：时间、范围还是关系？"
    if kind == "no_attempt":
        return "先用一句话写下目标：这一轮你最想解决或得到的是什么？"
    return "这一步用到的依据（定义、公式或规则），能在题目里找到对应条件吗？"


# --- how_to_start ------------------------------------------------------------


def _start_plan(context: CoachContext, focus: CoachFocus) -> CoachOut:
    blank = not context.has_attempt
    points: list[CoachPoint] = []
    if blank:
        points.append(CoachPoint(kind="no_attempt", text=_NO_ATTEMPT_POINT, basis="attempt:none"))

    for index, item in _plan_items(context.checklist):
        points.append(
            CoachPoint(
                kind="next_step",
                text=_plan_line(item),
                basis=f"checklist[{index}]",
            )
        )

    if not context.checklist:
        points.append(
            CoachPoint(
                kind="next_step",
                text="先把目标、已知和不能动的条件各写一句；不用先写答案。",
                basis="coach.rules",
            )
        )

    if blank:
        headline = (
            "还没看到你的过程，所以先不给「错在哪」。"
            if focus == "where_wrong"
            else "还没看到你的过程：先把目标、约束和下一步各写一句。"
        )
        not_claimed = _START_NOT_CLAIMED + (_NO_ATTEMPT_NOTE,)
    else:
        headline = "先不找错：按下面三句把问题搭起来，再回来看。"
        not_claimed = _START_NOT_CLAIMED

    return CoachOut(
        version=VERSION,
        mode="rules",
        focus=focus,
        headline=headline,
        points=tuple(points[:4]),
        next_question="先用一句话写下目标：这一轮你最想解决或得到的是什么？",
        not_claimed=not_claimed,
        disclaimer=_RULES_DISCLAIMER,
    )


def _plan_items(checklist: tuple[str, ...]) -> tuple[tuple[int, str], ...]:
    """Pick goal, one boundary and one next action from the domain checklist."""

    indexed = tuple((index, item) for index, item in enumerate(checklist) if item)
    if not indexed:
        return ()

    selected: list[tuple[int, str]] = []
    for labels in (_GOAL_LABELS, _CONSTRAINT_LABELS, _ACTION_LABELS, _KNOWN_LABELS):
        for index, item in indexed:
            if (index, item) in selected:
                continue
            if any(item.startswith(label) for label in labels):
                selected.append((index, item))
                break
        if len(selected) >= 3:
            break

    for index, item in indexed:
        if len(selected) >= 3:
            break
        if (index, item) not in selected:
            selected.append((index, item))
    return tuple(selected[:3])


def _plan_line(item: str) -> str:
    label, separator, rest = item.partition("：")
    if not separator:
        label, separator, rest = item.partition(":")
    if not separator:
        return _ensure_period(f"先写一句{item}")
    connector = "先写一句" if label in _GOAL_LABELS else "再补一句"
    if label in _CONSTRAINT_LABELS or label in _KNOWN_LABELS:
        connector = "再补一句"
    body = rest.strip() or item
    return _ensure_period(f"{connector}{label}：{body}")


# --- shared text helpers -----------------------------------------------------


def _meaningful(text: str) -> bool:
    cleaned = _SPACE.sub("", text)
    if not cleaned:
        return False
    rest = cleaned
    for marker in _NON_ATTEMPT_MARKERS:
        rest = rest.replace(marker, "")
    return len(rest.strip(_TRIM)) >= 2


def _excerpts(context: CoachContext) -> tuple[str, ...]:
    """Short quotes from the student's own text, deduplicated and ordered."""

    chunks: list[str] = []
    sources = (
        (context.work_text, context.answer_text)
        if context.work_text
        else (
            context.answer_text,
            context.work_text,
        )
    )
    for source in sources:
        for part in _SENTENCE_SPLIT.split(source):
            cleaned = _SPACE.sub(" ", part).strip(_TRIM)
            if len(cleaned) >= 2 and cleaned not in chunks:
                chunks.append(cleaned)
    return tuple(_clip(cleaned, 36) for cleaned in chunks)


def _ensure_period(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return "。"
    if cleaned.endswith(("。", "！", "？", "!", "?")):
        return cleaned
    return f"{cleaned}。"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
