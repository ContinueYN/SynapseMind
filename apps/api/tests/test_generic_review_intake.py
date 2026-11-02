"""T3: the generic review is attached to the intake, not to a diagnosis.

The intake stays the honest floor it was in v0.4; v0.5 only adds an optional
``review``. These tests pin the two boundaries that make that safe:

* the review is composed for the argumentative modes (writing / research /
  decision / generic) when there is an attempt, and is absent for formal,
  empirical and executable modes — the composer has no branch for them;
* a composer failure is swallowed at the entry: the old intake fields are still
  served with ``review=None``, and nothing is rewritten as a fake check.

The published review shape is still v0.1; the intake contract is v0.5.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from synapse.application.diagnosis import intake as intake_module
from synapse.application.diagnosis.domains import DomainRegistry
from synapse.application.diagnosis.intake import build_domain_intake
from synapse.domain.problem.models import Problem, SolutionGraph

REGISTRY = DomainRegistry()

DECISION = "我应该接受北京的工作机会，还是留在上海陪家人？"
DECISION_ATTEMPT = "我想在两年内转做后端。要么留在现在的公司转岗，要么跳槽去小厂。但我怕收入下降。"
WRITING = "我想论证远程办公更好。因为省通勤。因此公司应该继续。"
CODE = "我的 Python 脚本报错了：IndexError: list index out of range，应该怎么修？"

REVIEW_KEYS = {
    "version",
    "session_id",
    "problem_id",
    "kind",
    "domain",
    "headline",
    "findings",
    "evidence",
    "not_checked",
    "next_step",
    "disclaimer",
}
FORBIDDEN_DECISION_KEYS = frozenset({"score", "rank", "recommended", "best"})


def _start(
    client: TestClient,
    text: str,
    *,
    answer: str,
    subject: str | None = None,
    work: str = "",
) -> dict:
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


def _problem(subject: str, *, confidence: float = 1.0) -> Problem:
    return Problem(
        id="P_GEN_REVIEW",
        title="测试",
        text="测试",
        graph=SolutionGraph(
            problem_id="P_GEN_REVIEW",
            version="g0",
            stem="",
            nodes=(),
            edges=(),
        ),
        subject=subject,
        annotated=False,
        domain_confidence=confidence,
        domain_method="declared",
        generic=None,
    )


def test_a_writing_intake_carries_a_structure_review(client: TestClient) -> None:
    body = _start(client, WRITING, answer=WRITING, subject="写作")

    intaked = body["intake"]
    assert intaked is not None
    # v0.5 keeps every v0.4 field; the review is additive.
    assert intaked["version"] == "0.5"
    assert intaked["observed"]
    assert "gaps" in intaked
    assert "graph" in intaked
    assert "verifications" in intaked
    assert "clarifier" in intaked
    assert "probe" in intaked
    assert intaked["next_step"]
    assert intaked["disclaimer"]

    review = intaked["review"]
    assert review is not None
    assert review["version"] == "0.1"
    assert review["session_id"] == body["session_id"]
    assert review["problem_id"] == body["problem_id"]
    assert review["kind"] == "structure"
    assert set(review) <= REVIEW_KEYS | {"options", "tradeoff_question", "execution"}
    assert review["domain"]["verification"] == "argumentative"
    assert review["headline"]
    assert review["disclaimer"]
    # Every finding cites evidence that exists in the same review.
    evidence_ids = {item["id"] for item in review["evidence"]}
    for finding in review["findings"]:
        assert set(finding["evidence_refs"]) <= evidence_ids
    assert "score" not in review and "rank" not in review


def test_the_ui_style_answer_and_work_are_both_read(client: TestClient) -> None:
    """The form has a short answer and a separate work field.

    A writing answer alone (``不应该禁止``) has no argument structure; the review
    must read the work field too, or the card is empty for exactly the input the
    form is designed to collect.
    """

    work = (
        "我想论证的是：中学生不该被禁止带手机进校园。手机能查资料，也方便联系家长。"
        "学校禁止手机，是担心课堂被打断。"
    )
    created = _start(
        client,
        "学校是否应该禁止中学生带手机进校园？请写一段议论，说明你的立场和理由。",
        answer="不应该禁止",
        subject="写作",
        work=work,
    )

    review = created["intake"]["review"]
    assert review is not None
    assert review["kind"] == "structure"
    assert review["findings"], "the work field must contribute the review's findings"

    reloaded = client.get(f"/api/v1/sessions/{created['session_id']}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["intake"]["review"] == review


def test_a_decision_intake_carries_the_frame_without_ranking(client: TestClient) -> None:
    body = _start(client, DECISION, answer=DECISION_ATTEMPT)

    review = body["intake"]["review"]
    assert review is not None
    assert review["kind"] == "decision"
    assert len(review["options"]) >= 2
    assert any("什么都不做" in option["label"] for option in review["options"])
    assert review["tradeoff_question"]
    # The published shape has no ranking field at all.
    assert not FORBIDDEN_DECISION_KEYS & set(review)
    for option in review["options"]:
        assert set(option) == {"label", "costs", "risks", "reversible_test"}
        assert not FORBIDDEN_DECISION_KEYS & set(option)


def test_an_unknown_domain_still_starts_and_can_carry_a_review(client: TestClient) -> None:
    body = _start(client, "我最近很烦，不知道该怎么办。", answer="不知道先做哪个。")

    assert body["domain"]["name"] == "generic"
    assert body["state"] == "CLOSED"
    assert body["diagnosis"] is None
    intaked = body["intake"]
    assert intaked is not None
    # The generic mode has no graph, but the composer still returns an honest
    # ``not_checked`` + one question instead of manufacturing findings.
    review = intaked["review"]
    assert review is not None
    assert review["kind"] == "structure"
    assert review["not_checked"]
    assert review["next_step"]


def test_an_executable_intake_does_not_compose_a_review(client: TestClient) -> None:
    body = _start(client, CODE, answer="```python\nprint(1)\n```")

    intaked = body["intake"]
    assert intaked is not None
    assert intaked["version"] == "0.5"
    assert intaked["domain"]["verification"] == "executable"
    assert intaked["review"] is None
    # The old intake is unchanged by T3.
    assert intaked["checklist"]
    assert "未执行" in intaked["disclaimer"]


@pytest.mark.parametrize("subject", ["math", "physics"])
def test_formal_and_empirical_intakes_keep_review_none(subject: str) -> None:
    profile = REGISTRY.profile_for(subject)

    intaked = build_domain_intake(
        _problem(subject),
        profile,
        "我想先算一下。",
        session_id="S_REVIEW_TEST",
    )

    assert intaked.version == "0.5"
    assert intaked.review is None
    assert intaked.observed
    assert intaked.checklist


def test_a_blank_attempt_has_no_review_but_keeps_the_old_fields() -> None:
    intaked = build_domain_intake(
        _problem("decision"),
        REGISTRY.profile_for("decision"),
        "   ",
        session_id="S_REVIEW_TEST",
    )

    assert intaked.review is None
    assert intaked.observed == ()
    assert intaked.gaps == ()
    assert intaked.version == "0.5"


def test_the_same_review_is_derived_after_a_reload(client: TestClient) -> None:
    created = _start(client, DECISION, answer=DECISION_ATTEMPT)

    reloaded = client.get(f"/api/v1/sessions/{created['session_id']}")

    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["intake"]["review"] == created["intake"]["review"]


def test_a_composer_failure_is_logged_and_the_intake_still_answers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Boom:
        def compose(self, **_: object) -> None:
            raise RuntimeError("composer exploded")

    monkeypatch.setattr(intake_module, "_REVIEW_COMPOSER", _Boom())
    caplog.set_level(logging.ERROR, logger=intake_module.__name__)

    intaked = build_domain_intake(
        _problem("decision"),
        REGISTRY.profile_for("decision"),
        DECISION_ATTEMPT,
        session_id="S_REVIEW_TEST",
    )

    assert intaked.review is None
    # Existing fields are intact; nothing was invented to explain the failure.
    assert intaked.observed
    assert intaked.gaps
    assert "composer exploded" not in " ".join(intaked.gaps)
    assert "generic review composition failed" in caplog.text
    assert "S_REVIEW_TEST" in caplog.text


def test_the_review_is_not_stored_on_the_problem() -> None:
    """The review is derived on every read; the problem model has no such field."""

    problem = _problem("decision")

    assert problem.generic is None
    assert not hasattr(problem, "review")
