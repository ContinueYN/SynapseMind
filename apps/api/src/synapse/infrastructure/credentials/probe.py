"""One OpenAI-compatible probe for the "test connection" button.

The request is deliberately tiny (``max_tokens: 1``, one short user message) so a
test costs a fraction of a cent and cannot be mistaken for a real generation. The
response body is never echoed: only the status code, the model name and a fixed
sentence reach the browser. That keeps a provider error from copying request
headers or the key back into the settings page.

Redirects are not followed. The SSRF guard vetted the URL that was saved, and
following a redirect would let the provider point the server at a new host.
"""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

import httpx

from synapse.application.credentials import CredentialTestResult, SecretCredential

TEST_TIMEOUT_S = 8.0
TEST_MAX_TOKENS = 1
TEST_PROMPT = "ping"


class HttpxModelTester:
    """Call ``POST {base_url}/chat/completions`` once, with a short budget."""

    def __init__(
        self,
        *,
        timeout_s: float = TEST_TIMEOUT_S,
        transport_factory: Callable[[], httpx.BaseTransport | None] | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._transport_factory = transport_factory

    def probe(self, credential: SecretCredential) -> CredentialTestResult:
        transport = self._transport_factory() if self._transport_factory is not None else None
        started = perf_counter()
        try:
            with httpx.Client(
                base_url=credential.base_url.rstrip("/"),
                timeout=self._timeout_s,
                transport=transport,
                follow_redirects=False,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {credential.api_key}",
                },
            ) as client:
                response = client.post(
                    "/chat/completions",
                    json={
                        "model": credential.model,
                        "messages": [{"role": "user", "content": TEST_PROMPT}],
                        "temperature": 0.0,
                        "max_tokens": TEST_MAX_TOKENS,
                    },
                )
        except httpx.TimeoutException:
            return _result(
                credential,
                started,
                ok=False,
                message=f"连接服务商超时（{self._timeout_s:g}s）；请检查 base_url 或网络。",
            )
        except httpx.HTTPError:
            return _result(
                credential,
                started,
                ok=False,
                message="无法连接到服务商；请检查 base_url 与网络。",
            )

        if response.status_code in {401, 403}:
            return _result(
                credential,
                started,
                ok=False,
                message="服务商拒绝了这组凭据（HTTP 401/403）；请检查 api_key。",
            )
        if response.status_code == 429:
            return _result(
                credential,
                started,
                ok=False,
                message="服务商限流（HTTP 429）；凭据可能有效，请稍后再试。",
            )
        if response.status_code != 200:
            return _result(
                credential,
                started,
                ok=False,
                message=f"服务商返回 HTTP {response.status_code}；请检查 base_url 和 model。",
            )
        body = _json_object(response)
        model = credential.model
        if body is not None:
            reported = body.get("model")
            if isinstance(reported, str) and reported.strip():
                model = reported.strip()
        return _result(
            credential,
            started,
            ok=True,
            message=f"连接成功，模型 {model} 已响应。",
            model=model,
        )


def _json_object(response: httpx.Response) -> dict[str, object] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    return {str(key): value for key, value in body.items()}


def _result(
    credential: SecretCredential,
    started: float,
    *,
    ok: bool,
    message: str,
    model: str | None = None,
) -> CredentialTestResult:
    return CredentialTestResult(
        ok=ok,
        latency_ms=max(0, int((perf_counter() - started) * 1000)),
        model=model if model is not None else credential.model,
        message=message,
    )
