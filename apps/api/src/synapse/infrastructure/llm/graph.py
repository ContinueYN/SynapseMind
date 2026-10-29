"""LLM-backed solution-graph builder (M2.5 S4).

Pipeline for one problem, exactly as chapter 13 §13.5 describes it:

    prompt -> JSON -> tolerant parse -> mechanical repair -> structural rules
           -> specs/solution-graph.schema.json -> success, or one retry

The schema is loaded from ``specs/`` rather than duplicated into Pydantic
models, so the contract stays single-sourced. The model is told what is wrong
on the retry (errors only, not the previous output) and gets exactly one
chance, matching the failure table in §13.5.

What the model controls: the decomposition, the wording of steps and probes.
What it cannot control: the problem id, the graph version, the probe target
vocabulary, or whether the result is accepted.
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

from synapse.application import trace
from synapse.application.audit import AuditEntry, CallAuditor
from synapse.application.graph import (
    GraphBuildFailed,
    GraphBuildResult,
    GraphFailureReason,
)
from synapse.application.llm import (
    LLMCallFailed,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMTimeout,
)
from synapse.domain.diagnosis.hypotheses import HYPOTHESES
from synapse.domain.problem.graph_structure import (
    GraphCheck,
    fingerprint,
    quality_notes,
    review,
)
from synapse.domain.problem.models import (
    Probe,
    ProblemDraft,
    SolutionGraph,
    SolutionNode,
)
from synapse.infrastructure.llm.settings import LLMSettings

GRAPH_MAX_TOKENS = 4096
GRAPH_CACHE_SIZE = 128
PROBLEM_ID_PATTERN = re.compile(r"^P_[A-Z0-9_]+$")

# The diagnosis layer is still the M1 one (H_L1/L2/L4), so a generated probe
# must separate two of those hypotheses. S5 replaces the vocabulary together
# with the evidence table.
ALLOWED_PROBE_TARGETS = frozenset(HYPOTHESES)

GRAPH_SYSTEM_PROMPT = """你是高中数学解法图标注器。输入一道高中数学题，输出一张“解法图”JSON。
解法图描述解这道题需要完成的认知步骤，不是完整演算稿。
硬性要求：
1. 只输出一个 JSON 对象，不要 markdown、代码块或解释，结构为：
   {"nodes":[{"id":"n1","type":"READ","text":"...","demand":{"V":0.2},"probes":[{"id":"p1","question":"...","options":["...","...","..."],"targets":["H_L2","H_L1"],"evidence":{"A":{"H_L2":-0.4,"H_L1":0.2},"B":{"H_L2":0.35,"H_L1":-0.1},"C":{"H_L1":0.3}}}]}],"edges":[["n1","n2"]]}
2. nodes 为 3–10 个（硬上限 20）；id 从 n1 连续编号；
   text 不超过 60 字，写这一步做什么，不写最终答案。
3. type 只能是 READ / CONCEPT / CONDITION / STRATEGY / TRANSFORM / COMPUTE / CHECK 之一。
4. demand 只填与这一步相关的维度，取值 0–1：
   V 符号识别、Gf 推理、Gv 空间、WM 工作记忆、Gs 加工速度、LTS 长时记忆、M 元认知。
5. edges 的每一项是 [前置节点, 后继节点]，必须无环；
   第一个节点是 READ，最后一个节点是 CHECK；每个节点至少与另一个节点相连。
6. 关键节点挂 1–2 个探针，整张图至少 2 个探针；探针一次只问一个小问题，选项 2–4 个，不给答案。
7. 每个探针的 targets 至少写 2 个假设 id，只能从 H_L1、H_L2、H_L4 中选：
   H_L1=概念不清（定义、定理条件）；H_L2=条件转译/参数分类；H_L4=执行/计算错误。
8. 不要复述题目，不要输出答案。
9. 每个探针的每个选项都必须有 evidence；键 A/B/C 依次对应 options 的第 1/2/3 个。
   evidence 的值是 log-odds 权重，范围 -1~1：正数表示选这个选项支持该假设，
   负数表示反对；0 等于没写，不要用。
10. evidence 里只能出现该探针 targets 中的假设；每个 target 至少要在一个选项上有非零权重；
    同一探针要让至少两个假设拿到方向相反的权重，否则这个探针没有区分度，不要设。"""

_ISSUE_HINTS = {
    "bad_json": "只输出一个合法 JSON 对象",
    "not_object": "只输出一个 JSON 对象",
    "edge_shape": "edges 的每一项必须是 [前置, 后继]",
    "duplicate_node_id": "节点 id 不能重复",
    "node_count": "节点数必须在 3–20 之间",
    "no_edges": "节点之间必须用 edges 连接",
    "unknown_node_type": "type 只能取允许的七种认知动作",
    "empty_node_text": "每个节点都要有步骤描述",
    "isolated_node": "每个节点都必须接入解法流程",
    "empty_probe_id": "探针必须有 id",
    "empty_probe_question": "探针必须有问题文本",
    "probe_options_too_few": "每个探针至少要有 2 个选项",
    "probe_targets_too_few": "每个探针至少指向 2 个假设",
    "probe_target_unknown": "探针 targets 只能取 H_L1 / H_L2 / H_L4",
    "no_probes": "解法图至少要有一个探针",
    "probe_evidence_missing": "每个探针的每个选项都要有 evidence 权重",
    "probe_evidence_option_missing": "选项 A/B/C 每一个都要有 evidence",
    "probe_evidence_empty": "选项权重不能全为 0，否则答了也不更新后验",
    "probe_evidence_target_unknown": "evidence 的假设键必须在该探针的 targets 里",
    "probe_evidence_target_unused": "每个 target 至少在一个选项上有非零权重",
    "probe_evidence_no_contrast": "同一探针的权重必须有正有负，否则无法区分假设",
    "evidence_option_dropped": "evidence 的选项键只能是 A/B/C，并与 options 数量一致",
    "evidence_value_dropped": "evidence 的权重必须是有限数字",
    "evidence_clamped": "evidence 权重必须在 -1~1 之间",
}

_DEGENERATE_CODES = frozenset({"node_count", "no_edges", "isolated_node", "no_probes"})


class _Rejected(Exception):
    def __init__(self, reason: GraphFailureReason, issues: Sequence[str]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.issues = tuple(issues)


class _ProbePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str
    question: str
    options: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    evidence: dict[str, dict[str, float]] = Field(default_factory=dict)
    hint_level: int = 0


class _NodePayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str
    type: str
    text: str
    demand: dict[str, float] = Field(default_factory=dict)
    common_errors: list[str] = Field(default_factory=list)
    probes: list[_ProbePayload] = Field(default_factory=list)


class _GraphPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nodes: list[_NodePayload]
    edges: list[list[str]] = Field(default_factory=list)


def build_request(draft: ProblemDraft, *, issues: Sequence[str] = ()) -> LLMRequest:
    """One generation request; ``issues`` carries the previous attempt's errors."""
    user = (
        f"学科：{draft.subject}\n"
        f"学段：{draft.grade}\n"
        f"题目：\n{draft.text.strip()}\n\n"
        "请输出解法图 JSON。"
    )
    feedback = _feedback(issues)
    if feedback:
        user += f"\n\n上一次输出未通过校验，必须修正以下问题后重新输出完整 JSON：\n{feedback}"
    return LLMRequest(
        purpose="graph_build",
        system=GRAPH_SYSTEM_PROMPT,
        user=user,
        schema_name="solution_graph",
        json_schema=None,
        max_tokens=GRAPH_MAX_TOKENS,
    )


def to_payload(graph: SolutionGraph) -> dict[str, object]:
    """Serialise a graph into the shape the spec validates.

    ``Probe.correct_option`` is deliberately absent: the schema forbids it and
    the builder never receives answer keys.
    """
    return {
        "problem_id": graph.problem_id,
        "version": graph.version,
        "stem": graph.stem,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "text": node.text,
                "demand": dict(node.demand),
                "common_errors": list(node.common_errors),
                "probes": [
                    {
                        "id": probe.id,
                        "question": probe.question,
                        "options": list(probe.options),
                        "targets": list(probe.targets),
                        "evidence": {
                            option: dict(weights) for option, weights in probe.evidence.items()
                        },
                        "hint_level": probe.hint_level,
                    }
                    for probe in node.probes
                ],
            }
            for node in graph.nodes
        ],
        "edges": [[source, target] for source, target in graph.edges],
    }


def validate_payload(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Run the real spec; returns human-readable errors, empty when valid."""
    validator = Draft202012Validator(_solution_graph_schema())
    errors = sorted(
        validator.iter_errors(dict(payload)),
        key=lambda error: "/".join(str(part) for part in error.absolute_path),
    )
    formatted: list[str] = []
    for error in errors:
        path = "/".join(str(part) for part in error.absolute_path)
        formatted.append(f"{path or '$'}: {error.message}")
    return tuple(formatted)


class LLMGraphGenerator:
    def __init__(
        self,
        client: LLMClient,
        *,
        settings: LLMSettings,
        auditor: CallAuditor | None = None,
        cache_size: int = GRAPH_CACHE_SIZE,
    ) -> None:
        self._client = client
        self._settings = settings
        self._auditor = auditor
        self._cache: dict[str, GraphBuildResult] = {}
        self._cache_size = max(0, cache_size)

    def generate(self, draft: ProblemDraft) -> GraphBuildResult:
        if not self._settings.llm_enabled:
            raise GraphBuildFailed(
                "disabled",
                detail="SYNAPSE_LLM_MODE=off 或缺少 API key；没有可用的规则建图路径",
            )
        if not PROBLEM_ID_PATTERN.fullmatch(draft.id):
            raise GraphBuildFailed(
                "invalid_draft",
                detail=f"problem id {draft.id!r} 不符合 ^P_[A-Z0-9_]+$",
            )

        cache_key = _cache_key(draft, self._settings)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return replace(cached, cached=True)

        attempts = max(1, self._settings.max_attempts)
        issues: tuple[str, ...] = ()
        reason: GraphFailureReason = "schema_invalid"

        for attempt in range(attempts):
            request = build_request(draft, issues=issues)
            try:
                response = self._client.complete(
                    request,
                    timeout_s=self._settings.graph_timeout_s,
                )
            except LLMTimeout as exc:
                # A timeout is not a schema failure: retrying it is how the
                # first-question budget gets blown (chapter 12 §12.8).
                self._audit(None, schema_ok=False, retried=attempt > 0, reason="timeout")
                raise GraphBuildFailed(
                    "timeout",
                    detail=str(exc),
                    attempts=attempt + 1,
                ) from exc
            except LLMCallFailed as exc:
                self._audit(None, schema_ok=False, retried=attempt > 0, reason="transport")
                raise GraphBuildFailed(
                    "transport",
                    detail=str(exc),
                    attempts=attempt + 1,
                ) from exc

            try:
                check = _build_graph(draft, response.text)
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

            digest = fingerprint(check.graph)
            self._audit(
                response,
                schema_ok=True,
                retried=attempt > 0,
                fingerprint=digest,
            )
            result = GraphBuildResult(
                graph=check.graph,
                fingerprint=digest,
                attempts=attempt + 1,
                repairs=check.repairs,
                notes=quality_notes(check.graph),
            )
            self._store(cache_key, result)
            return result

        raise GraphBuildFailed(
            reason,
            detail="; ".join(issues[:5]),
            attempts=attempts,
        )

    def _store(self, key: str, result: GraphBuildResult) -> None:
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
    ) -> None:
        if self._auditor is None:
            return
        context = trace.current()
        self._auditor.record(
            AuditEntry(
                kind="graph_build",
                session_id=context.session_id if context else "",
                turn=context.turn if context else 0,
                model=response.model if response else self._settings.model,
                prompt_version=self._settings.graph_prompt_version,
                latency_ms=response.latency_ms if response else 0,
                prompt_tokens=response.prompt_tokens if response else 0,
                completion_tokens=response.completion_tokens if response else 0,
                retried=retried,
                fallback_reason=reason,
                schema_ok=schema_ok,
                graph_fingerprint=fingerprint,
            )
        )


def _build_graph(draft: ProblemDraft, text: str) -> GraphCheck:
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _Rejected("bad_json", (f"bad_json: {exc.msg}",)) from exc
    if not isinstance(raw, dict):
        raise _Rejected("bad_json", ("not_object: 响应必须是 JSON 对象",))

    try:
        payload = _GraphPayload.model_validate(raw)
    except ValidationError as exc:
        raise _Rejected("schema_invalid", _format_validation(exc)) from exc

    nodes = tuple(_node(item) for item in payload.nodes)
    edges: list[tuple[str, str]] = []
    for edge in payload.edges:
        if len(edge) != 2:
            raise _Rejected("schema_invalid", ("edge_shape: edges 的每一项必须是 [前置, 后继]",))
        edges.append((edge[0], edge[1]))

    graph = SolutionGraph(
        problem_id=draft.id,
        version="g1",
        stem=draft.text,
        nodes=nodes,
        edges=tuple(edges),
    )
    check = review(
        graph,
        allowed_targets=ALLOWED_PROBE_TARGETS,
        require_evidence=True,
    )
    if not check.ok:
        raise _Rejected(_classify(check.issues), check.issues)

    spec_errors = validate_payload(to_payload(check.graph))
    if spec_errors:
        raise _Rejected("schema_invalid", spec_errors)
    return check


def _node(item: _NodePayload) -> SolutionNode:
    return SolutionNode(
        id=item.id,
        type=item.type,
        text=item.text,
        demand=dict(item.demand),
        common_errors=tuple(item.common_errors),
        probes=tuple(
            Probe(
                id=probe.id,
                question=probe.question,
                options=tuple(probe.options),
                targets=tuple(probe.targets),
                hint_level=probe.hint_level,
                evidence={option: dict(weights) for option, weights in probe.evidence.items()},
            )
            for probe in item.probes
        ),
    )


def _classify(issues: Sequence[str]) -> GraphFailureReason:
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


def _cache_key(draft: ProblemDraft, settings: LLMSettings) -> str:
    raw = "\x1f".join(
        (
            draft.id,
            draft.subject,
            draft.grade,
            settings.model,
            settings.graph_prompt_version,
            draft.text.strip(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _solution_graph_schema() -> dict[str, object]:
    path = _repo_root() / "specs" / "solution-graph.schema.json"
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} is not a JSON object")
    return cast(dict[str, object], loaded)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "specs" / "solution-graph.schema.json").is_file():
            return parent
    raise RuntimeError(
        "specs/solution-graph.schema.json not found; graph generation requires the repo checkout"
    )
