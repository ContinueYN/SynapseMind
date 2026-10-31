"""Generation failures are words, not a stack trace or a guessed graph."""

from __future__ import annotations

import pytest

from synapse.application.errors import ProblemNotSupported
from synapse.application.graph import GraphBuildFailed
from synapse.application.problem_resolver import ProblemResolver
from synapse.application.subject import SubjectRegistry
from synapse.domain.problem.models import ProblemDraft, SolutionGraph
from synapse.infrastructure.in_memory import InMemoryProblemRepository

TEXT = "已知函数 f(x)=x^2-a x+1，求 a 的取值范围。"


class _FailingPlugin:
    subject = "math"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def identify(self, text: str) -> None:
        del text
        return None

    def build_graph(self, draft: ProblemDraft) -> SolutionGraph:
        del draft
        raise GraphBuildFailed(self.reason, detail="raw provider detail")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reason", "needle"),
    [
        ("timeout", "建图超时"),
        ("transport", "建图服务暂时不可达"),
        ("bad_json", "格式不合法"),
        ("schema_invalid", "结构约束"),
        ("degenerate", "拆不出足够可验证的步骤"),
        ("invalid_draft", "题目标识不合法"),
    ],
)
def test_each_generation_failure_has_a_distinct_explanation(reason: str, needle: str) -> None:
    repo = InMemoryProblemRepository()
    resolver = ProblemResolver(
        repo,
        SubjectRegistry((_FailingPlugin(reason),)),  # type: ignore[arg-type]
        store=repo,
    )

    with pytest.raises(ProblemNotSupported) as info:
        resolver.resolve(TEXT, "math")

    message = str(info.value)
    assert needle in message
    assert "raw provider detail" not in message
