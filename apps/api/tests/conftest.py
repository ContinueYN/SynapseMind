"""Session service tests use a fresh app per test."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def pytest_configure(config: pytest.Config) -> None:
    """Keep the module-level app out of a developer's shell state DB.

    ``synapse.api.main`` exposes ``app = create_app()`` for uvicorn. Importing
    any test module would otherwise construct SQLite repositories from the
    shell's environment before the per-test fixture gets a chance to isolate
    them.
    """
    del config
    os.environ.pop("SYNAPSE_SESSION_DB", None)
    os.environ["SYNAPSE_REVIEW_DB"] = str(
        Path(tempfile.gettempdir()) / f"synapse-review-boot-{os.getpid()}.sqlite3"
    )


@pytest.fixture(autouse=True)
def _rule_mode_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CI must never depend on a model key or on the developer's shell."""
    for name in (
        "SYNAPSE_LLM_MODE",
        "SYNAPSE_LLM_API_KEY",
        "DEEPSEEK_API_KEY",
        # The equality-chain switch changes card text; a developer's shell must
        # not flip the golden baseline under pytest.
        "SYNAPSE_EQUALITY_CHECK",
        # Persistence is opt-in; a developer shell with this set must not make
        # every test share one SQLite file.
        "SYNAPSE_SESSION_DB",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNAPSE_REVIEW_DB", str(tmp_path / "review.sqlite3"))


@pytest.fixture()
def client() -> TestClient:
    from synapse.api.main import create_app

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
