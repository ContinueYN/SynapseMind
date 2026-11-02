"""Run the fixed product behavior / contract cases in-process and write a report.

This is a **behavior / contract harness**, not a learning-gain study and not an
accuracy benchmark. It answers one narrow question on a fixed case set:

    with the model, RAG and code execution switched off, do the product's
    entry, review, skip and isolation boundaries still behave as promised?

What it deliberately does **not** measure:

* whether a diagnosis is correct, or whether the student learned anything;
* real-student accuracy or any learning outcome;
* generated graphs, knowledge-card retrieval or real code execution (all off);
* natural-language understanding quality.

Usage::

    python scripts/eval/product_behavior.py
    python scripts/eval/product_behavior.py --subset
    python scripts/eval/product_behavior.py --only W01,C02,O01
    python scripts/eval/product_behavior.py --out var/eval/product-behavior.md
    python scripts/eval/product_behavior.py --list

The report goes to ``var/eval/product-behavior-<date>.md`` and ``.json`` by
default. Exit status is non-zero when any case does not meet its expectation;
an ``expected_fail`` case that starts passing is also drift and fails the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
API_SRC = ROOT / "apps" / "api" / "src"
SCRIPTS_EVAL = ROOT / "scripts" / "eval"
for _path in (API_SRC, SCRIPTS_EVAL):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows GBK consoles

# The FastAPI test client warns about its httpx shim on import; that is unrelated
# to this harness and would otherwise look like an error on stderr.
warnings.filterwarnings(
    "ignore", message=r"Using `httpx` with `starlette.testclient` is deprecated.*"
)

# The harness fixes the offline configuration. Individual CHC cases build one
# container with the same flag parser and only that switch on; the environment is
# pinned anyway so a developer shell cannot change the baseline.
os.environ["SYNAPSE_LLM_MODE"] = "off"
os.environ["SYNAPSE_RAG"] = "off"
os.environ["SYNAPSE_EXEC"] = "off"
os.environ["SYNAPSE_CHC_ATTRIBUTION"] = "off"
os.environ.pop("SYNAPSE_SESSION_DB", None)
os.environ.setdefault(
    "SYNAPSE_REVIEW_DB",
    str(ROOT / "var" / "eval" / f"review-harness-{os.getpid()}.sqlite3"),
)

from fastapi.testclient import TestClient  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
from product_behavior_cases import CASES, SUBSET_IDS, Case, Check  # noqa: E402
from synapse.api.deps import build_container  # noqa: E402
from synapse.api.main import create_app  # noqa: E402
from synapse.infrastructure.features import FeatureFlags  # noqa: E402
from synapse.infrastructure.llm.settings import LLMSettings  # noqa: E402

SPEC_PATH = ROOT / "specs" / "generic-review.schema.json"

# The decision frame has no score/rank/recommended/best field at any depth.
FORBIDDEN_REVIEW_KEYS = frozenset({"score", "rank", "recommended", "best"})
ALLOWED_OPTION_KEYS = frozenset({"label", "costs", "risks", "reversible_test"})
# Negations such as "不推荐" / "不排序" are legitimate; these phrases are not.
FORBIDDEN_COPY = ("你错了", "正确答案", "应该选", "建议选", "推荐选", "最佳选项", "排名")

FLAGS = {
    "SYNAPSE_LLM_MODE": "off",
    "SYNAPSE_RAG": "off",
    "SYNAPSE_EXEC": "off",
    "SYNAPSE_CHC_ATTRIBUTION": "off by default; on only for the CHC cases",
}

LIMITATIONS = (
    "这是行为 / 契约 harness，不是学习增益研究，也不是诊断准确率评测。",
    "通过只说明固定输入下这些边界仍成立；不代表产品有效、答案正确或学生学得更好。",
    "用例由作者构造，覆盖的是承诺与接线，不是自然分布的学生样本。",
    "模型、RAG 和代码执行全部关闭：生成图、知识卡引用、真实执行结果未被覆盖。",
    "执行一律 off；skipped 只表示没有运行，不能读成代码正确或通过。",
    "领域识别是线索/关键词启发式：线索表或固定文本变化会让个别用例漂移。",
    "CHC 显示的是题目节点需求标签，不是学生能力分；单题不足以下任何能力结论。",
    "预期失败项是已记录的已知边界，不是“通过”；详见报告中的原因。",
)


@dataclass(frozen=True, slots=True)
class Obs:
    """What one scenario observed, plus two short human-readable notes."""

    fields: dict[str, Any]
    actual: str
    evidence: str


@dataclass(frozen=True, slots=True)
class Result:
    case: Case
    obs: Obs
    checks: tuple[tuple[Check, bool], ...]
    status: str

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "expected_fail"}

    @property
    def failed_checks(self) -> tuple[Check, ...]:
        return tuple(check for check, passed in self.checks if not passed)


# --- Environment -------------------------------------------------------------


class _SentinelExecutor:
    """An injected executor that must never run while ``SYNAPSE_EXEC=off``."""

    def __init__(self, env: Env) -> None:
        self._env = env

    def run(self, command: object) -> object:
        del command
        self._env.executor_calls += 1
        raise AssertionError("SYNAPSE_EXEC=off must not reach the executor")


class Env:
    def __init__(self) -> None:
        self.executor_calls = 0
        self._clients: dict[str, TestClient] = {}
        self._validator = Draft202012Validator(json.loads(SPEC_PATH.read_text(encoding="utf-8")))

    @property
    def validator(self) -> Draft202012Validator:
        return self._validator

    def client(self, config: str = "off") -> TestClient:
        if config not in self._clients:
            self._clients[config] = self._build(config)
        return self._clients[config]

    def _build(self, config: str) -> TestClient:
        # FeatureFlags.from_env keeps the real parser and makes the per-case CHC
        # opt-in literal, while the other switches stay pinned off.
        flags = FeatureFlags.from_env(
            {
                "SYNAPSE_EQUALITY_CHECK": "off",
                "SYNAPSE_RAG": "off",
                "SYNAPSE_EXEC": "off",
                "SYNAPSE_CHC_ATTRIBUTION": "on" if config == "chc_on" else "off",
            }
        )
        executor = _SentinelExecutor(self) if config == "off_sentinel" else None
        settings = LLMSettings(
            mode="off",
            api_key="",
            audit_path=str(ROOT / "var" / "eval" / "harness-audit.jsonl"),
        )
        return TestClient(create_app(build_container(settings, features=flags, executor=executor)))


# --- Small HTTP helpers ------------------------------------------------------


def _json(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _detail(body: Mapping[str, Any]) -> str:
    detail = body.get("detail")
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    return json.dumps(detail, ensure_ascii=False)


def _post_start(client: TestClient, params: Mapping[str, Any]) -> Any:
    problem: dict[str, Any] = {"text": params.get("text", "")}
    subject = params.get("subject")
    if subject:
        problem["subject"] = subject
    return client.post(
        "/api/v1/sessions",
        json={
            "problem": problem,
            "attempt": {
                "answer": params.get("answer", "不知道"),
                "work": params.get("work", ""),
                "self_report": params.get("self_report", "unsure"),
            },
            "mode": "learning",
        },
    )


def _all_keys(node: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        keys.update(node)
        for value in node.values():
            keys |= _all_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


def _drop_none(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _drop_none(value) for key, value in node.items() if value is not None}
    if isinstance(node, list):
        return [_drop_none(item) for item in node]
    return node


def _schema_errors(validator: Draft202012Validator, node: Any) -> list[str]:
    errors = sorted(validator.iter_errors(node), key=lambda error: list(error.path))
    return [
        f"{'/'.join(str(part) for part in error.path) or '$'}: {error.message}" for error in errors
    ]


def _review_copy_texts(review: Mapping[str, Any]) -> list[str]:
    texts = [
        str(review.get("headline") or ""),
        str(review.get("next_step") or ""),
        str(review.get("disclaimer") or ""),
        str(review.get("tradeoff_question") or ""),
        *(str(item) for item in review.get("not_checked") or []),
        *(str(finding.get("summary") or "") for finding in review.get("findings") or []),
    ]
    for option in review.get("options") or []:
        texts.append(str(option.get("label") or ""))
        texts.extend(str(item) for item in option.get("costs") or [])
        texts.extend(str(item) for item in option.get("risks") or [])
        texts.append(str(option.get("reversible_test") or ""))
    return texts


def _session_fields(
    body: Mapping[str, Any],
    params: Mapping[str, Any],
    validator: Draft202012Validator,
) -> dict[str, Any]:
    """Flatten the response fields the cases assert on."""

    intake_raw = body.get("intake")
    intake: Mapping[str, Any] = intake_raw if isinstance(intake_raw, dict) else {}
    review_raw = intake.get("review") if intake else None
    review: Mapping[str, Any] = review_raw if isinstance(review_raw, dict) else {}
    diagnosis_raw = body.get("diagnosis")
    diagnosis: Mapping[str, Any] = diagnosis_raw if isinstance(diagnosis_raw, dict) else {}
    domain: Mapping[str, Any] = body.get("domain") if isinstance(body.get("domain"), dict) else {}

    findings = list(review.get("findings") or [])
    evidence = list(review.get("evidence") or [])
    evidence_ids = {str(item.get("id")) for item in evidence}
    refs_ok = True
    for finding in findings:
        refs = list(finding.get("evidence_refs") or [])
        if not refs or not set(map(str, refs)) <= evidence_ids:
            refs_ok = False

    options = list(review.get("options") or [])
    option_bad_keys = sum(1 for option in options if set(option) != ALLOWED_OPTION_KEYS)
    student_evidence = " ".join(
        str(item.get("excerpt") or "") for item in evidence if item.get("source") == "student"
    )
    needle = params.get("evidence_needle")
    work_in_evidence = bool(needle) and str(needle) in student_evidence

    published_errors = _schema_errors(validator, review) if review else []
    clean_errors = _schema_errors(validator, _drop_none(review)) if review else []
    copy_texts = _review_copy_texts(review)

    return {
        "state": body.get("state"),
        "domain_name": domain.get("name"),
        "domain_label": domain.get("label"),
        "verification": domain.get("verification"),
        "generic": domain.get("generic"),
        "confidence": domain.get("confidence"),
        "has_intake": bool(intake),
        "intake_version": intake.get("version"),
        "observed": list(intake.get("observed") or []),
        "gaps": list(intake.get("gaps") or []),
        "clarifier": intake.get("clarifier"),
        "probe": intake.get("probe"),
        "intake_disclaimer": str(intake.get("disclaimer") or ""),
        "intake_next_step": str(intake.get("next_step") or ""),
        "has_review": bool(review),
        "review_kind": review.get("kind"),
        "review_headline": str(review.get("headline") or ""),
        "review_next_step": str(review.get("next_step") or ""),
        "review_disclaimer": str(review.get("disclaimer") or ""),
        "review_findings_count": len(findings),
        "review_evidence_count": len(evidence),
        "review_not_checked_count": len(review.get("not_checked") or []),
        "review_not_checked_text": " | ".join(
            str(item) for item in review.get("not_checked") or []
        ),
        "finding_kinds": [str(finding.get("kind")) for finding in findings],
        "review_refs_ok": refs_ok,
        "review_forbidden_keys": sorted(_all_keys(review) & FORBIDDEN_REVIEW_KEYS),
        "body_forbidden_keys": sorted(_all_keys(body) & FORBIDDEN_REVIEW_KEYS),
        "review_copy_hits": sorted(
            {phrase for phrase in FORBIDDEN_COPY if any(phrase in text for text in copy_texts)}
        ),
        "options_count": len(options),
        "do_nothing_count": sum(
            1 for option in options if "什么都不做" in str(option.get("label") or "")
        ),
        "option_bad_keys_count": option_bad_keys,
        "tradeoff_question": str(review.get("tradeoff_question") or ""),
        "work_in_evidence": work_in_evidence,
        "review_published_schema_errors_count": len(published_errors),
        "review_published_schema_errors": published_errors,
        "review_clean_schema_errors_count": len(clean_errors),
        "has_answer_key": "answer" in body,
        "has_solution_key": "solution" in body,
        "answer": body.get("answer"),
        "solution_has_text": bool(body.get("solution")),
        "has_diagnosis": bool(diagnosis),
        "diagnosis_version": diagnosis.get("version"),
        "prompt": bool(body.get("prompt")),
        "prompt_question": str((body.get("prompt") or {}).get("question") or ""),
        "notice": str(body.get("notice") or ""),
    }


def _session_actual(fields: Mapping[str, Any]) -> str:
    if fields.get("detail"):
        return f"HTTP {fields.get('status')}: {str(fields['detail'])[:70]}"
    parts = [
        f"HTTP {fields.get('status')}",
        f"state={fields.get('state')}",
        f"domain={fields.get('domain_name') or '-'}/{fields.get('verification') or '-'}",
    ]
    if fields.get("has_review"):
        parts.append(f"review={fields.get('review_kind')}")
    parts.append(f"observed={len(fields.get('observed') or [])}")
    parts.append(f"gaps={len(fields.get('gaps') or [])}")
    return "; ".join(parts)


def _session_evidence(fields: Mapping[str, Any]) -> str:
    detail = str(fields.get("detail") or "")
    if detail:
        return detail[:140]
    headline = str(fields.get("review_headline") or "")
    if headline:
        return f"headline: {headline}"[:140]
    question = str(fields.get("prompt_question") or "")
    if question:
        return f"question: {question}"[:140]
    return f"next: {str(fields.get('review_next_step') or fields.get('notice') or '-')}"[:140]


# --- Scenarios ---------------------------------------------------------------


def _scenario_start(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    response = _post_start(client, params)
    body = _json(response)
    fields = _session_fields(body, params, env.validator)
    fields["status"] = response.status_code
    fields["detail"] = _detail(body)
    return Obs(fields, _session_actual(fields), _session_evidence(fields))


def _scenario_start_reload(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    response = _post_start(client, params)
    body = _json(response)
    fields = _session_fields(body, params, env.validator)
    fields["status"] = response.status_code
    fields["detail"] = _detail(body)
    session_id = body.get("session_id")
    get_status = 0
    review_equal = False
    intake_equal = False
    get_has_answer_key = False
    get_has_solution_key = False
    if response.status_code == 201 and session_id:
        reloaded = client.get(f"/api/v1/sessions/{session_id}")
        get_status = reloaded.status_code
        reload_body = _json(reloaded)
        get_has_answer_key = "answer" in reload_body
        get_has_solution_key = "solution" in reload_body
        review_equal = (body.get("intake") or {}).get("review") == (
            reload_body.get("intake") or {}
        ).get("review")
        intake_equal = body.get("intake") == reload_body.get("intake")
    fields.update(
        get_status=get_status,
        review_equal=review_equal,
        intake_equal=intake_equal,
        get_has_answer_key=get_has_answer_key,
        get_has_solution_key=get_has_solution_key,
    )
    return Obs(fields, _session_actual(fields), _session_evidence(fields))


def _scenario_review_run(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    body = _json(started)
    fields = _session_fields(body, params, env.validator)
    fields["start_status"] = started.status_code
    fields["status"] = started.status_code
    fields["detail"] = _detail(body)
    session_id = body.get("session_id")
    if started.status_code == 201 and session_id:
        before = _json(client.get(f"/api/v1/sessions/{session_id}"))
        code = str(params.get("code") or "")
        tests = str(params.get("tests") or "")
        response = client.post(
            f"/api/v1/sessions/{session_id}/review/run",
            json={"code": code, "tests": tests},
        )
        review = _json(response)
        after = _json(client.get(f"/api/v1/sessions/{session_id}"))
        execution = review.get("execution")
        execution = execution if isinstance(execution, dict) else {}
        fields.update(
            status=response.status_code,
            detail=_detail(review),
            kind=review.get("kind"),
            execution_status=execution.get("status"),
            tests_submitted=bool(execution.get("tests_submitted", False)),
            headline=str(review.get("headline") or ""),
            review_findings_count=len(review.get("findings") or []),
            review_evidence_count=len(review.get("evidence") or []),
            code_echoed=bool(code.strip()) and code in json.dumps(review, ensure_ascii=False),
            has_answer_key="answer" in review,
            has_solution_key="solution" in review,
            executor_calls=env.executor_calls,
            session_unchanged=before == after,
            schema_errors_count=(
                len(_schema_errors(env.validator, review)) if response.status_code == 200 else 0
            ),
        )
    actual = (
        f"HTTP {fields['status']}; kind={fields.get('kind')}; "
        f"execution={fields.get('execution_status')}; "
        f"tests_submitted={fields.get('tests_submitted')}; "
        f"findings={fields.get('review_findings_count')}; calls={fields.get('executor_calls')}"
    )
    evidence = str(fields.get("headline") or fields.get("detail") or "-")[:140]
    return Obs(fields, actual, evidence)


def _scenario_executions(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    response = client.post(
        "/api/v1/executions",
        json={"language": "python", "code": "print('HARNESS_EXEC')\n"},
    )
    body = _json(response)
    fields = {
        "status": response.status_code,
        "detail": _detail(body),
        "executor_calls": env.executor_calls,
    }
    actual = f"HTTP {fields['status']}; calls={fields['executor_calls']}"
    return Obs(fields, actual, str(fields["detail"] or "-")[:140])


def _scenario_agent_run(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    start_body = _json(started)
    fields = _session_fields(start_body, params, env.validator)
    fields["start_status"] = started.status_code
    fields["status"] = started.status_code
    fields["detail"] = _detail(start_body)
    session_id = start_body.get("session_id")
    if started.status_code == 201 and session_id:
        before = _json(client.get(f"/api/v1/sessions/{session_id}"))
        response = client.post(
            f"/api/v1/sessions/{session_id}/agent/run",
            json={
                "code": str(params.get("code") or ""),
                "tests": str(params.get("tests") or ""),
            },
        )
        trace = _json(response)
        after = _json(client.get(f"/api/v1/sessions/{session_id}"))
        steps = list(trace.get("steps") or [])
        run_steps = [step for step in steps if step.get("tool") in {"run_code", "run_tests"}]
        planner = trace.get("planner")
        planner = planner if isinstance(planner, dict) else {}
        fields.update(
            status=response.status_code,
            detail=_detail(trace),
            trace_version=trace.get("version"),
            steps_count=len(steps),
            tools=[str(step.get("tool")) for step in steps],
            statuses=[str(step.get("status")) for step in steps],
            has_run_step=bool(run_steps),
            run_step_status=run_steps[0].get("status") if run_steps else None,
            planner_status=planner.get("status"),
            session_unchanged=before == after,
            has_answer_key="answer" in trace,
            has_solution_key="solution" in trace,
            executor_calls=env.executor_calls,
        )
    actual = (
        f"HTTP {fields['status']}; steps={fields.get('steps_count')}; "
        f"run={fields.get('run_step_status')}; planner={fields.get('planner_status')}; "
        f"unchanged={fields.get('session_unchanged')}"
    )
    return Obs(fields, actual, str(fields.get("detail") or fields.get("notice") or "-")[:140])


def _scenario_clarifier_flow(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    start_body = _json(started)
    fields = _session_fields(start_body, params, env.validator)
    fields["start_status"] = started.status_code
    fields["status"] = started.status_code
    fields["detail"] = _detail(start_body)
    session_id = start_body.get("session_id")
    if started.status_code == 201 and session_id:
        first = client.post(
            f"/api/v1/sessions/{session_id}/intake",
            json={"answer": str(params.get("clarifier_answer") or "")},
        )
        first_body = _json(first)
        first_intake = first_body.get("intake") or {}
        second = client.post(
            f"/api/v1/sessions/{session_id}/intake",
            json={"answer": str(params.get("second_answer") or "")},
        )
        second_body = _json(second)
        second_intake = second_body.get("intake") or {}
        fields.update(
            status=first.status_code,
            detail=_detail(first_body),
            domain_name=(first_body.get("domain") or {}).get("name"),
            domain_label=(first_body.get("domain") or {}).get("label"),
            clarifier_after_first=first_intake.get("clarifier"),
            notice=str(first_body.get("notice") or ""),
            gaps=list(first_intake.get("gaps") or []),
            has_answer_key="answer" in first_body,
            second_status=second.status_code,
            second_notice=str(second_body.get("notice") or ""),
            gaps_equal=(first_intake.get("gaps") or []) == (second_intake.get("gaps") or []),
            second_clarifier=second_intake.get("clarifier"),
        )
    actual = (
        f"HTTP {fields['status']}; domain={fields.get('domain_name')}; "
        f"clarifier={bool(fields.get('clarifier_after_first'))}; "
        f"second={fields.get('second_status')}"
    )
    return Obs(fields, actual, str(fields.get("notice") or fields.get("detail") or "-")[:140])


def _scenario_intake_answer(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    start_body = _json(started)
    fields = _session_fields(start_body, params, env.validator)
    fields["start_status"] = started.status_code
    fields["status"] = started.status_code
    fields["detail"] = _detail(start_body)
    session_id = start_body.get("session_id")
    if started.status_code == 201 and session_id:
        endpoint = str(params.get("endpoint") or "intake")
        response = client.post(
            f"/api/v1/sessions/{session_id}/{endpoint}",
            json={"answer": str(params.get("post") or "")},
        )
        body = _json(response)
        intake = body.get("intake") if isinstance(body.get("intake"), dict) else {}
        fields.update(
            status=response.status_code,
            detail=_detail(body),
            domain_name=(body.get("domain") or {}).get("name"),
            domain_label=(body.get("domain") or {}).get("label"),
            clarifier_after_post=intake.get("clarifier"),
            has_diagnosis=bool(body.get("diagnosis")),
            notice=str(body.get("notice") or ""),
        )
    actual = f"HTTP {fields['status']}; domain={fields.get('domain_name')}"
    if fields.get("detail"):
        actual += f"; detail={fields['detail']}"
    return Obs(fields, actual[:160], str(fields.get("detail") or fields.get("notice") or "-")[:140])


def _scenario_probe_flow(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    start_body = _json(started)
    fields = _session_fields(start_body, params, env.validator)
    fields["start_status"] = started.status_code
    fields["status"] = started.status_code
    fields["detail"] = _detail(start_body)
    session_id = start_body.get("session_id")
    answered: list[Any] = []
    statuses: list[int] = []
    first_probe: Any = (start_body.get("intake") or {}).get("probe")
    last_body: dict[str, Any] = start_body
    fourth_status = 0
    if started.status_code == 201 and session_id:
        for answer in params.get("answers") or []:
            response = client.post(
                f"/api/v1/sessions/{session_id}/intake/probe",
                json={"answer": str(answer)},
            )
            body = _json(response)
            probe = (body.get("intake") or {}).get("probe")
            answered.append(probe.get("answered") if isinstance(probe, dict) else None)
            statuses.append(response.status_code)
            last_body = body
        fourth = client.post(
            f"/api/v1/sessions/{session_id}/intake/probe",
            json={"answer": "再补一句。"},
        )
        fourth_status = fourth.status_code
    fields.update(
        first_probe=bool(first_probe),
        statuses=statuses,
        answered=answered,
        last_probe_none=bool(answered) and answered[-1] is None,
        fourth_status=fourth_status,
        state=last_body.get("state"),
        has_diagnosis=bool(last_body.get("diagnosis")),
        notice=str(last_body.get("notice") or ""),
    )
    actual = f"answered={answered}; statuses={statuses}; fourth={fourth_status}"
    return Obs(fields, actual, str(fields.get("notice") or fields.get("detail") or "-")[:140])


def _scenario_chc_card(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    body = _json(started)
    start_status = started.status_code
    status = start_status
    session_id = body.get("session_id")
    if start_status == 201 and session_id:
        for _ in range(6):
            if body.get("diagnosis") or not body.get("prompt"):
                break
            response = client.post(
                f"/api/v1/sessions/{session_id}/turns",
                json={"answer": "没有检查", "option_id": "A"},
            )
            status = response.status_code
            body = _json(response)
    diagnosis = body.get("diagnosis") if isinstance(body.get("diagnosis"), dict) else {}
    card = diagnosis.get("card") if isinstance(diagnosis.get("card"), dict) else {}
    attribution = card.get("attribution") if isinstance(card.get("attribution"), dict) else {}
    dimensions = list(attribution.get("dimensions") or [])
    all_dimensions = list(attribution.get("all_dimensions") or [])
    fields = {
        "start_status": start_status,
        "status": status,
        "state": body.get("state"),
        "turn": body.get("turn"),
        "has_diagnosis": bool(diagnosis),
        "diagnosis_version": diagnosis.get("version"),
        "has_attribution": "attribution" in card,
        "dims": [dimension.get("key") for dimension in dimensions],
        "all_dims": [dimension.get("key") for dimension in all_dimensions],
        "all_dim_count": len(all_dimensions),
        "note": str(attribution.get("note") or ""),
        "card_ability_keys": sorted(_all_keys(card) & {"score", "ability", "iq"}),
        "has_answer_key": "answer" in body,
    }
    actual = (
        f"version={fields['diagnosis_version']}; dims={fields['dims']}; "
        f"all={fields['all_dim_count']}; state={fields['state']}"
    )
    return Obs(fields, actual, str(fields.get("note") or "-")[:140])


def _scenario_exit_flow(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    start_body = _json(started)
    fields = _session_fields(start_body, params, env.validator)
    fields["status"] = started.status_code
    fields["detail"] = _detail(start_body)
    session_id = start_body.get("session_id")
    if started.status_code == 201 and session_id:
        reveal = params.get("reveal")
        if reveal is None:
            response = client.post(f"/api/v1/sessions/{session_id}/exit")
        else:
            response = client.post(
                f"/api/v1/sessions/{session_id}/exit",
                json={"reveal": bool(reveal)},
            )
        body = _json(response)
        fields.update(
            status=response.status_code,
            detail=_detail(body),
            state=body.get("state"),
            has_answer_key="answer" in body,
            answer=body.get("answer"),
            has_solution_key="solution" in body,
            solution_has_text=bool(body.get("solution")),
            notice=str(body.get("notice") or ""),
        )
    actual = (
        f"HTTP {fields['status']}; state={fields.get('state')}; "
        f"answer_key={fields.get('has_answer_key')}; "
        f"solution_key={fields.get('has_solution_key')}"
    )
    return Obs(fields, actual, str(fields.get("notice") or fields.get("detail") or "-")[:140])


def _scenario_turn_on_generic(env: Env, params: Mapping[str, Any]) -> Obs:
    client = env.client(str(params.get("config") or "off"))
    started = _post_start(client, params)
    start_body = _json(started)
    fields = _session_fields(start_body, params, env.validator)
    fields["start_status"] = started.status_code
    fields["status"] = started.status_code
    fields["detail"] = _detail(start_body)
    session_id = start_body.get("session_id")
    if started.status_code == 201 and session_id:
        response = client.post(
            f"/api/v1/sessions/{session_id}/turns",
            json={"answer": "选北京", "option_id": "A"},
        )
        body = _json(response)
        fields.update(
            status=response.status_code,
            detail=_detail(body),
            state=body.get("state"),
            has_diagnosis=bool(body.get("diagnosis")),
            notice=str(body.get("notice") or ""),
            has_intake=bool(body.get("intake")),
        )
    actual = (
        f"HTTP {fields['status']}; state={fields.get('state')}; "
        f"diagnosis={fields.get('has_diagnosis')}"
    )
    return Obs(fields, actual, str(fields.get("notice") or "-")[:140])


SCENARIOS: dict[str, Callable[[Env, Mapping[str, Any]], Obs]] = {
    "start": _scenario_start,
    "start_reload": _scenario_start_reload,
    "review_run": _scenario_review_run,
    "executions": _scenario_executions,
    "agent_run": _scenario_agent_run,
    "clarifier_flow": _scenario_clarifier_flow,
    "intake_answer": _scenario_intake_answer,
    "probe_flow": _scenario_probe_flow,
    "chc_card": _scenario_chc_card,
    "exit_flow": _scenario_exit_flow,
    "turn_on_generic": _scenario_turn_on_generic,
}


# --- Check engine ------------------------------------------------------------


def _contains(actual: Any, value: Any) -> bool:
    if isinstance(actual, str):
        return str(value) in actual
    if isinstance(actual, (list, tuple, set, dict)):
        return value in actual
    return False


_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda actual, value: actual == value,
    "ne": lambda actual, value: actual != value,
    "in": lambda actual, value: actual in value,
    "not_in": lambda actual, value: actual not in value,
    "contains": _contains,
    "not_contains": lambda actual, value: not _contains(actual, value),
    "truthy": lambda actual, value: bool(actual),
    "falsy": lambda actual, value: not actual,
    "ge": lambda actual, value: actual is not None and actual >= value,
    "le": lambda actual, value: actual is not None and actual <= value,
    "len_eq": lambda actual, value: len(actual) == value,
    "len_ge": lambda actual, value: len(actual) >= value,
    "len_le": lambda actual, value: len(actual) <= value,
    "ends_with": lambda actual, value: isinstance(actual, str) and actual.endswith(value),
    "starts_with": lambda actual, value: isinstance(actual, str) and actual.startswith(value),
}


def _evaluate(fields: Mapping[str, Any], check: Check) -> bool:
    if check.key not in fields:
        return False
    op = _OPS.get(check.op)
    if op is None:
        raise ValueError(f"unknown check op: {check.op}")
    return bool(op(fields[check.key], check.value))


def _short(value: Any, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _run_case(env: Env, case: Case) -> Result:
    scenario = SCENARIOS.get(case.scenario)
    if scenario is None:
        obs = Obs(
            {"status": 0, "detail": f"unknown scenario: {case.scenario}"},
            "scenario missing",
            "scenario missing",
        )
    else:
        try:
            obs = scenario(env, dict(case.params))
        except Exception as exc:  # noqa: BLE001 - a crash is recorded, not hidden
            obs = Obs(
                {"status": 0, "detail": f"{type(exc).__name__}: {exc}"},
                "scenario crashed",
                f"{type(exc).__name__}: {exc}"[:140],
            )
    checks = tuple((check, _evaluate(obs.fields, check)) for check in case.checks)
    all_passed = all(passed for _, passed in checks)
    if all_passed:
        status = "pass" if case.expected == "pass" else "unexpected_pass"
    else:
        status = "fail" if case.expected == "pass" else "expected_fail"
    return Result(case=case, obs=obs, checks=checks, status=status)


def run_cases(cases: tuple[Case, ...] | list[Case]) -> list[Result]:
    """Run cases in order with one shared in-process environment."""

    env = Env()
    return [_run_case(env, case) for case in cases]


# --- Reports -----------------------------------------------------------------

STATUS_LABELS = {
    "pass": "通过",
    "expected_fail": "预期失败",
    "fail": "失败",
    "unexpected_pass": "意外通过",
}


def _counts(results: list[Result]) -> dict[str, int]:
    return {
        "cases": len(results),
        "passed": sum(1 for result in results if result.status == "pass"),
        "expected_fail": sum(1 for result in results if result.status == "expected_fail"),
        "failed": sum(1 for result in results if result.status == "fail"),
        "unexpected_pass": sum(1 for result in results if result.status == "unexpected_pass"),
    }


def _categories(results: list[Result]) -> list[str]:
    seen: list[str] = []
    for result in results:
        if result.case.category not in seen:
            seen.append(result.case.category)
    return seen


def _cell(value: Any, limit: int = 90) -> str:
    return _short(value, limit).replace("|", "\\|")


def render_markdown(results: list[Result], meta: Mapping[str, Any]) -> str:
    counts = _counts(results)
    lines: list[str] = [
        "# 产品行为 / 契约 harness 报告",
        "",
        "> **这是行为 / 契约 harness，不是学习增益研究，也不是诊断准确率报告。**",
        "> 它只回答：在固定输入和固定开关下，入口、复盘、跳过与答案隔离的边界是否仍然成立。",
        "> 通过不代表产品有效，也不代表学生学得更好。",
        "",
        "## 环境",
        "",
        f"- 日期：{meta['date']}",
        f"- 命令：`{meta['command']}`",
        "- 固定开关：`SYNAPSE_LLM_MODE=off`、`SYNAPSE_RAG=off`、`SYNAPSE_EXEC=off`；"
        "只有 CHC 用例把 `SYNAPSE_CHC_ATTRIBUTION` 设为 `on`。",
        "- 运行方式：进程内 FastAPI `TestClient`；无网络、无模型 key、无 RAG 模型。",
        "",
        "## 汇总",
        "",
        f"- 用例：{counts['cases']}",
        f"- 通过：{counts['passed']}",
        f"- 预期失败（已记录的边界）：{counts['expected_fail']}",
        f"- 非预期失败：{counts['failed']}",
        f"- 预期失败却通过（漂移）：{counts['unexpected_pass']}",
        "",
        "## 分类",
        "",
        "| 类别 | 用例 | 通过 | 预期失败 | 非预期失败 |",
        "|---|---:|---:|---:|---:|",
    ]
    for category in _categories(results):
        rows = [result for result in results if result.case.category == category]
        category_counts = _counts(rows)
        lines.append(
            f"| {category} | {category_counts['cases']} | {category_counts['passed']} | "
            f"{category_counts['expected_fail']} | "
            f"{category_counts['failed'] + category_counts['unexpected_pass']} |"
        )

    lines += ["", "## 逐案结果", ""]
    for category in _categories(results):
        rows = [result for result in results if result.case.category == category]
        lines += [
            f"### {category}（{len(rows)}）",
            "",
            "| id | 意图 | 期望契约 | 实际 | 证据 | 结果 |",
            "|---|---|---|---|---|---|",
        ]
        for result in rows:
            lines.append(
                f"| `{result.case.id}` | {_cell(result.case.intent)} | "
                f"{_cell(result.case.contract)} | {_cell(result.obs.actual)} | "
                f"{_cell(result.obs.evidence)} | {STATUS_LABELS[result.status]} |"
            )
        lines.append("")

    expected = [result for result in results if result.status == "expected_fail"]
    lines += ["## 预期失败（已记录的边界，不计为通过）", ""]
    if not expected:
        lines.append("无。")
        lines.append("")
    for result in expected:
        lines += [
            f"### `{result.case.id}` — {result.case.intent}",
            "",
            f"- 原因：{result.case.reason or '（未填写）'}",
            f"- 实际：{result.obs.actual}",
            f"- 未满足的检查：{_cell([check.label for check in result.failed_checks], 160)}",
        ]
        schema_errors = result.obs.fields.get("review_published_schema_errors") or []
        if schema_errors:
            lines.append(f"- schema 错误：{_cell(schema_errors, 220)}")
        lines.append("")

    unexpected = [result for result in results if not result.ok]
    lines += ["## 非预期失败", ""]
    if not unexpected:
        lines.append("无。")
        lines.append("")
    for result in unexpected:
        detail = "; ".join(
            f"{check.key}={_short(result.obs.fields.get(check.key))}"
            for check in result.failed_checks
        )
        lines += [
            f"### `{result.case.id}` — {STATUS_LABELS[result.status]}",
            "",
            f"- 意图：{result.case.intent}",
            f"- 期望契约：{result.case.contract}",
            f"- 实际：{result.obs.actual}",
            f"- 未满足的检查：{detail or '（无检查失败，但期望状态不符）'}",
            "",
        ]

    lines += ["## 局限", ""]
    lines.extend(f"- {item}" for item in LIMITATIONS)
    lines += [
        "",
        "> 结论：这是回归护栏，不是效果证明。通过数不能用于宣传、对比或推断学习收益。",
        "",
    ]
    return "\n".join(lines)


def build_json(results: list[Result], meta: Mapping[str, Any]) -> dict[str, Any]:
    counts = _counts(results)
    categories = []
    for category in _categories(results):
        rows = [result for result in results if result.case.category == category]
        category_counts = _counts(rows)
        categories.append({"name": category, **category_counts})
    return {
        "version": "0.1",
        "kind": "behavior-contract-harness",
        "disclaimer": (
            "行为/契约 harness，不是学习增益研究，也不是准确率评测；通过数不能用于效果或能力结论。"
        ),
        "date": meta["date"],
        "command": meta["command"],
        "flags": FLAGS,
        "totals": counts,
        "categories": categories,
        "cases": [
            {
                "id": result.case.id,
                "category": result.case.category,
                "intent": result.case.intent,
                "contract": result.case.contract,
                "scenario": result.case.scenario,
                "expected": result.case.expected,
                "status": result.status,
                "actual": result.obs.actual,
                "evidence": result.obs.evidence,
                "failed_checks": [
                    {
                        "label": check.label,
                        "field": check.key,
                        "expected": _short(check.value, 120),
                        "actual": _short(result.obs.fields.get(check.key), 120),
                    }
                    for check in result.failed_checks
                ],
                "reason": result.case.reason,
            }
            for result in results
        ],
        "limitations": list(LIMITATIONS),
    }


# --- CLI ---------------------------------------------------------------------


def _select_cases(only: str, subset: bool) -> tuple[Case, ...]:
    if subset:
        return tuple(case for case in CASES if case.id in SUBSET_IDS)
    if not only.strip():
        return CASES
    wanted = {item.strip() for item in only.split(",") if item.strip()}
    known = {case.id for case in CASES}
    missing = sorted(wanted - known)
    if missing:
        raise SystemExit(f"unknown case id(s): {', '.join(missing)}")
    return tuple(case for case in CASES if case.id in wanted)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", action="store_true", help="run the fast CI subset only")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--list", action="store_true", help="list case ids and exit")
    parser.add_argument("--out", type=Path, default=None, help="Markdown output path")
    parser.add_argument("--json-out", type=Path, default=None, help="JSON output path")
    parser.add_argument("--date", default=None, help="report date (default: today, ISO)")
    args = parser.parse_args(argv)

    if args.list:
        for case in CASES:
            marker = " (subset)" if case.id in SUBSET_IDS else ""
            print(f"{case.id}\t{case.category}\t{case.intent}{marker}")
        return 0

    cases = _select_cases(args.only, args.subset)
    if not cases:
        print("no cases selected")
        return 2

    results = run_cases(cases)
    counts = _counts(results)
    report_date = args.date or date.today().isoformat()
    command = "python scripts/eval/product_behavior.py"
    if args.subset:
        command += " --subset"
    if args.only:
        command += f" --only {args.only}"
    meta = {"date": report_date, "command": command}

    md_path = args.out or ROOT / "var" / "eval" / f"product-behavior-{report_date}.md"
    json_path = args.json_out or md_path.with_suffix(".json")
    for path in (md_path, json_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(results, meta), encoding="utf-8")
    json_path.write_text(
        json.dumps(build_json(results, meta), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"product behavior harness: {counts['passed']} passed, "
        f"{counts['expected_fail']} expected-fail, {counts['failed']} failed, "
        f"{counts['unexpected_pass']} unexpected-pass ({counts['cases']} cases)"
    )
    print(f"md: {md_path}")
    print(f"json: {json_path}")
    if counts["failed"] or counts["unexpected_pass"]:
        bad = [result.case.id for result in results if not result.ok]
        print(f"unexpected: {', '.join(bad)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
