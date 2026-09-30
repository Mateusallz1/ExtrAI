from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx
from pydantic_ai import Agent, BinaryContent, UsageLimits
from pydantic_ai.exceptions import (
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from pydantic_ai.result import RunUsage

from .config import Settings
from .document_processing import (
    DocumentProcessingTimeoutError,
    process_document_async,
)
from .document_processing import (
    UploadValidationError as UploadValidationError,
)
from .document_processing import (
    extract_pdf_previews as extract_pdf_previews,
)
from .document_processing import (
    media_type_for as media_type_for,
)
from .document_processing import (
    validate_upload as validate_upload,
)
from .limits import (
    EXTRACTION_TIMEOUT_SECONDS,
    MODEL_TIMEOUT_SECONDS,
    PROVIDER_BACKOFF_SECONDS,
    PROVIDER_RETRIES,
)
from .models import EXPECTED_FIELDS, DocumentExtraction
from .prompts import EXTRACTION_INSTRUCTIONS
from .provider_usage import BudgetedModel, ProviderUsage, RequestBudget


class ProviderNotConfiguredError(RuntimeError):
    """Raised before a request when provider credentials are missing."""


class ExtractionTimeoutError(RuntimeError):
    """Raised when document processing or the provider exceeds the time budget."""


class ProviderUnavailableError(RuntimeError):
    """Raised when the model service is temporarily unavailable."""


class ProviderRateLimitError(RuntimeError):
    """Raised when the provider refuses a request because of quota or rate limit."""


class ProviderConnectionError(RuntimeError):
    """Raised when the provider cannot be reached from the local machine."""


def _provider_error(error: ModelHTTPError) -> RuntimeError:
    if error.status_code == 429:
        return ProviderRateLimitError(
            "O provedor atingiu um limite temporário. Tente novamente em instantes."
        )
    if error.status_code in {500, 502, 503, 504}:
        return ProviderUnavailableError(
            "O provedor de IA está temporariamente indisponível. Tente novamente."
        )
    return error


logger = logging.getLogger("doc_extractor_pydantic")


class DocumentExtractor:
    def __init__(
        self,
        settings: Settings | None = None,
        agent: Any | None = None,
        fallback_agents: list[Any] | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.agent = agent
        self.fallback_agents = fallback_agents
        self._cached_agents: dict[str, Any] = {}
        if agent is not None:
            self._cached_agents[self.settings.model] = agent

    def _get_agent(self, model_name: str) -> Any:
        if model_name not in self._cached_agents:
            self._cached_agents[model_name] = self._build_agent(model_name)
        return self._cached_agents[model_name]

    def _build_agent(self, model: str | None = None) -> Agent:
        target_model = model or self.settings.model
        agent_model = target_model
        model_settings: dict[str, object] | None = None
        model_lower = target_model.lower()
        if model_lower.startswith(("google:", "google-cloud:", "google-gla:", "google-vertex:")):
            model_settings = {"google_thinking_config": {"thinking_level": "MINIMAL"}}
        elif model_lower.startswith(("openai:", "openai-responses:")):
            from openai import AsyncOpenAI
            from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
            from pydantic_ai.providers.openai import OpenAIProvider

            # The application owns the request budget and backoff; SDK retries
            # would otherwise make extra HTTP calls below BudgetedModel.
            provider = OpenAIProvider(openai_client=AsyncOpenAI(max_retries=0))
            model_name = target_model.split(":", maxsplit=1)[1]
            model_class = OpenAIChatModel
            if model_lower.startswith("openai-responses:"):
                model_class = OpenAIResponsesModel
            agent_model = model_class(model_name, provider=provider)
        return Agent(
            model=agent_model,
            output_type=DocumentExtraction,
            instructions=EXTRACTION_INSTRUCTIONS,
            model_settings=model_settings,
            retries=PROVIDER_RETRIES,
        )

    async def extract(
        self,
        file_name: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        deadline = started + EXTRACTION_TIMEOUT_SECONDS
        try:
            async with asyncio.timeout(EXTRACTION_TIMEOUT_SECONDS):
                processed = await process_document_async(
                    file_name, content, self.settings.max_upload_bytes, content_type
                )
        except (TimeoutError, DocumentProcessingTimeoutError):
            raise ExtractionTimeoutError(
                "O documento excedeu o tempo limite de processamento local."
            ) from None

        if self.agent is None and not self.settings.provider_configured():
            raise ProviderNotConfiguredError(
                "Configure as credenciais e o modelo do provedor."
            )
        previews = processed.previews
        prompt = (
            "Extraia os campos do documento usando somente o conteúdo visível. "
            "Quando houver uma imagem complementar da frente, use-a para ler os "
            "campos pequenos com prioridade. Não invente valores."
        )
        message_parts: list[object] = [
            prompt,
            BinaryContent(data=content, media_type=processed.media_type),
        ]
        if previews:
            message_parts.append(_preview_binary_content(previews[0]))

        candidates: list[tuple[str, Any | None]] = [(self.settings.model, self.agent)]
        if self.agent is not None:
            for idx, fb_agent in enumerate(self.fallback_agents or []):
                name = (
                    self.settings.fallback_models[idx]
                    if idx < len(self.settings.fallback_models)
                    else f"fallback-{idx}"
                )
                candidates.append((name, fb_agent))
        else:
            candidates.extend((name, None) for name in self.settings.configured_fallback_models())

        last_error: Exception | None = None
        result = None
        model_used: str | None = None
        total_usage = ProviderUsage()
        for idx, (target_model, injected_agent) in enumerate(candidates):
            has_fallback = idx < len(candidates) - 1
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise ExtractionTimeoutError(
                    "O provedor não respondeu dentro do tempo limite local."
                )
            per_model_timeout = (
                min(MODEL_TIMEOUT_SECONDS, remaining) if has_fallback else remaining
            )
            try:
                # Reserve agents are built only when the primary actually needs one.
                target_agent = injected_agent or self._get_agent(target_model)
            except (ValueError, ImportError, UserError) as error:
                if idx == 0:
                    raise ProviderNotConfiguredError(
                        "A configuração do provedor não é válida."
                    ) from None
                logger.warning(
                    "fallback configuration ignored: error_type=%s", type(error).__name__
                )
                continue
            try:
                result = await self._run_model_with_backoff(
                    target_agent, message_parts, per_model_timeout, total_usage
                )
                model_used = target_model
                if idx > 0:
                    logger.info("fallback succeeded using model=%s", target_model)
                break
            except (
                ProviderUnavailableError,
                ProviderConnectionError,
                ProviderRateLimitError,
                TimeoutError,
                ExtractionTimeoutError,
                UnexpectedModelBehavior,
            ) as error:
                last_error = error
                if not has_fallback:
                    if isinstance(error, (TimeoutError, ExtractionTimeoutError)):
                        raise ExtractionTimeoutError(
                            "O provedor não respondeu dentro do tempo limite local."
                        ) from error
                    raise
                logger.warning(
                    "model failed; attempting fallback: error_type=%s", type(error).__name__
                )

        if result is None:
            if last_error is not None:
                if isinstance(last_error, (TimeoutError, ExtractionTimeoutError)):
                    raise ExtractionTimeoutError(
                        "O provedor não respondeu dentro do tempo limite local."
                    ) from last_error
                raise last_error
            raise ProviderUnavailableError("O provedor de IA está temporariamente indisponível.")
        extraction = result.output
        if not isinstance(extraction, DocumentExtraction):
            extraction = DocumentExtraction.model_validate(extraction)
        return to_api_response(
            extraction,
            pages=processed.pages,
            duration_ms=round((time.perf_counter() - started) * 1000),
            previews=previews,
            usage=total_usage.to_api(),
            model_used=model_used,
        )

    async def _run_model_with_backoff(
        self,
        agent: Any,
        message_parts: list[object],
        timeout: float,
        total_usage: ProviderUsage | None = None,
    ) -> Any:
        usage = total_usage if total_usage is not None else ProviderUsage()
        budget = RequestBudget(PROVIDER_RETRIES + 1, usage)
        run_usage = RunUsage()
        real_agent = isinstance(agent, Agent)
        bounded_model = BudgetedModel(agent.model, budget) if real_agent else None
        async with asyncio.timeout(timeout):
            for attempt in range(PROVIDER_RETRIES + 1):
                try:
                    if real_agent:
                        result = await agent.run(
                            message_parts,
                            model=bounded_model,
                            usage=run_usage,
                            usage_limits=UsageLimits(
                                response_tokens_limit=1500, request_limit=budget.limit
                            ),
                        )
                    else:
                        # An injected agent may abstract multiple model requests.
                        budget.reserve()
                        result = await agent.run(
                            message_parts,
                            usage=run_usage,
                            usage_limits=UsageLimits(
                                response_tokens_limit=1500, request_limit=budget.limit
                            ),
                        )
                        reported = getattr(result, "usage", None)
                        if callable(reported) and not isinstance(reported, RunUsage):
                            reported = reported()
                        if reported is not None:
                            usage.add_tokens(reported)
                            extra = max(0, getattr(reported, "requests", 1) - 1)
                            for _ in range(extra):
                                budget.reserve()
                    return result
                except UsageLimitExceeded:
                    raise ProviderUnavailableError(
                        "A análise atingiu o limite local de tentativas."
                    ) from None
                except ModelHTTPError as error:
                    retryable = error.status_code in {429, 500, 502, 503, 504}
                    if not retryable or budget.used >= budget.limit:
                        raise _provider_error(error) from error
                except (httpx.ConnectError, httpx.TimeoutException) as error:
                    if budget.used >= budget.limit:
                        raise ProviderConnectionError(
                            "Não foi possível conectar ao provedor de IA."
                        ) from error
                await asyncio.sleep(PROVIDER_BACKOFF_SECONDS * (2**attempt))
            raise ProviderUnavailableError("O provedor de IA está temporariamente indisponível.")

    async def _run_provider_with_backoff(self, message_parts: list[object]) -> Any:
        agent = self.agent if self.agent is not None else self._get_agent(self.settings.model)
        return await self._run_model_with_backoff(
            agent=agent,
            message_parts=message_parts,
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        )


def _preview_binary_content(preview: dict[str, Any]) -> BinaryContent:
    if "_raw_data" in preview and "_media_type" in preview:
        return BinaryContent(
            data=preview["_raw_data"],
            media_type=preview["_media_type"],
        )
    source = str(preview["src"])
    media_header, encoded = source.split(",", maxsplit=1)
    media_type = media_header.removeprefix("data:").split(";", maxsplit=1)[0]
    return BinaryContent(
        data=base64.b64decode(encoded),
        media_type=media_type,
    )


FIELD_LABELS = {
    "name": "Nome",
    "cpf": "CPF",
    "birth_date": "Data de nascimento",
    "issue_date": "Data de emissão",
    "validity": "Validade",
    "registration": "Registro",
    "category": "Categoria",
    "birth_place": "Local de nascimento",
    "nationality": "Nacionalidade",
    "parentage": "Filiação",
}
API_FIELD_NAMES = {
    "birth_date": "birthDate",
    "issue_date": "issueDate",
    "birth_place": "birthPlace",
}


def to_api_response(
    extraction: DocumentExtraction,
    pages: int,
    duration_ms: int,
    previews: list[dict[str, Any]] | None = None,
    usage: dict[str, int] | None = None,
    model_used: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {}
    for key, value in extraction.fields.populated().items():
        api_key = API_FIELD_NAMES.get(key, key)
        fields[api_key] = {
            "value": value.value,
            "confidence": value.confidence,
            "label": FIELD_LABELS[key],
        }
    expected = EXPECTED_FIELDS.get(extraction.kind, EXPECTED_FIELDS["unknown"])
    missing = [
        {"key": API_FIELD_NAMES.get(key, key), "label": FIELD_LABELS[key]}
        for key in expected
        if API_FIELD_NAMES.get(key, key) not in fields
    ]
    cleaned_previews = [
        {k: v for k, v in p.items() if not k.startswith("_")}
        for p in (previews or [])
    ]
    response: dict[str, Any] = {
        "kind": extraction.kind,
        "pages": pages,
        "fields": fields,
        "missing": missing,
        "text": format_text(extraction),
        "warnings": extraction.warnings,
        "durationMs": duration_ms,
        "previews": cleaned_previews,
        "usage": usage,
    }
    if model_used is not None:
        response["modelUsed"] = model_used
    return response


def format_text(extraction: DocumentExtraction) -> str:
    kind_label = extraction.kind.upper()
    lines = [f"DOCUMENTO: {kind_label}"]
    structured = [
        f"{FIELD_LABELS[key]}: {value.value}"
        for key, value in extraction.fields.populated().items()
        if value.value
    ]
    if structured:
        lines.extend(["", "DADOS ESTRUTURADOS", *structured])
    if extraction.transcription:
        lines.extend(["", "TRANSCRIÇÃO RECONHECIDA", extraction.transcription])
    return "\n".join(lines)
