"""Session service tests use a fresh app per test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from synapse.api.main import create_app


@pytest.fixture(autouse=True)
def _rule_mode_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI must never depend on a model key or on the developer's shell."""
    for name in (
        "SYNAPSE_LLM_MODE",
        "SYNAPSE_LLM_API_KEY",
        "DEEPSEEK_API_KEY",
        # The equality-chain switch changes card text; a developer's shell must
        # not flip the golden baseline under pytest.
        "SYNAPSE_EQUALITY_CHECK",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def sample_payload() -> dict[str, object]:
    return {
        "problem": {
            "text": (
                "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"
            )
        },
        "attempt": {
            "answer": "a≥1/e",
            "work": (
                "定义域 x>0。f'(x)=1/x-a，令 f'(x)=0 得 x=1/a。"
                "a>0 时，最大值为 f(1/a)=-ln a-1≤0，所以 a≥1/e。"
            ),
            "self_report": "wrong",
        },
        "mode": "learning",
    }
