"""The process coach: honest process feedback for attempted and blank problems.

The product boundary is the test target, not only the happy path:

* the rule result quotes the student's own attempt/work and never outputs a
  final answer, score, rank or ability claim;
* a blank attempt gets a start plan, not a fabricated diagnosis;
* the model path is optional. A valid JSON answer may set ``mode="llm"``; a
  timeout, transport error, bad JSON or schema violation returns 200 with
  ``mode="rules"`` and says it fell back;
* the endpoint is on the gated session router (401 with auth on) and never reads
  ``AnswerStore``.
"""

from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.auth.service import AuthService
from synapse.application.diagnosis.coach import (
    CoachUnavailable,
    build_coach_context,
)
from synapse.application.diagnosis.domains import DomainRegistry
from synapse.application.diagnosis.generic_graph import GenericGraphBuildFailed
from synapse.application.shared.llm import LLMRequest, LLMResponse, LLMTimeout
from synapse.infrastructure.auth.build import AuthRuntime
from synapse.infrastructure.auth.settings import AuthSettings
from synapse.infrastructure.llm.coach import parse_narrative
from synapse.infrastructure.llm.settings import LLMSettings

WRITING = "学校是否应该禁止中学生带手机进校园？请写一段议论，说明你的立场和理由。"
ANSWER = "不应该禁止"
WORK = "手机能查资料，也方便联系家长。学校禁止手机，是担心课堂被打断。"
BLANK_PROBLEM = "我的乐高结构总是一推就散，该怎么加固？"

# A real-looking, valid ``coach-v1`` answer. It is process feedback, not a
# solution, and every basis is one the prompt allows.
VALID_COACH_JSON = json.dumps(
    {
        "headline": "先不判对错：这段过程有 2 处可以先自查。",
        "points": [
            {
                "kind": "process_note",
                "text": "你写到「手机能查资料」；这一步的依据是观察还是调查，还没有写出来。",
                "basis": "attempt",
            },
            {
                "kind": "next_step",
                "text": "把「结论 → 理由 → 证据」三行分开写，缺哪一行先补哪一行。",
                "basis": "problem",
            },
        ],
        "next_question": "「方便联系家长」这条理由，对应的证据是哪一条？",
    },
    ensure_ascii=False,
)

FORBIDDEN_IN_FEEDBACK = (
    "正确答案",
    "答案是",
    "最终答案",
    "得分",
    "评分",
    "IQ",
    "能力分",
    "智商",
    "天赋",
    "排名",
)


def _start(
    client: TestClient,
    text: str,
    *,
    answer: str,
    work: str = "",
    subject: str | None = None,
) -> dict[str, object]:
    problem: dict[str, object] = {"text": text}
    if subject is not None:
        problem["subject"] = subject
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": problem,
            "attempt": {"answer": answer, "work": work, "self_report": "unsure"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _coach(client: TestClient, session_id: str, focus: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/sessions/{session_id}/coach",
        json={"focus": focus},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _feedback_text(coach: dict[str, object]) -> str:
    points = cast(list[dict[str, str]], coach["points"])
    return str(coach["headline"]) + "\n".join(point["text"] for point in points)


class _NullAuditor:
    def record(self, entry: object) -> None:
        del entry


class _FakeLLM:
    """A scripted provider: only the coach purpose is interesting here."""

    def __init__(self, coach_text: str = "", *, error: Exception | None = None) -> None:
        self.coach_text = coach_text
        self.error = error
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest, *, timeout_s: float) -> LLMResponse:
        del timeout_s
        self.requests.append(request)
        if request.purpose == "coach":
            if self.error is not None:
                raise self.error
            return LLMResponse(text=self.coach_text, model="fake")
        # Probe rewrite / graph calls get an unusable answer; the real adapters
        # fall back and the coach test never depends on those paths.
        return LLMResponse(text="{}", model="fake")


def _llm_client(fake: _FakeLLM) -> TestClient:
    container = build_container(
        LLMSettings(mode="on", api_key="test-key"),
        llm_client=fake,
        auditor=_NullAuditor(),
        generic_generator=_NullGenericGenerator(),  # type: ignore[arg-type]
    )
    return TestClient(create_app(container))


class _NullGenericGenerator:
    """Skip generic graph generation: these tests only exercise the coach."""

    def generate(self, draft: object) -> object:
        del draft
        raise GenericGraphBuildFailed("coach tests do not build generic graphs")


# --------------------------------------------------------------------------
# Rule path: attempted work
# --------------------------------------------------------------------------


def test_where_wrong_quotes_the_attempt_and_never_gives_a_verdict(
    client: TestClient,
) -> None:
    created = _start(client, WRITING, answer=ANSWER, work=WORK, subject="写作")

    coach = _coach(client, cast(str, created["session_id"]), "where_wrong")

    assert coach["version"] == "0.1"
    assert coach["mode"] == "rules"
    assert coach["focus"] == "where_wrong"
    assert coach["next_question"]
    assert coach["not_claimed"], "the coach must say what it did not claim"
    # The actual attempt/work text is quoted; it is the basis of the feedback.
    assert "手机" in _feedback_text(coach)
    # No final answer, score, rank or ability claim in the feedback itself.
    for field in (
        str(coach["headline"]),
        str(coach["next_question"]),
        *(point["text"] for point in cast(list[dict[str, str]], coach["points"])),
    ):
        assert not any(word in field for word in FORBIDDEN_IN_FEEDBACK)
    assert "answer" not in coach
    assert "solution" not in coach


def test_coach_never_reads_the_answer_store(
    client: TestClient,
    sample_payload: dict[str, object],
) -> None:
    created = client.post("/api/v1/sessions", json=sample_payload)
    assert created.status_code == 201, created.text
    session_id = cast(str, created.json()["session_id"])

    response = client.post(
        f"/api/v1/sessions/{session_id}/coach",
        json={"focus": "where_wrong"},
    )

    assert response.status_code == 200, response.text
    # The stored answer and the stored solution never appear. The student's own
    # "a≥1/e" (in the attempt) is allowed; the catalog's "a∈[1/e,+∞)" is not.
    assert "a∈[1/e" not in response.text
    assert "分 a≤0 与 a>0" not in response.text
    assert "answer" not in response.json()
    assert "solution" not in response.json()


def test_how_to_start_does_not_diagnose_even_when_an_attempt_exists(
    client: TestClient,
) -> None:
    created = _start(client, WRITING, answer=ANSWER, work=WORK, subject="写作")

    coach = _coach(client, cast(str, created["session_id"]), "how_to_start")

    assert coach["focus"] == "how_to_start"
    kinds = [point["kind"] for point in cast(list[dict[str, str]], coach["points"])]
    assert "next_step" in kinds
    assert not any(kind.startswith("missing_") for kind in kinds)
    assert coach["not_claimed"]


# --------------------------------------------------------------------------
# Rule path: blank / not started
# --------------------------------------------------------------------------


@pytest.mark.parametrize("focus", ["how_to_start", "where_wrong"])
def test_blank_attempt_gets_a_start_plan_not_a_diagnosis(
    client: TestClient,
    focus: str,
) -> None:
    created = _start(client, BLANK_PROBLEM, answer="不知道")

    coach = _coach(client, cast(str, created["session_id"]), focus)

    assert coach["mode"] == "rules"
    assert coach["focus"] == focus
    kinds = [point["kind"] for point in cast(list[dict[str, str]], coach["points"])]
    assert "no_attempt" in kinds
    assert "next_step" in kinds
    assert not any(kind.startswith("missing_") for kind in kinds)
    assert coach["not_claimed"]
    assert coach["next_question"]
    # "错在哪" is not answered as a diagnosis when there is no process to read.
    headline = str(coach["headline"])
    if focus == "where_wrong":
        assert "先不给「错在哪」" in headline
    else:
        assert "还没看到你的过程" in headline


# --------------------------------------------------------------------------
# Optional model path
# --------------------------------------------------------------------------


def test_valid_model_json_is_mode_llm() -> None:
    fake = _FakeLLM(VALID_COACH_JSON)
    client = _llm_client(fake)
    created = _start(client, WRITING, answer=ANSWER, work=WORK, subject="写作")

    coach = _coach(client, cast(str, created["session_id"]), "where_wrong")

    assert coach["mode"] == "llm"
    texts = [point["text"] for point in cast(list[dict[str, str]], coach["points"])]
    assert any("手机能查资料" in text for text in texts)
    assert coach["not_claimed"]

    coach_requests = [request for request in fake.requests if request.purpose == "coach"]
    assert coach_requests, "a valid model path should be called"
    prompt = coach_requests[0].user
    assert "手机能查资料" in prompt
    # The prompt carries the problem and the student's text, never the answer.
    assert "a∈[1/e" not in prompt


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (LLMTimeout("slow"), ""),
        (None, "not json at all"),
        (None, '{"headline": "x", "points": [], "next_question": "然后呢？"}'),
        (RuntimeError("boom"), ""),
    ],
    ids=["timeout", "bad-json", "schema-invalid", "exception"],
)
def test_model_failure_falls_back_to_rules_without_leaking(
    error: Exception | None,
    text: str,
) -> None:
    fake = _FakeLLM(text, error=error)
    client = _llm_client(fake)
    created = _start(client, WRITING, answer=ANSWER, work=WORK, subject="写作")

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/coach",
        json={"focus": "where_wrong"},
    )

    assert response.status_code == 200, response.text
    coach = response.json()
    assert coach["mode"] == "rules"
    assert "回退规则版" in coach["disclaimer"]
    assert coach["not_claimed"]
    assert "a∈[1/e" not in response.text
    assert "answer" not in coach
    assert "solution" not in coach


def test_model_parser_rejects_a_final_answer_claim() -> None:
    registry = DomainRegistry()
    context = build_coach_context(
        session_id="S_COACH_UNIT",
        problem_text=WRITING,
        profile=registry.profile_for("writing"),
        checklist=("结论：你想让读者接受什么",),
        answer_text=ANSWER,
        work_text=WORK,
    )
    payload = json.dumps(
        {
            "headline": "这段过程缺证据。",
            "points": [
                {
                    "kind": "missing_evidence",
                    "text": "正确答案是应该禁止。",
                    "basis": "attempt",
                },
                {
                    "kind": "next_step",
                    "text": "补一条证据。",
                    "basis": "problem",
                },
            ],
            "next_question": "证据是哪一条？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(CoachUnavailable) as caught:
        parse_narrative(LLMResponse(text=payload, model="fake"), context)

    assert caught.value.reason == "rejected"


# --------------------------------------------------------------------------
# Auth gate and unknown session
# --------------------------------------------------------------------------


class _AnonymousAuth:
    """A gate-only runtime: every presented token is treated as absent."""

    def authenticate(self, token: str | None) -> None:
        del token
        return None


def test_coach_is_gated_when_auth_is_on() -> None:
    runtime = AuthRuntime(
        service=cast(AuthService, _AnonymousAuth()),
        close=lambda: None,
    )
    container = build_container(
        LLMSettings(mode="off"),
        auth_settings=AuthSettings(enabled=True),
        auth_runtime=runtime,
    )
    anonymous = TestClient(create_app(container))

    response = anonymous.post(
        "/api/v1/sessions/S_ANY/coach",
        json={"focus": "where_wrong"},
    )

    assert response.status_code == 401


def test_coach_is_reachable_when_auth_is_off(client: TestClient) -> None:
    created = _start(client, BLANK_PROBLEM, answer="不知道")
    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/coach",
        json={"focus": "how_to_start"},
    )
    assert response.status_code == 200, response.text


def test_unknown_session_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions/S_DOES_NOT_EXIST/coach",
        json={"focus": "where_wrong"},
    )
    assert response.status_code == 404


def test_unknown_focus_is_422(client: TestClient) -> None:
    created = _start(client, BLANK_PROBLEM, answer="不知道")
    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/coach",
        json={"focus": "solve_it"},
    )
    assert response.status_code == 422
