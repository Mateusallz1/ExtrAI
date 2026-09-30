from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import openai
import pytest
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

from doc_extractor_pydantic import extractor as extractor_module
from doc_extractor_pydantic.config import Settings
from doc_extractor_pydantic.provider_usage import ProviderUsage


def run_async(coroutine):
    # Playwright's synchronous session may keep an event loop running in this
    # pytest thread. The provider tests own a separate event loop and HTTP mock.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result(timeout=20)


@pytest.mark.parametrize(
    "prefix,model_class,path",
    [
        ("openai", OpenAIChatModel, "/v1/chat/completions"),
        ("openai-responses", OpenAIResponsesModel, "/v1/responses"),
    ],
)
def test_openai_http_retries_share_the_application_budget(
    monkeypatch, prefix: str, model_class: type, path: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    real_sdk = openai.AsyncOpenAI
    clients = []
    paths = []

    async def failing_transport(request):
        paths.append(request.url.path)
        return httpx.Response(
            503,
            json={"error": {"message": "synthetic unavailable", "type": "server_error"}},
        )

    def local_sdk(**kwargs):
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(failing_transport))
        sdk = real_sdk(http_client=http_client, **kwargs)
        clients.append(sdk)
        return sdk

    monkeypatch.setattr(openai, "AsyncOpenAI", local_sdk)

    async def exercise():
        extractor = extractor_module.DocumentExtractor(Settings(model=f"{prefix}:synthetic"))
        agent = extractor._build_agent()
        assert isinstance(agent.model, model_class)
        usage = ProviderUsage()
        try:
            with pytest.raises(extractor_module.ProviderUnavailableError):
                await extractor._run_model_with_backoff(agent, ["synthetic"], 5, usage)
            assert clients[0].max_retries == 0
            assert clients[0].api_key == "synthetic-key"
            assert str(clients[0].base_url) == "https://synthetic.invalid/v1/"
            assert paths == [path] * 3
            assert usage.to_api() == {"requests": 3, "inputTokens": 0, "outputTokens": 0}
        finally:
            for sdk in clients:
                await sdk.close()

    run_async(exercise())


def test_openai_success_after_transient_errors_reports_every_http_attempt(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    real_sdk = openai.AsyncOpenAI
    clients = []
    attempts = []

    async def recovering_transport(request):
        attempts.append(request.url.path)
        if len(attempts) < 3:
            return httpx.Response(
                503,
                json={"error": {"message": "synthetic unavailable", "type": "server_error"}},
            )
        body = json.loads(request.content)
        message = {"role": "assistant", "content": '{"kind":"unknown"}'}
        if body.get("tools"):
            message = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-synthetic",
                        "type": "function",
                        "function": {
                            "name": body["tools"][0]["function"]["name"],
                            "arguments": '{"kind":"unknown"}',
                        },
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )

    def local_sdk(**kwargs):
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(recovering_transport))
        sdk = real_sdk(http_client=http_client, **kwargs)
        clients.append(sdk)
        return sdk

    monkeypatch.setattr(openai, "AsyncOpenAI", local_sdk)

    async def exercise():
        extractor = extractor_module.DocumentExtractor(Settings(model="openai:synthetic"))
        usage = ProviderUsage()
        try:
            result = await extractor._run_model_with_backoff(
                extractor._build_agent(), ["synthetic"], 5, usage
            )
            assert result.output.kind == "unknown"
            assert attempts == ["/v1/chat/completions"] * 3
            assert usage.to_api() == {"requests": 3, "inputTokens": 100, "outputTokens": 10}
        finally:
            for sdk in clients:
                await sdk.close()

    run_async(exercise())
