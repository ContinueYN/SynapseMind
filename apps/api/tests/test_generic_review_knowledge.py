"""T5: a generic review may cite knowledge cards, but only returned ones.

The composer may attach a card as **top-level** evidence; it may not turn a card
into a finding, invent a ref when retrieval is off/empty/failing, or send the
student's attempt (or a finding summary) to the embedder. These tests pin all
four behaviours, plus the intake/service wiring that makes the lookup reachable.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.diagnosis.domains import DomainRegistry, IntakeFramework, VerificationMode
from synapse.application.diagnosis.generic_check import structure_gaps
from synapse.application.diagnosis.generic_slots import CueSlotExtractor
from synapse.application.diagnosis.intake import build_domain_intake
from synapse.application.knowledge.service import KnowledgeService
from synapse.application.review.generic import GenericReviewComposer
from synapse.domain.knowledge.models import KnowledgeCard, KnowledgeHit, KnowledgeSource
from synapse.domain.problem.generic_review import (
    EvidenceSource,
    GenericEvidence,
    GenericReview,
)
from synapse.domain.problem.models import Problem, SolutionGraph
from synapse.infrastructure.features import FeatureFlags

REGISTRY = DomainRegistry()
WRITING_ATTEMPT = "我想论证学校应该禁止学生带手机。很多同学都这样。"
SENTINEL = "学校应该禁止学生带手机"
DECISION_ATTEMPT = "我在纠结接受北京的工作，还是留在上海陪家人。我怕异地。"
GENERIC_ATTEMPT = "我最近很烦，不知道该怎么办。"


def _card(card_id: str, title: str, *, subject: str = "writing") -> KnowledgeCard:
    return KnowledgeCard(
        id=card_id,
        kind="pattern",
        subject=subject,
        verifications=("argumentative",),
        title=title,
        body="测试卡片正文；这里只关心 id、标题与来源字段。",
        tags=("论证",),
        source=KnowledgeSource(
            title="测试来源",
            url="https://example.com/writing-guide",
            license="CC BY 4.0",
        ),
    )


class _FakeRetriever:
    """Records the exact query; returns every hit so the composer's cap is tested."""

    def __init__(
        self,
        hits: tuple[KnowledgeHit, ...] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self._hits = hits
        self._error = error
        self.queries: list[str] = []
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        *,
        subject: str | None = None,
        verification: str | None = None,
        kind: str | None = None,
        limit: int = 3,
    ) -> tuple[KnowledgeHit, ...]:
        self.queries.append(query)
        self.calls.append(
            {
                "subject": subject,
                "verification": verification,
                "kind": kind,
                "limit": limit,
            }
        )
        if self._error is not None:
            raise self._error
        return self._hits


def _hits(*cards: KnowledgeCard) -> tuple[KnowledgeHit, ...]:
    return tuple(KnowledgeHit(card=card, score=0.9) for card in cards)


def _compose(
    attempt: str,
    *,
    knowledge: KnowledgeService | None,
    domain_name: str = "writing",
    domain_label: str = "写作",
    framework: IntakeFramework = IntakeFramework.ARGUMENTATIVE,
    problem_id: str = "P_T5_REVIEW_001",
    session_id: str = "S_T5_REVIEW_001",
) -> GenericReview:
    graph = CueSlotExtractor().extract(problem_id, attempt)
    return GenericReviewComposer(knowledge=knowledge).compose(
        session_id=session_id,
        problem_id=problem_id,
        domain_name=domain_name,
        domain_label=domain_label,
        verification=VerificationMode.ARGUMENTATIVE,
        graph=graph,
        gaps=structure_gaps(framework, graph),
        initial_answer=attempt,
        framework=framework,
    )


def _knowledge_items(review: GenericReview) -> list[GenericEvidence]:
    return [item for item in review.evidence if item.source is EvidenceSource.KNOWLEDGE]


def test_a_retrieved_card_becomes_traceable_top_level_evidence() -> None:
    cards = (
        _card("K_WRITING_CLAIM_EVIDENCE", "主张、理由、证据分开写"),
        _card("K_WRITING_COUNTERARGUMENT", "主动写出最强反方"),
    )
    review = _compose(WRITING_ATTEMPT, knowledge=KnowledgeService(_FakeRetriever(_hits(*cards))))

    sources = _knowledge_items(review)
    assert [item.ref for item in sources] == [
        "K_WRITING_CLAIM_EVIDENCE",
        "K_WRITING_COUNTERARGUMENT",
    ]
    assert [item.excerpt for item in sources] == ["主张、理由、证据分开写", "主动写出最强反方"]

    # The cards are top-level sources, not findings: no finding cites them, and
    # every finding still cites evidence that exists in this same review.
    cited = {ref for finding in review.findings for ref in finding.evidence_refs}
    assert {item.id for item in sources}.isdisjoint(cited)
    evidence_ids = {item.id for item in review.evidence}
    for finding in review.findings:
        assert finding.evidence_refs
        assert set(finding.evidence_refs) <= evidence_ids
    assert len({item.id for item in review.evidence}) == len(review.evidence)


def test_the_query_never_contains_the_attempt_or_a_finding_summary() -> None:
    retriever = _FakeRetriever(_hits(_card("K_WRITING_CLAIM_EVIDENCE", "主张与证据分开写")))
    review = _compose(WRITING_ATTEMPT, knowledge=KnowledgeService(retriever))

    assert retriever.queries == ["写作 论证 证据 推理 反方"]
    query = retriever.queries[0]
    assert SENTINEL not in query
    for finding in review.findings:
        assert finding.summary not in query
    # Retrieval is filtered to argumentative cards and capped at two.
    assert retriever.calls == [
        {
            "subject": None,
            "verification": "argumentative",
            "kind": None,
            "limit": 2,
        }
    ]


def test_at_most_two_cards_are_added_even_if_the_retriever_returns_three() -> None:
    retriever = _FakeRetriever(
        _hits(
            _card("K_WRITING_A", "卡片 A"),
            _card("K_WRITING_B", "卡片 B"),
            _card("K_WRITING_C", "卡片 C"),
        )
    )

    review = _compose(WRITING_ATTEMPT, knowledge=KnowledgeService(retriever))

    assert [item.ref for item in _knowledge_items(review)] == ["K_WRITING_A", "K_WRITING_B"]


def test_rag_off_keeps_the_review_and_invents_no_source() -> None:
    review = _compose(WRITING_ATTEMPT, knowledge=KnowledgeService(None))

    assert review.findings
    assert review.evidence
    assert _knowledge_items(review) == []
    assert review.not_checked


def test_no_composer_service_or_a_blank_attempt_skips_retrieval() -> None:
    retriever = _FakeRetriever(_hits(_card("K_WRITING_CLAIM_EVIDENCE", "主张与证据分开写")))
    service = KnowledgeService(retriever)

    without_service = _compose(WRITING_ATTEMPT, knowledge=None)
    blank = _compose("   ", knowledge=service)

    assert _knowledge_items(without_service) == []
    assert _knowledge_items(blank) == []
    assert blank.evidence == ()
    # Neither path had anything to ask about, so retrieval was never called.
    assert retriever.queries == []


def test_no_hits_keeps_the_review_without_fabricating_a_citation() -> None:
    retriever = _FakeRetriever()
    review = _compose(WRITING_ATTEMPT, knowledge=KnowledgeService(retriever))

    assert retriever.queries == ["写作 论证 证据 推理 反方"]
    assert review.findings
    assert _knowledge_items(review) == []
    assert not any("https://" in item for item in review.not_checked)


def test_a_retrieval_failure_is_swallowed_and_the_review_still_serves() -> None:
    retriever = _FakeRetriever(error=RuntimeError("model unavailable"))
    review = _compose(WRITING_ATTEMPT, knowledge=KnowledgeService(retriever))

    assert retriever.queries == ["写作 论证 证据 推理 反方"]
    assert review.findings
    assert _knowledge_items(review) == []


def test_a_decision_review_can_show_a_card_without_ranking() -> None:
    retriever = _FakeRetriever(
        _hits(_card("K_DECISION_REVERSIBLE", "决策前先写选项、代价和可逆性"))
    )
    review = _compose(
        DECISION_ATTEMPT,
        knowledge=KnowledgeService(retriever),
        domain_name="decision",
        domain_label="生活决策",
        framework=IntakeFramework.DECISION,
    )

    assert review.kind.value == "decision"
    assert [item.ref for item in _knowledge_items(review)] == ["K_DECISION_REVERSIBLE"]
    assert retriever.queries == ["生活决策 决策 目标 约束 选项 代价 风险 可逆实验"]
    payload = review.to_dict()
    assert not {"score", "rank", "recommended"} & set(payload)


def test_an_open_domain_gets_no_query_instead_of_an_off_domain_card() -> None:
    retriever = _FakeRetriever(_hits(_card("K_WRITING_CLAIM_EVIDENCE", "主张与证据分开写")))

    review = _compose(
        GENERIC_ATTEMPT,
        knowledge=KnowledgeService(retriever),
        domain_name="photography",
        domain_label="摄影",
        framework=IntakeFramework.GENERIC,
    )

    assert _knowledge_items(review) == []
    assert retriever.queries == []


def _problem(subject: str) -> Problem:
    return Problem(
        id="P_T5_INTAKE_001",
        title="测试",
        text="测试",
        graph=SolutionGraph(
            problem_id="P_T5_INTAKE_001",
            version="g0",
            stem="",
            nodes=(),
            edges=(),
        ),
        subject=subject,
        annotated=False,
        domain_confidence=1.0,
        domain_method="declared",
        generic=None,
    )


def test_build_domain_intake_forwards_the_knowledge_service() -> None:
    retriever = _FakeRetriever(_hits(_card("K_WRITING_CLAIM_EVIDENCE", "主张、理由、证据分开写")))
    intaked = build_domain_intake(
        _problem("writing"),
        REGISTRY.profile_for("writing"),
        WRITING_ATTEMPT,
        session_id="S_T5_INTAKE_001",
        knowledge=KnowledgeService(retriever),
    )

    assert intaked.review is not None
    assert [item.ref for item in _knowledge_items(intaked.review)] == ["K_WRITING_CLAIM_EVIDENCE"]
    assert SENTINEL not in retriever.queries[0]


def test_the_session_service_passes_its_knowledge_service_to_the_intake() -> None:
    retriever = _FakeRetriever(
        _hits(
            _card("K_WRITING_CLAIM_EVIDENCE", "主张、理由、证据分开写"),
            _card("K_WRITING_COUNTERARGUMENT", "主动写出最强反方"),
        )
    )
    client = TestClient(
        create_app(
            build_container(
                features=FeatureFlags(rag=False),
                knowledge=KnowledgeService(retriever),
            )
        )
    )

    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": "我想论证远程办公更好", "subject": "写作"},
            "attempt": {"answer": WRITING_ATTEMPT, "work": "", "self_report": "unsure"},
            "mode": "learning",
        },
    )

    assert response.status_code == 201, response.text
    review = response.json()["intake"]["review"]
    assert review is not None
    knowledge = [item for item in review["evidence"] if item["source"] == "knowledge"]
    assert [item["ref"] for item in knowledge] == [
        "K_WRITING_CLAIM_EVIDENCE",
        "K_WRITING_COUNTERARGUMENT",
    ]
    assert retriever.queries == ["写作 论证 证据 推理 反方"]
    assert SENTINEL not in retriever.queries[0]
    # The published shape still has no score/rank, even with cards attached.
    assert "score" not in review and "rank" not in review
