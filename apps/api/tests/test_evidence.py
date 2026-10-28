from __future__ import annotations

from synapse.domain.evidence.models import Evidence, EvidenceChain


def test_chain_deduplicates_and_keeps_order() -> None:
    chain = EvidenceChain()
    first = Evidence(id="a:1", source="alignment", claim="没有检查边界", supports=("H_L2",))
    chain.add(first)
    chain.add(first)
    chain.add(Evidence(id="p:1", source="probe", claim="第 1 轮支持参数分类", supports=("H_L2",)))
    assert [item.id for item in chain.items] == ["a:1", "p:1"]
    assert chain.claims(limit=1) == ("没有检查边界",)


def test_chain_can_filter_by_hypothesis() -> None:
    chain = EvidenceChain()
    chain.add(Evidence(id="a:1", source="alignment", claim="边界证据", supports=("H_L2",)))
    chain.add(Evidence(id="a:2", source="alignment", claim="计算证据", supports=("H_L4",)))
    assert [item.id for item in chain.for_hypothesis("H_L2")] == ["a:1"]


def test_chain_latest_probe_evidence() -> None:
    chain = EvidenceChain()
    chain.add(Evidence(id="a:1", source="alignment", claim="对齐证据"))
    chain.add(Evidence(id="p:1", source="probe", claim="第一轮探针"))
    chain.add(Evidence(id="p:2", source="probe", claim="第二轮探针"))
    assert chain.latest("probe") == ("第二轮探针",)
    assert chain.latest("probe", limit=2) == ("第一轮探针", "第二轮探针")
