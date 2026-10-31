from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from synapse.api.deps import build_container
from synapse.api.main import create_app
from synapse.application.knowledge import KnowledgeService, KnowledgeUnavailable
from synapse.infrastructure.features import FeatureFlags
from synapse.infrastructure.knowledge.corpus import load_corpus, parse_corpus
from synapse.infrastructure.knowledge.embedding import HashingEmbedder
from synapse.infrastructure.knowledge.index import InMemoryKnowledgeIndex

SPEC_PATH = Path(__file__).resolve().parents[3] / "specs" / "knowledge-search.schema.json"


def _index() -> InMemoryKnowledgeIndex:
    return InMemoryKnowledgeIndex(
        load_corpus(),
        HashingEmbedder(),
        min_score=0.0,
    )


def _client(service: KnowledgeService) -> TestClient:
    return TestClient(
        create_app(
            build_container(
                features=FeatureFlags(rag=False),
                knowledge=service,
            )
        )
    )


def test_corpus_is_sourced_and_has_no_duplicate_ids() -> None:
    cards = load_corpus()

    assert len(cards) >= 10
    assert len({card.id for card in cards}) == len(cards)
    assert {card.subject for card in cards} == {"math", "physics"}
    for card in cards:
        assert card.source.url.startswith("https://")
        assert card.source.license
        assert card.body
        assert card.tags


def test_corpus_rejects_duplicate_ids() -> None:
    line = (
        '{"id":"K_X","subject":"math","title":"t","body":"b","tags":["a"],'
        '"source":{"title":"s","url":"https://example.com","license":"CC"}}'
    )

    with pytest.raises(ValueError, match="duplicate card id"):
        parse_corpus(f"{line}\n{line}", origin="test")


def test_corpus_rejects_non_https_source() -> None:
    line = (
        '{"id":"K_X","subject":"math","title":"t","body":"b","tags":["a"],'
        '"source":{"title":"s","url":"http://example.com","license":"CC"}}'
    )

    with pytest.raises(ValueError, match="https URL"):
        parse_corpus(line, origin="test")


def test_index_ranks_the_closest_concept_first() -> None:
    hits = _index().search("恒成立 参数 最值", limit=3)

    assert hits
    assert hits[0].card.id == "K_MATH_MAX_MIN"
    assert hits[0].score > 0


def test_index_filters_by_subject() -> None:
    hits = _index().search("单位 量纲", subject="physics", limit=3)

    assert hits[0].card.id == "K_PHYS_UNITS"
    assert all(hit.card.subject == "physics" for hit in hits)


def test_disabled_service_is_explicitly_empty() -> None:
    result = KnowledgeService(None).search("恒成立")

    assert result.enabled is False
    assert result.hits == ()


def test_api_hides_the_panel_when_rag_is_off() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/knowledge/search", params={"q": "恒成立"})

    assert response.status_code == 200
    assert response.json() == {
        "version": "0.1",
        "enabled": False,
        "query": "恒成立",
        "hits": [],
    }


def test_api_returns_cited_hits_and_matches_the_spec() -> None:
    client = _client(KnowledgeService(_index()))

    response = client.get(
        "/api/v1/knowledge/search",
        params={"q": "恒成立 参数 最值", "subject": "math", "limit": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["version"] == "0.1"
    assert len(payload["hits"]) == 1
    hit = payload["hits"][0]
    assert hit["card_id"] == "K_MATH_MAX_MIN"
    assert hit["source"]["url"].startswith("https://")
    assert 0 <= hit["score"] <= 1

    schema = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


def test_api_rejects_a_too_short_query_and_too_many_hits() -> None:
    client = _client(KnowledgeService(_index()))

    assert client.get("/api/v1/knowledge/search", params={"q": "x"}).status_code == 422
    assert (
        client.get(
            "/api/v1/knowledge/search",
            params={"q": "恒成立", "limit": 6},
        ).status_code
        == 422
    )


def test_api_maps_an_unavailable_model_to_503() -> None:
    class _Unavailable:
        def search(self, query: str, *, subject: str | None = None, limit: int = 3):
            raise KnowledgeUnavailable("RAG 已开启，但没有安装 fastembed")

    client = _client(KnowledgeService(_Unavailable()))

    response = client.get("/api/v1/knowledge/search", params={"q": "恒成立"})

    assert response.status_code == 503
    assert "fastembed" in response.json()["detail"]
