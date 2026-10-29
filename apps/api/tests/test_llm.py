"""T2/T4 adapters: provider client, settings switch and output validation."""

from __future__ import annotations

import json

import httpx
import pytest

from synapse.application.llm import LLMCallFailed, LLMRequest, LLMTimeout
from synapse.infrastructure.llm.client import OpenAICompatibleClient
from synapse.infrastructure.llm.schema import SchemaRejected, parse_rewrite
from synapse.infrastructure.llm.settings import LLMSettings


def _request() -> LLMRequest:
    return LLMRequest(
        purpose="probe_rewrite",
        system="sys",
        user="usr",
        schema_name="probe_rewrite",
    )


def _settings(**overrides: object) -> LLMSettings:
    values: dict[str, object] = {"mode": "on", "api_key": "sk-test"}
    values.update(overrides)
    return LLMSettings(**values)  # type: ignore[arg-type]


def test_client_sends_json_mode_at_temperature_zero() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"content": '{"question": "a=0 时导数是什么？"}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    client = OpenAICompatibleClient(_settings(), transport=httpx.MockTransport(handler))
    response = client.complete(_request(), timeout_s=1.0)

    assert response.text == '{"question": "a=0 时导数是什么？"}'
    assert response.model == "deepseek-chat"
    assert (response.prompt_tokens, response.completion_tokens) == (11, 7)
    assert seen["temperature"] == 0.0
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["max_tokens"] == 300


def test_client_maps_timeout_to_llm_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = OpenAICompatibleClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMTimeout):
        client.complete(_request(), timeout_s=0.1)


def test_client_maps_http_error_to_call_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    client = OpenAICompatibleClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMCallFailed, match="401"):
        client.complete(_request(), timeout_s=1.0)


def test_client_rejects_malformed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = OpenAICompatibleClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMCallFailed):
        client.complete(_request(), timeout_s=1.0)


@pytest.mark.parametrize(
    ("mode", "canary"),
    [("off", 0), ("shadow", 0), ("on", 0), ("on:10", 10)],
)
def test_mode_parsing(mode: str, canary: int) -> None:
    settings = LLMSettings.from_env({"SYNAPSE_LLM_MODE": mode})
    assert settings.mode == mode.split(":")[0]
    assert settings.canary_percent == canary


def test_unknown_mode_is_loud() -> None:
    with pytest.raises(ValueError, match="SYNAPSE_LLM_MODE"):
        LLMSettings.from_env({"SYNAPSE_LLM_MODE": "enable"})


def test_mode_without_key_stays_rule_based() -> None:
    assert not LLMSettings.from_env({"SYNAPSE_LLM_MODE": "on"}).llm_enabled
    assert LLMSettings.from_env(
        {"SYNAPSE_LLM_MODE": "on", "DEEPSEEK_API_KEY": "sk-x"}
    ).llm_enabled


def test_canary_is_stable_per_session() -> None:
    settings = LLMSettings(mode="on", api_key="sk", canary_percent=10)
    assert settings.use_for("S_abc") == settings.use_for("S_abc")
    hits = [sid for sid in (f"S_{i}" for i in range(500)) if settings.use_for(sid)]
    assert 20 <= len(hits) <= 80, f"canary split looks wrong: {len(hits)}/500"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json", "not_json"),
        ("[]", "not_object"),
        ('{"q": "x"}', "missing_question"),
        ('{"question": "短？"}', "too_short"),
        ('{"question": "第一问？还问第二问？"}', "question_marks"),
        ('{"question": "换行\\n的问题？"}', "multi_line"),
        ('{"question": "' + "很" * 90 + "？" + '"}', "too_long"),
    ],
)
def test_schema_rejections(text: str, reason: str) -> None:
    with pytest.raises(SchemaRejected) as caught:
        parse_rewrite(text)
    assert caught.value.reason == reason


def test_schema_accepts_one_question() -> None:
    assert parse_rewrite('{"question": "a=0 时 f\'(x) 有零点吗？"}') == "a=0 时 f'(x) 有零点吗？"