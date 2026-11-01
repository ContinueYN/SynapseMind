"""LLM-backed generic problem graph (Phase 1b).

Same pipeline shape as the solution-graph builder — prompt -> JSON -> tolerant
parse -> structural rules -> ``specs/problem-graph.schema.json`` -> one retry —
but a different contract. The model organises the *problem* (goal, givens,
constraints, options, risks, next experiment); it does not solve it, does not
rank options, and does not output probes.

Two deliberate limits:

* a ``formal`` claim is only read when the domain is FORMAL **and** the student
  already wrote an answer. The model may formalise that answer; it may not solve
  the problem for them. No answer means no claim, and the verifier says
  ``unknown``.
* an ``empirical`` claim is only read when the caller supplies structured input
  (equation/expression + units). Phase 1b has no such input, so the model is told
  to emit ``null``; guessing units from prose would be exactly the false check
  the product forbids.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from synapse.application import trace
from synapse.application.audit import AuditEntry, CallAuditor
from synapse.application.domains import IntakeFramework, VerificationMode
from synapse.application.generic_graph import (
    GenericGraphBuildFailed,
    GenericGraphBuildResult,
    GenericGraphDraft,
    GenericGraphFailureReason,
)
from synapse.application.generic_verify import EmpiricalVerifier, FormalVerifier
from synapse.application.llm import (
    LLMCallFailed,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
)
from synapse.domain.problem.generic import (
    ClaimCheck,
    EmpiricalClaim,
    GenericGraph,
    GenericNode,
    NodeKind,
)
from synapse.domain.problem.generic_structure import fingerprint, review
from synapse.domain.problem.models import VerificationClaim
from synapse.infrastructure.llm.graph import ClaimPayloadError, claim_payload, read_claim
from synapse.infrastructure.llm.settings import LLMSettings
from synapse.infrastructure.verification import (
    default_empirical_verifier,
    default_formal_verifier,
)

GENERIC_GRAPH_MAX_TOKENS = 1400
GENERIC_GRAPH_CACHE_SIZE = 64
PROBLEM_ID_PATTERN = re.compile(r"^P_[A-Z0-9_]+$")

GENERIC_SYSTEM_PROMPT = """你是通用问题结构整理器。输入一个问题、它的领域标签、
验证方式和学生已有的作答，输出一张“问题结构图”JSON。
结构图只描述这个问题由什么组成，不是解题稿，也不是诊断结论；你不给答案。
硬性要求：
1. 只输出一个 JSON 对象，不要 markdown、代码块或解释。顶层只有 nodes / formal / empirical：
   {"nodes": [{"id": "g1", "kind": "goal", "text": "..."},
              {"id": "g2", "kind": "constraint", "text": "..."}],
    "formal": null, "empirical": null}
2. nodes 为 3–10 个，id 从 g1 连续编号；text 不超过 60 字，
   写“这一项是什么”，不复述题面，不写最终答案、完整算式或完整解法。
3. kind 只能是 goal / given / constraint / assumption / plan / action /
   evidence / check / decision / risk / next 之一：
   goal 目标；given 已知/材料；constraint 约束/边界；assumption 假设；
   plan 计划/策略；action 已做的尝试；evidence 证据/报错/数据；
   check 检查/测试/判定标准；decision 一个候选选项；risk 风险/代价；
   next 下一步/可逆小实验。
4. 必须有一个 goal；除 decision 外，每种 kind 最多一个节点。
   决策问题（验证方式为 argumentative 且是在做选择）至少要有两个 decision 节点，
   其中一个应该是“什么都不做”。decision 表示“一个候选选项”，不是“最终选择”。
5. 不要排序、不要推荐、不要写“你应该”“建议选”“最好选”“正确答案”“唯一答案”
   “最优解”。只列目标、约束、选项、代价、风险和可逆实验。
6. 不要输出探针（probes），不要输出完整解法，不要给最终答案。
7. 只写问题或学生作答里支持的内容；没写到的不要编。宁可少一个节点，
   也不要补一个看起来合理的事实。不确定就留空。
8. formal 只在验证方式为 formal、且学生已经写过一个“参数区间”形式的答案时填写。
   它把**学生已经写出的答案**形式化，不得替学生解题，也不得修正学生答案。
   没有作答、学生说“不知道/不确定/不会”、答案不是参数区间、或题型不是
   “恒成立求参数范围”时，formal 必须为 null。
   形状与解法图的 claim 相同：
   {"kind":"parameter_range","parameter":"a","variable":"x",
    "variable_domain":"(-inf,+inf)",
    "constraint":{"expression":"x^2-a*x+1","relation":">"},
    "answer":[{"lower":"-2","upper":"2","lower_inclusive":false,"upper_inclusive":false}]}
9. empirical 只在输入里已经给出结构化 equation 或 expression + units 时才填写；
   当前接口没有结构化输入，所以 empirical 必须为 null。
   不要从自然语言里猜单位、公式或数值。
10. 这是通用问题诊断，不是全科家教：生活/写作/决策问题没有唯一正确答案，
    代码问题没有运行就不能声称找到了 bug。"""

_ISSUE_HINTS = {
    "bad_json": "只输出一个合法 JSON 对象",
    "not_object": "只输出一个 JSON 对象",
    "unknown_node_kind": "kind 只能取第 3 条列出的十一种",
    "node_count": "节点数必须在 3–10 之间",
    "no_goal": "必须有一个 goal 节点",
    "decision_options_too_few": "决策问题至少要有两个 decision 节点",
    "recommendation_in_node": "删掉“你应该/建议选/正确答案”一类结论，只列选项与取舍",
    "probes_unsupported": "不要输出探针；这张图不是解法图",
    "empty_node_text": "每个节点都要有文字",
    "duplicate_node_id": "节点 id 不能重复",
    "unknown_node": "每个节点都要有 id / kind / text",
    "formal": "formal 必须是 claim 对象或 null",
    "formal.constraint": "formal.constraint 必须含 expression 与 relation",
    "formal.answer": "formal.answer 必须是非空的区间数组",
    "empirical": "empirical 必须是对象或 null",
    "empirical_equation": "equation 与 expression 只能二选一",
    "empirical_expression": "expression 模式必须同时给 unit",
    "empirical_units": "units 必须是 符号 -> 单位字符串 的对象",
    "empirical_values": "values 必须是 符号 -> 数字 的对象",
    "empirical_unsupported": "没有结构化输入时不要填 empirical",
}

_DEGENERATE_CODES = frozenset(
    {"node_count", "no_goal", "decision_options_too_few", "recommendation_in_node"}
)

# A non-empty answer is not enough to formalise: "暂时不确定" is an answer to the
# interface, not a candidate solution. Letting the model turn it into a claim
# would invent something the student never asserted.
_UNSURE_ANSWER_MARKERS = ("不知道", "不确定", "不会", "没思路", "还没", "暂时", "猜")


class _Rejected(Exception):
    def __init__(self, reason: GenericGraphFailureReason, issues: Sequence[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.issues = tuple(issues)


class _NodePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str
    kind: str
    text: str


class _GraphPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nodes: list[_NodePayload] = Field(default_factory=list)


def build_request(
    draft: GenericGraphDraft,
    *,
    issues: Sequence[str] = (),
) -> LLMRequest:
    """One structure request; ``issues`` carries the previous attempt's errors."""

    answer = draft.answer.strip() or "（没有作答）"
    work = draft.work.strip() or "（没有写过程）"
    user = (
        f"领域：{draft.label}\n"
        f"验证方式：{draft.verification.value}\n"
        f"检查框架：{draft.framework.value}\n"
        f"问题：\n{draft.text.strip()}\n\n"
        f"学生已有的回答：\n{answer[:1200]}\n\n"
        f"学生写的过程：\n{work[:1200]}\n\n"
        "请输出问题结构图 JSON。"
    )
    feedback = _feedback(issues)
    if feedback:
        user += (
            "\n\n上一次输出未通过校验，必须修正以下问题后重新输出完整 JSON：\n"
            f"{feedback}\n\n"
            "这次请输出**最小可用结构**：3–6 个节点，宁短勿长；"
            "规则一条都不能少。"
        )
    return LLMRequest(
        purpose="generic_graph_build",
        system=GENERIC_SYSTEM_PROMPT,
        user=user,
        schema_name="generic_problem_graph",
        json_schema=None,
        max_tokens=GENERIC_GRAPH_MAX_TOKENS,
    )


class LLMGenericGraphGenerator:
    def __init__(
        self,
        client: LLMClient,
        *,
        settings: LLMSettings,
        auditor: CallAuditor | None = None,
        formal: FormalVerifier | None = None,
        empirical: EmpiricalVerifier | None = None,
        cache_size: int = GENERIC_GRAPH_CACHE_SIZE,
    ) -> None:
        self._client = client
        self._settings = settings
        self._auditor = auditor
        self._formal: FormalVerifier = formal or default_formal_verifier()
        self._empirical: EmpiricalVerifier = empirical or default_empirical_verifier()
        self._cache: dict[str, GenericGraphBuildResult] = {}
        self._cache_size = max(0, cache_size)

    def warm(self) -> None:
        warm = getattr(self._formal, "warm", None)
        if callable(warm):
            warm()

    def generate(self, draft: GenericGraphDraft) -> GenericGraphBuildResult:
        if not self._settings.llm_enabled:
            raise GenericGraphBuildFailed(
                "disabled",
                detail="SYNAPSE_LLM_MODE=off 或缺少 API key；没有可用的规则建图路径",
            )
        if not PROBLEM_ID_PATTERN.fullmatch(draft.id):
            raise GenericGraphBuildFailed(
                "invalid_draft",
                detail=f"problem id {draft.id!r} 不符合 ^P_[A-Z0-9_]+$",
            )

        cache_key = _cache_key(draft, self._settings)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return replace(cached, cached=True)

        attempts = max(1, self._settings.max_attempts)
        issues: tuple[str, ...] = ()
        reason: GenericGraphFailureReason = "schema_invalid"
        for attempt in range(attempts):
            request = build_request(draft, issues=issues)
            try:
                response = self._client.complete(
                    request,
                    timeout_s=self._settings.generic_graph_timeout_s,
                )
            except LLMTimeout as exc:
                self._audit(
                    None,
                    schema_ok=False,
                    retried=attempt > 0,
                    reason="timeout",
                )
                raise GenericGraphBuildFailed(
                    "timeout",
                    detail=str(exc),
                    attempts=attempt + 1,
                ) from exc
            except LLMCallFailed as exc:
                self._audit(
                    None,
                    schema_ok=False,
                    retried=attempt > 0,
                    reason="transport",
                )
                raise GenericGraphBuildFailed(
                    "transport",
                    detail=str(exc),
                    attempts=attempt + 1,
                ) from exc

            try:
                graph, repairs = _build_graph(draft, response.text)
            except _Rejected as exc:
                reason = exc.reason
                issues = exc.issues
                self._audit(
                    response,
                    schema_ok=False,
                    retried=attempt > 0,
                    reason=exc.reason,
                )
                continue

            checks = _run_checks(self._formal, self._empirical, draft, graph)
            digest = fingerprint(graph)
            self._audit(
                response,
                schema_ok=True,
                retried=attempt > 0,
                fingerprint=digest,
                verification_status=_status(checks),
            )
            result = GenericGraphBuildResult(
                graph=graph,
                checks=checks,
                attempts=attempt + 1,
                repairs=repairs,
                notes=(),
            )
            self._store(cache_key, result)
            return result

        raise GenericGraphBuildFailed(
            reason,
            detail="; ".join(issues[:5]),
            attempts=attempts,
        )

    def _store(self, key: str, result: GenericGraphBuildResult) -> None:
        if self._cache_size <= 0:
            return
        if len(self._cache) >= self._cache_size:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = result

    def _audit(
        self,
        response: LLMResponse | None,
        *,
        schema_ok: bool,
        retried: bool,
        reason: str | None = None,
        fingerprint: str = "",
        verification_status: str = "",
    ) -> None:
        if self._auditor is None:
            return
        context = trace.current()
        self._auditor.record(
            AuditEntry(
                kind="generic_graph_build",
                session_id=context.session_id if context else "",
                turn=context.turn if context else 0,
                model=response.model if response else self._settings.model,
                prompt_version=self._settings.generic_graph_prompt_version,
                latency_ms=response.latency_ms if response else 0,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                retried=retried,
                fallback_reason=reason,
                schema_ok=schema_ok,
                graph_fingerprint=fingerprint,
                verification_status=verification_status,
            )
        )


def _answer_is_formalisable(draft: GenericGraphDraft) -> bool:
    answer = draft.answer.strip()
    if draft.verification is not VerificationMode.FORMAL or not answer:
        return False
    return not any(marker in answer for marker in _UNSURE_ANSWER_MARKERS)


def _build_graph(draft: GenericGraphDraft, text: str) -> tuple[GenericGraph, tuple[str, ...]]:
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _Rejected("bad_json", (f"bad_json: {exc.msg}",)) from exc
    if not isinstance(raw, Mapping):
        raise _Rejected("bad_json", ("not_object: 响应必须是 JSON 对象",))

    top_probes = raw.get("probes")
    if isinstance(top_probes, list) and top_probes:
        raise _Rejected(
            "schema_invalid",
            ("probes_unsupported: 通用图不输出探针",),
        )
    if raw.get("claim") is not None:
        raise _Rejected(
            "schema_invalid",
            ("formal: 形式化声明请写在 formal 字段里",),
        )

    try:
        payload = _GraphPayload.model_validate(raw)
    except ValidationError as exc:
        raise _Rejected("schema_invalid", _format_validation(exc)) from exc

    nodes: list[GenericNode] = []
    seen: set[str] = set()
    for index, item in enumerate(payload.nodes, start=1):
        if not item.id or not item.text:
            raise _Rejected(
                "schema_invalid",
                (f"unknown_node: 第 {index} 个节点缺少 id 或 text",),
            )
        if item.id in seen:
            raise _Rejected("schema_invalid", (f"duplicate_node_id: {item.id}",))
        seen.add(item.id)
        try:
            kind = NodeKind(item.kind.strip().lower())
        except ValueError as exc:
            raise _Rejected(
                "schema_invalid",
                (f"unknown_node_kind: {item.kind!r}",),
            ) from exc
        nodes.append(
            GenericNode(
                id=item.id,
                kind=kind,
                text=" ".join(item.text.split()),
                source="system",
            )
        )

    repairs: set[str] = set()
    formal: VerificationClaim | None = None
    if raw.get("formal") is not None:
        if not _answer_is_formalisable(draft):
            repairs.add("formal_dropped_unsupported")
        else:
            try:
                formal = read_claim(raw.get("formal"))
            except ClaimPayloadError as exc:
                raise _Rejected("schema_invalid", exc.issues) from exc

    empirical: EmpiricalClaim | None = None
    if raw.get("empirical") is not None:
        if draft.verification is not VerificationMode.EMPIRICAL or draft.structured is None:
            repairs.add("empirical_dropped_unsupported")
        else:
            empirical = _empirical(raw.get("empirical"))

    graph = GenericGraph(
        problem_id=draft.id,
        version="g2",
        nodes=tuple(nodes),
        formal=formal,
        empirical=empirical,
    )
    checked = review(graph, decision=draft.framework is IntakeFramework.DECISION)
    if not checked.ok:
        raise _Rejected(_classify(checked.issues), checked.issues)
    repairs.update(checked.repairs)

    spec_errors = validate_payload(to_payload(checked.graph))
    if spec_errors:
        raise _Rejected("schema_invalid", spec_errors)
    return checked.graph, tuple(sorted(repairs))


def _empirical(raw: object) -> EmpiricalClaim:
    if not isinstance(raw, Mapping):
        raise _Rejected("schema_invalid", ("empirical: 必须是对象",))
    equation = _optional_text(raw.get("equation"))
    expression = _optional_text(raw.get("expression"))
    if equation is None and expression is None:
        raise _Rejected("schema_invalid", ("empirical_equation: 必须给 equation 或 expression",))
    if equation is not None and expression is not None:
        raise _Rejected(
            "schema_invalid",
            ("empirical_equation: equation 与 expression 只能二选一",),
        )
    unit = _optional_text(raw.get("unit"))
    if expression is not None and not unit:
        raise _Rejected("schema_invalid", ("empirical_expression: expression 需要 unit",))
    try:
        return EmpiricalClaim(
            equation=equation,
            expression=expression,
            unit=unit,
            units=_text_map(raw.get("units", {}), "empirical_units"),
            values=_number_map(raw.get("values", {}), "empirical_values"),
        )
    except ValueError as exc:
        raise _Rejected("schema_invalid", (f"empirical: {exc}",)) from exc


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _Rejected("schema_invalid", ("empirical_expression: 必须是字符串",))
    text = value.strip()
    return text or None


def _text_map(raw: object, code: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise _Rejected("schema_invalid", (f"{code}: 必须是对象",))
    result: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise _Rejected("schema_invalid", (f"{code}: 键和值都必须是非空字符串",))
        result[key] = value.strip()
    return result


def _number_map(raw: object, code: str) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise _Rejected("schema_invalid", (f"{code}: 必须是对象",))
    result: dict[str, float] = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise _Rejected("schema_invalid", (f"{code}: 值必须是数字",))
        result[key] = float(value)
    return result


def _run_checks(
    formal: FormalVerifier,
    empirical: EmpiricalVerifier,
    draft: GenericGraphDraft,
    graph: GenericGraph,
) -> tuple[ClaimCheck, ...]:
    checks: list[ClaimCheck] = []
    if draft.verification is VerificationMode.FORMAL:
        if graph.formal is None:
            checks.append(
                ClaimCheck(
                    kind="formal",
                    status="unknown",
                    detail="没有可验证的形式化声明（需要“恒成立求参数区间”一类问题），本轮未做符号检查。",
                )
            )
        else:
            checks.append(_safe_formal(formal, graph.formal))
    elif draft.verification is VerificationMode.EMPIRICAL:
        if graph.empirical is None:
            checks.append(
                ClaimCheck(
                    kind="empirical",
                    status="unknown",
                    detail="没有结构化方程/单位输入，本轮未做量纲检查。",
                )
            )
        else:
            checks.append(_safe_empirical(empirical, graph.empirical))
    return tuple(checks)


def _safe_formal(verifier: FormalVerifier, claim: VerificationClaim) -> ClaimCheck:
    try:
        return verifier.verify(claim)
    except Exception as exc:  # noqa: BLE001 - a verifier bug is not a pass
        return ClaimCheck(
            kind="formal",
            status="unknown",
            detail=f"形式验证器无法运行（{type(exc).__name__}）；本次不把 claim 当作已检查。",
        )


def _safe_empirical(verifier: EmpiricalVerifier, claim: EmpiricalClaim) -> ClaimCheck:
    try:
        return verifier.verify(claim)
    except Exception as exc:  # noqa: BLE001 - a verifier bug is not a pass
        return ClaimCheck(
            kind="empirical",
            status="unknown",
            detail=f"经验验证器无法运行（{type(exc).__name__}）；本次未做量纲检查。",
        )


def to_payload(graph: GenericGraph) -> dict[str, object]:
    """The shape ``specs/problem-graph.schema.json`` validates."""

    payload: dict[str, object] = {
        "problem_id": graph.problem_id,
        "version": graph.version,
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind.value,
                "text": node.text,
                "source": node.source,
            }
            for node in graph.nodes
        ],
    }
    if graph.formal is not None:
        payload["formal"] = claim_payload(graph.formal)
    if graph.empirical is not None:
        empirical: dict[str, object] = {
            "units": dict(graph.empirical.units),
            "values": dict(graph.empirical.values),
        }
        # The schema types these as strings when present; omit the absent half
        # instead of sending an explicit null.
        if graph.empirical.equation is not None:
            empirical["equation"] = graph.empirical.equation
        if graph.empirical.expression is not None:
            empirical["expression"] = graph.empirical.expression
        if graph.empirical.unit is not None:
            empirical["unit"] = graph.empirical.unit
        payload["empirical"] = empirical
    return payload


def validate_payload(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Run the real spec; returns human-readable errors, empty when valid."""

    schema, registry = _schemas()
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(
        validator.iter_errors(dict(payload)),
        key=lambda error: "/".join(str(part) for part in error.absolute_path),
    )
    formatted: list[str] = []
    for error in errors:
        path = "/".join(str(part) for part in error.absolute_path)
        formatted.append(f"{path or '$'}: {error.message}")
    return tuple(formatted)


def _classify(issues: Sequence[str]) -> GenericGraphFailureReason:
    codes = {issue.split(":", 1)[0].strip() for issue in issues}
    return "degenerate" if codes & _DEGENERATE_CODES else "schema_invalid"


def _format_validation(exc: ValidationError) -> tuple[str, ...]:
    formatted: list[str] = []
    for error in exc.errors():
        location = "/".join(str(part) for part in error["loc"])
        formatted.append(f"{location or '$'}: {error['msg']}")
    return tuple(formatted)


def _feedback(issues: Sequence[str]) -> str:
    lines: list[str] = []
    for issue in issues[:12]:
        code = issue.split(":", 1)[0].strip()
        hint = _ISSUE_HINTS.get(code, "")
        lines.append(f"- {hint}（{issue}）" if hint else f"- {issue}")
    return "\n".join(lines)


def _status(checks: Sequence[ClaimCheck]) -> str:
    for check in checks:
        if check.status == "fail":
            return "fail"
    for check in checks:
        if check.status == "pass":
            return "pass"
    return "unknown"


def _cache_key(draft: GenericGraphDraft, settings: LLMSettings) -> str:
    structured = json.dumps(
        dict(draft.structured) if draft.structured is not None else None,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    raw = "\x1f".join(
        (
            draft.id,
            draft.text.strip(),
            draft.label,
            draft.verification.value,
            draft.framework.value,
            draft.answer.strip(),
            draft.work.strip(),
            structured,
            settings.model,
            settings.generic_graph_prompt_version,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _schemas() -> tuple[dict[str, object], Registry]:
    base = _repo_root() / "specs"
    problem = _load_schema(base / "problem-graph.schema.json")
    solution = _load_schema(base / "solution-graph.schema.json")
    registry: Registry = Registry().with_resources(
        [
            (
                "https://synapsemind.dev/schemas/solution-graph.schema.json",
                Resource.from_contents(solution, default_specification=DRAFT202012),
            ),
            (
                "https://synapsemind.dev/schemas/problem-graph.schema.json",
                Resource.from_contents(problem, default_specification=DRAFT202012),
            ),
        ]
    )
    return problem, registry


def _load_schema(path: Path) -> dict[str, object]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return cast(dict[str, object], loaded)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "specs" / "problem-graph.schema.json").is_file():
            return parent
    raise RuntimeError(
        "specs/problem-graph.schema.json not found; generic graph generation "
        "requires the repo checkout"
    )
