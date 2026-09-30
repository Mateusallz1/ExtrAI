from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

import doc_extractor_pydantic.extractor as extractor_module
import doc_extractor_pydantic.main as main_module
from doc_extractor_pydantic.config import Settings
from doc_extractor_pydantic.extractor import DocumentExtractor, ProviderUnavailableError
from doc_extractor_pydantic.models import DocumentExtraction


def run_analysis(coroutine):
    """Use a separate loop from the session-scoped synchronous Playwright browser."""

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result(timeout=30)


def synthetic_png() -> bytes:
    stream = BytesIO()
    with Image.new("RGB", (10, 10), (10, 120, 200)) as image:
        image.save(stream, format="PNG")
    return stream.getvalue()


def response(info, *, invalid: bool = False) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(
            info.output_tools[0].name,
            {"kind": "invalid" if invalid else "rg", "fields": {}},
        )],
        usage=RequestUsage(input_tokens=100, output_tokens=10),
    )


def test_internal_and_external_retries_share_one_model_budget(monkeypatch) -> None:
    calls = []

    async def mixed_failures(messages, info):
        calls.append(1)
        if len(calls) % 3 == 0:
            raise ModelHTTPError(503, "synthetic", {})
        return response(info, invalid=True)

    agent = Agent(FunctionModel(mixed_failures), output_type=DocumentExtraction, retries=2)
    extractor = DocumentExtractor(Settings(model="test:model"), agent=agent)
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    with pytest.raises(ProviderUnavailableError):
        run_analysis(extractor.extract("synthetic.png", synthetic_png()))
    assert len(calls) == 3


def test_usage_includes_invalid_responses_failures_and_fallback(monkeypatch) -> None:
    primary_calls = []
    fallback_calls = []

    async def primary(messages, info):
        primary_calls.append(1)
        if len(primary_calls) == 3:
            raise ModelHTTPError(503, "synthetic", {})
        return response(info, invalid=True)

    async def fallback(messages, info):
        fallback_calls.append(1)
        return response(info)

    extractor = DocumentExtractor(
        Settings(model="test:primary", fallback_models=("test:fallback",)),
        agent=Agent(FunctionModel(primary), output_type=DocumentExtraction, retries=2),
        fallback_agents=[Agent(FunctionModel(fallback), output_type=DocumentExtraction, retries=2)],
    )
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    result = run_analysis(extractor.extract("synthetic.png", synthetic_png()))
    assert len(primary_calls) == 3
    assert len(fallback_calls) == 1
    assert result["modelUsed"] == "test:fallback"
    assert result["usage"] == {"requests": 4, "inputTokens": 300, "outputTokens": 30}


def test_transient_retry_accumulates_usage_without_resetting_budget(monkeypatch) -> None:
    calls = []

    async def flaky(messages, info):
        calls.append(1)
        if len(calls) == 1:
            return response(info, invalid=True)
        if len(calls) == 2:
            raise ModelHTTPError(503, "synthetic", {})
        return response(info)

    extractor = DocumentExtractor(
        Settings(model="test:model"),
        agent=Agent(FunctionModel(flaky), output_type=DocumentExtraction, retries=2),
    )
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    result = run_analysis(extractor.extract("synthetic.png", synthetic_png()))
    assert len(calls) == 3
    assert result["usage"] == {"requests": 3, "inputTokens": 200, "outputTokens": 20}


def test_unused_fallback_is_not_built(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    built = []

    async def successful(messages, info):
        return response(info)

    agent = Agent(FunctionModel(successful), output_type=DocumentExtraction)
    extractor = DocumentExtractor(Settings(
        fallback_models=("google:invalid-reserve",),
    ))

    def build(model):
        built.append(model)
        if model != extractor.settings.model:
            raise ValueError("synthetic invalid configuration")
        return agent

    monkeypatch.setattr(extractor, "_get_agent", build)
    result = run_analysis(extractor.extract("synthetic.png", synthetic_png()))
    assert result["kind"] == "rg"
    assert built == [extractor.settings.model]


def test_unsupported_or_duplicate_reserves_are_not_configured(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    settings = Settings(fallback_models=(
        "unsupported:typo", "google:", "google:reserve", "google:reserve",
    ))
    assert settings.configured_fallback_models() == ("google:reserve",)
    assert not settings.is_provider_configured("unsupported:typo")


def test_invalid_reserve_preserves_primary_timeout_status(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.setattr(extractor_module, "MODEL_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(extractor_module, "EXTRACTION_TIMEOUT_SECONDS", 5)

    async def slow(messages, info):
        await asyncio.sleep(30)

    primary = Agent(FunctionModel(slow), output_type=DocumentExtraction)
    extractor = DocumentExtractor(Settings(fallback_models=("google:invalid-reserve",)))

    def build(model):
        if model == extractor.settings.model:
            return primary
        raise ValueError("synthetic invalid configuration")

    monkeypatch.setattr(extractor, "_get_agent", build)
    with pytest.raises(extractor_module.ExtractionTimeoutError, match="tempo limite"):
        run_analysis(extractor.extract("synthetic.png", synthetic_png()))


def test_rg_preserves_mixed_warning_about_cpf_and_category() -> None:
    warning = "O CPF e a categoria estão ilegíveis; confira o documento."
    extraction = DocumentExtraction(kind="rg", warnings=[warning])
    assert extraction.warnings == [warning]


def test_rg_keeps_emission_warning_while_dropping_only_unrelated_warning() -> None:
    relevant = "A emissão e a validade estão parcialmente ilegíveis."
    unrelated = "A categoria de habilitação não foi encontrada."
    extraction = DocumentExtraction(kind="rg", warnings=[relevant, unrelated])
    assert extraction.warnings == [relevant]


def test_http_flow_validates_in_worker_before_model_and_returns_usage(monkeypatch) -> None:
    calls = []

    async def successful(messages, info):
        calls.append(1)
        return response(info)

    extractor = DocumentExtractor(
        Settings(model="test:model"),
        agent=Agent(FunctionModel(successful), output_type=DocumentExtraction),
    )
    monkeypatch.setattr(main_module, "extractor", extractor)
    with TestClient(main_module.app, client=("127.0.0.1", 51234)) as client:
        invalid = client.post("/api/extract", files={
            "document": ("synthetic.png", b"\x89PNG\r\n\x1a\n", "image/png"),
        })
        assert invalid.status_code == 400
        assert calls == []
        valid = client.post("/api/extract", files={
            "document": ("synthetic.png", synthetic_png(), "image/png"),
        })
    assert valid.status_code == 200
    assert valid.headers["cache-control"] == "no-store"
    assert calls == [1]
    assert valid.json()["usage"] == {"requests": 1, "inputTokens": 100, "outputTokens": 10}
