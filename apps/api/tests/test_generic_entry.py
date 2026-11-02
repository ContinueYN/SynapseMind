"""Phase 0 exit condition: four different kinds of problem can start.

The point is not that every problem gets a card. It is that the same entry
accepts a math problem, a code bug, a life decision and an unknown domain, and
that a reference-free session is honest about what it did not check. With
``SYNAPSE_LLM_MODE=off`` there is no graph generator, so the code/decision/
unknown cases must start as intake views instead of returning 422.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

MATH_SEED = "已知函数 f(x)=ln x - a x，a∈R。若 f(x)≤0 对任意 x>0 恒成立，求 a 的取值范围。"
CODE = "我的 Python 脚本报错了：IndexError: list index out of range，列表里明明有元素，应该怎么修？"
DECISION = "我应该接受北京的工作机会，还是留在上海陪家人？"
UNKNOWN = "我最近很烦，不知道该怎么办。"


def _start(client: TestClient, text: str, *, answer: str = "不知道") -> dict[str, object]:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": text},
            "attempt": {"answer": answer, "work": "", "self_report": "unsure"},
            "mode": "learning",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_math_problem_still_reaches_the_annotated_graph(client: TestClient) -> None:
    body = _start(client, MATH_SEED, answer="a≥1/e")

    assert body["state"] == "PROBE"
    assert body["prompt"] is not None
    assert body["intake"] is None
    assert body["domain"] == {
        "name": "math",
        "label": "数学",
        "verification": "formal",
        "generic": False,
        "confidence": 1.0,
    }


def test_a_code_problem_starts_as_executable_intake(client: TestClient) -> None:
    body = _start(client, CODE)

    assert body["state"] == "CLOSED"
    assert body["prompt"] is None
    assert body["diagnosis"] is None
    assert body["domain"]["name"] == "programming"
    assert body["domain"]["verification"] == "executable"
    assert body["domain"]["generic"] is False
    intake = body["intake"]
    assert intake is not None
    assert intake["domain"]["name"] == "programming"
    assert any("复现" in item for item in intake["checklist"])
    assert "未执行" in intake["disclaimer"]
    # A confident label does not ask a clarifying question.
    assert intake["clarifier"] is None
    # No answer / solution key on a learning-mode response.
    assert "answer" not in body
    assert "solution" not in body


def test_a_life_decision_starts_without_a_right_answer(client: TestClient) -> None:
    body = _start(client, DECISION, answer="不知道选哪个")

    assert body["state"] == "CLOSED"
    assert body["domain"]["name"] == "decision"
    intake = body["intake"]
    assert intake is not None
    assert "唯一正确答案" in intake["disclaimer"]
    assert any("可逆实验" in item for item in intake["checklist"])
    assert "卡点卡" not in body.get("notice", "")


def test_the_decision_intake_reads_the_students_own_words(client: TestClient) -> None:
    body = _start(
        client,
        DECISION,
        answer=("我想两年内转做后端；要么留在公司转岗，要么跳槽去小厂；但我怕收入下降。"),
    )

    intake = body["intake"]
    assert intake is not None
    assert intake["version"] == "0.5"
    # What the submission mentions, and only that.
    assert "目标" in intake["observed"]
    assert "选项" in intake["observed"]
    assert "风险" in intake["observed"]
    assert len(intake["gaps"]) <= 3
    assert not any("两个选项" in gap for gap in intake["gaps"])


def test_an_unknown_domain_starts_in_generic_mode(client: TestClient) -> None:
    body = _start(client, UNKNOWN)

    assert body["state"] == "CLOSED"
    assert body["domain"]["name"] == "generic"
    assert body["domain"]["label"] == "通用问题"
    assert body["domain"]["generic"] is True
    assert body["domain"]["confidence"] == 0.0
    intake = body["intake"]
    assert intake is not None
    # Low confidence may ask exactly one clarifying question, and never blocks.
    assert intake["clarifier"] is not None
    assert intake["clarifier"].count("？") == 1
    assert intake["checklist"]


def test_an_open_label_is_accepted_and_kept(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sessions",
        json={
            "problem": {"text": "我的乐高结构总是一推就散，该怎么加固？", "subject": "乐高结构"},
            "attempt": {"answer": "不知道"},
            "mode": "learning",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["domain"]["name"] == "乐高结构"
    assert body["domain"]["generic"] is True
    assert body["intake"]["domain"]["label"] == "乐高结构"


def test_a_generic_session_can_be_reloaded(client: TestClient) -> None:
    created = _start(client, UNKNOWN)

    response = client.get(f"/api/v1/sessions/{created['session_id']}")

    assert response.status_code == 200, response.text
    reloaded = response.json()
    assert reloaded["domain"] == created["domain"]
    assert reloaded["intake"]["checklist"] == created["intake"]["checklist"]
    assert reloaded["intake"]["clarifier"] == created["intake"]["clarifier"]
    # The gap list is derived from the stored attempt, so a reload cannot drift.
    assert reloaded["intake"]["observed"] == created["intake"]["observed"]
    assert reloaded["intake"]["gaps"] == created["intake"]["gaps"]


def test_a_generic_session_has_no_answer_to_reveal(client: TestClient) -> None:
    created = _start(client, CODE)

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/exit",
        json={"reveal": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "answer" not in body
    assert "solution" not in body
    assert "没有存储解法" in body["notice"]
    # The intake is still derived on the way out, so a reload does not lose it.
    assert body["intake"] is not None


def test_the_single_clarifier_can_be_answered_once(client: TestClient) -> None:
    created = _start(client, UNKNOWN)
    session_id = created["session_id"]
    assert created["intake"]["clarifier"] is not None

    response = client.post(
        f"/api/v1/sessions/{session_id}/intake",
        json={"answer": "我纠结要不要换城市工作：要么留下，要么跳槽，但我担心收入下降。"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # The one question is used up; the session stays closed and undiagnosed.
    assert body["state"] == "CLOSED"
    assert body["intake"]["clarifier"] is None
    assert body["diagnosis"] is None
    assert "不定位卡点" in body["notice"]
    assert body["intake"]["observed"]
    # Naming a kind of problem relabels the display profile, not the plugin key.
    assert body["subject"] == "generic"
    assert body["domain"]["name"] == "decision"
    assert body["domain"]["label"] == "生活决策"
    assert body["domain"]["confidence"] == 0.8
    assert body["intake"]["domain"] == body["domain"]
    assert any("可逆实验" in item for item in body["intake"]["checklist"])
    assert "改按「生活决策」处理" in body["notice"]

    reloaded = client.get(f"/api/v1/sessions/{session_id}").json()
    assert reloaded["domain"] == body["domain"]
    assert reloaded["intake"]["clarifier"] is None
    assert reloaded["intake"]["domain"] == body["intake"]["domain"]
    assert reloaded["intake"]["checklist"] == body["intake"]["checklist"]
    assert reloaded["intake"]["observed"] == body["intake"]["observed"]
    assert reloaded["intake"]["gaps"] == body["intake"]["gaps"]

    # A second clarification is not appended; it returns the current view.
    second = client.post(
        f"/api/v1/sessions/{session_id}/intake",
        json={"answer": "再补充一句。"},
    )
    assert second.status_code == 200, second.text
    assert "只接受一次补充" in second.json()["notice"]
    assert second.json()["intake"]["gaps"] == body["intake"]["gaps"]


def test_a_clarifier_without_a_domain_cue_keeps_the_generic_profile(
    client: TestClient,
) -> None:
    created = _start(client, UNKNOWN)
    session_id = created["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/intake",
        json={"answer": "我卡在第二步：不知道先做哪个。"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # A structural sentence must not be forced into a domain.
    assert body["domain"]["name"] == "generic"
    assert body["intake"]["domain"]["name"] == "generic"
    assert body["intake"]["clarifier"] is None
    assert body["diagnosis"] is None


def test_a_confident_intake_rejects_a_clarifier(client: TestClient) -> None:
    created = _start(client, CODE)
    assert created["intake"]["clarifier"] is None

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/intake",
        json={"answer": "补充一句。"},
    )

    assert response.status_code == 409, response.text


def test_a_blank_or_oversized_clarifier_is_rejected(client: TestClient) -> None:
    created = _start(client, UNKNOWN)
    session_id = created["session_id"]

    blank = client.post(
        f"/api/v1/sessions/{session_id}/intake",
        json={"answer": "   "},
    )
    assert blank.status_code == 422, blank.text

    oversized = client.post(
        f"/api/v1/sessions/{session_id}/intake",
        json={"answer": "补" * 501},
    )
    assert oversized.status_code == 422, oversized.text


def test_structural_follow_ups_are_one_at_a_time_and_stop_after_three(
    client: TestClient,
) -> None:
    created = _start(client, DECISION)
    session_id = created["session_id"]
    intake = created["intake"]
    assert intake["clarifier"] is None
    assert intake["probe"] is not None
    assert intake["probe"]["kind"] == "goal"
    assert intake["probe"]["answered"] == 0
    assert intake["probe"]["limit"] == 3

    first = client.post(
        f"/api/v1/sessions/{session_id}/intake/probe",
        json={"answer": "目标：我想两年内转做后端。"},
    )
    assert first.status_code == 200, first.text
    after_first = first.json()
    assert after_first["state"] == "CLOSED"
    assert after_first["diagnosis"] is None
    assert after_first["intake"]["probe"]["answered"] == 1
    assert after_first["intake"]["probe"]["kind"] != "goal"
    assert "目标" in after_first["intake"]["observed"]

    for answer in (
        "选项：要么留在公司转岗，要么跳槽去小厂。",
        "约束：收入不能下降。",
    ):
        response = client.post(
            f"/api/v1/sessions/{session_id}/intake/probe",
            json={"answer": answer},
        )
        assert response.status_code == 200, response.text

    # The budget is three answers; the third response no longer offers a question.
    last = response.json()
    assert last["intake"]["probe"] is None
    assert last["intake"]["clarifier"] is None

    fourth = client.post(
        f"/api/v1/sessions/{session_id}/intake/probe",
        json={"answer": "再补一句。"},
    )
    assert fourth.status_code == 409, fourth.text

    reloaded = client.get(f"/api/v1/sessions/{session_id}").json()
    assert reloaded["intake"]["probe"] is None
    assert reloaded["intake"]["observed"] == last["intake"]["observed"]


def test_an_open_clarifier_blocks_a_structural_follow_up(client: TestClient) -> None:
    created = _start(client, UNKNOWN)
    assert created["intake"]["clarifier"] is not None
    assert created["intake"]["probe"] is None

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/intake/probe",
        json={"answer": "目标：先把问题说清楚。"},
    )

    assert response.status_code == 409, response.text


def test_a_blank_or_oversized_structural_answer_is_rejected(client: TestClient) -> None:
    created = _start(client, DECISION)
    session_id = created["session_id"]

    blank = client.post(
        f"/api/v1/sessions/{session_id}/intake/probe",
        json={"answer": "   "},
    )
    assert blank.status_code == 422, blank.text

    oversized = client.post(
        f"/api/v1/sessions/{session_id}/intake/probe",
        json={"answer": "补" * 501},
    )
    assert oversized.status_code == 422, oversized.text


def test_a_generic_session_does_not_accept_probe_answers(client: TestClient) -> None:
    created = _start(client, DECISION)

    response = client.post(
        f"/api/v1/sessions/{created['session_id']}/turns",
        json={"answer": "选北京", "option_id": "A"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diagnosis"] is None
    assert "已结束" in body["notice"]
    assert body["intake"] is not None
