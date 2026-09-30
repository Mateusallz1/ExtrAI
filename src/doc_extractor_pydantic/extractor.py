from __future__ import annotations

import asyncio
import base64
import logging
import time
from io import BytesIO
from pathlib import PurePath
from typing import Any

import httpx
from pydantic_ai import Agent, BinaryContent, UsageLimits
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.result import RunUsage
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, ContentStream, StreamObject

from .config import Settings
from .limits import (
    EXTRACTION_TIMEOUT_SECONDS,
    MAX_CONTENT_STREAM_BYTES,
    MAX_PDF_PAGES,
    MAX_PREVIEW_CANDIDATES,
    MAX_PREVIEW_IMAGES,
    MAX_PREVIEW_PIXELS,
    MAX_PREVIEW_SCAN_PAGES,
    MAX_STREAM_OPERATIONS,
    MIN_PREVIEW_SIDE,
    MODEL_TIMEOUT_SECONDS,
    PROVIDER_BACKOFF_SECONDS,
    PROVIDER_RETRIES,
    upload_limit_message,
)
from .models import EXPECTED_FIELDS, DocumentExtraction
from .prompts import EXTRACTION_INSTRUCTIONS

IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
ALLOWED_EXTENSIONS = {".pdf", *IMAGE_MEDIA_TYPES}
IDENTITY_MATRIX = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

Matrix = tuple[float, float, float, float, float, float]


class UploadValidationError(ValueError):
    """Raised when an upload is not a supported document."""


class ProviderNotConfiguredError(RuntimeError):
    """Raised before a request when provider credentials are missing."""


class ExtractionTimeoutError(RuntimeError):
    """Raised when the provider does not answer inside the local time budget."""


class ProviderUnavailableError(RuntimeError):
    """Raised when the model service is temporarily unavailable."""


class ProviderRateLimitError(RuntimeError):
    """Raised when the provider refuses the request because of quota or rate limit."""


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
        model_settings: dict[str, object] | None = None
        model_lower = target_model.lower()
        if model_lower.startswith(("google:", "google-cloud:", "google-gla:", "google-vertex:")):
            model_settings = {
                "google_thinking_config": {"thinking_level": "MINIMAL"}
            }
        return Agent(
            model=target_model,
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
        document = validate_upload(
            file_name=file_name,
            content=content,
            max_upload_bytes=self.settings.max_upload_bytes,
        )
        if not self.settings.provider_configured():
            raise ProviderNotConfiguredError(
                f"Configure as credenciais do provedor para {self.settings.model}."
            )

        media_type = media_type_for(file_name, content_type)
        pages = len(document.pages) if document is not None else 1
        previews = extract_pdf_previews(document)
        prompt = (
            "Extraia os campos do documento usando somente o conteúdo visível. "
            "Quando houver uma imagem complementar da frente, use-a para ler os "
            "campos pequenos com prioridade. Não invente valores."
        )
        message_parts: list[object] = [
            prompt,
            BinaryContent(data=content, media_type=media_type),
        ]
        if previews:
            message_parts.append(_preview_binary_content(previews[0]))

        started = time.perf_counter()
        deadline = started + EXTRACTION_TIMEOUT_SECONDS

        candidates: list[tuple[str, Any]] = []
        if self.agent is not None:
            candidates.append((self.settings.model, self.agent))
            if self.fallback_agents:
                for idx, fb_agent in enumerate(self.fallback_agents):
                    name = (
                        self.settings.fallback_models[idx]
                        if idx < len(self.settings.fallback_models)
                        else f"fallback-{idx}"
                    )
                    candidates.append((name, fb_agent))
        else:
            candidates.append((self.settings.model, self._get_agent(self.settings.model)))
            for fb_model in self.settings.configured_fallback_models():
                candidates.append((fb_model, self._get_agent(fb_model)))

        last_error: Exception | None = None
        result = None
        model_used: str | None = None

        for idx, (target_model, target_agent) in enumerate(candidates):
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
                result = await self._run_model_with_backoff(
                    agent=target_agent,
                    message_parts=message_parts,
                    timeout=per_model_timeout,
                )
                model_used = target_model
                if idx > 0:
                    logger.info(
                        "fallback succeeded using model=%s after primary failure",
                        target_model,
                    )
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
                    "model %s failed (%s); attempting fallback",
                    target_model,
                    type(error).__name__,
                )

        if result is None:
            if last_error is not None:
                raise last_error
            raise ProviderUnavailableError("O provedor de IA está temporariamente indisponível.")

        extraction = result.output
        if not isinstance(extraction, DocumentExtraction):
            extraction = DocumentExtraction.model_validate(extraction)
        raw_usage = getattr(result, "usage", None)
        if isinstance(raw_usage, RunUsage):
            usage = raw_usage
        elif callable(raw_usage):
            usage = raw_usage()
        else:
            usage = raw_usage
        usage_data = (
            {
                "requests": getattr(usage, "requests", 1),
                "inputTokens": getattr(usage, "input_tokens", 0),
                "outputTokens": getattr(usage, "output_tokens", 0),
            }
            if usage is not None
            else None
        )
        duration_ms = round((time.perf_counter() - started) * 1000)
        return to_api_response(
            extraction,
            pages=pages,
            duration_ms=duration_ms,
            previews=previews,
            usage=usage_data,
            model_used=model_used,
        )

    async def _run_model_with_backoff(
        self, agent: Any, message_parts: list[object], timeout: float
    ) -> Any:
        async with asyncio.timeout(timeout):
            for attempt in range(PROVIDER_RETRIES + 1):
                try:
                    return await agent.run(
                        message_parts,
                        usage_limits=UsageLimits(
                            response_tokens_limit=1500, request_limit=PROVIDER_RETRIES + 1
                        ),
                    )
                except ModelHTTPError as error:
                    retryable = error.status_code in {429, 500, 502, 503, 504}
                    if not retryable or attempt >= PROVIDER_RETRIES:
                        raise _provider_error(error) from error
                except (httpx.ConnectError, httpx.TimeoutException) as error:
                    if attempt >= PROVIDER_RETRIES:
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


def validate_upload(
    file_name: str | None, content: bytes, max_upload_bytes: int
) -> PdfReader | None:
    """Validate the upload and return the single parsed PDF, when the upload is one."""

    if not file_name:
        raise UploadValidationError("Selecione um arquivo.")

    extension = PurePath(file_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Formato não suportado. Use PDF, JPG, JPEG, PNG ou WEBP.")
    if not content:
        raise UploadValidationError("O arquivo está vazio.")
    if len(content) > max_upload_bytes:
        raise UploadValidationError(upload_limit_message(max_upload_bytes))

    if extension == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise UploadValidationError("O arquivo não parece ser um PDF válido.")
        try:
            document = PdfReader(BytesIO(content))
            if document.is_encrypted:
                raise UploadValidationError("PDF protegido por senha não é suportado.")
            pages = len(document.pages)
        except UploadValidationError:
            raise
        except Exception as error:
            raise UploadValidationError("O arquivo não parece ser um PDF válido.") from error
        if pages < 1:
            raise UploadValidationError("O PDF não contém nenhuma página válida.")
        if pages > MAX_PDF_PAGES:
            raise UploadValidationError(
                f"O PDF tem {pages} páginas e o limite local é de {MAX_PDF_PAGES}."
            )
        return document
    if extension == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UploadValidationError("O arquivo não parece ser um PNG válido.")
    if extension in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise UploadValidationError("O arquivo não parece ser uma imagem JPEG válida.")
    if extension == ".webp" and not (
        content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP"
    ):
        raise UploadValidationError("O arquivo não parece ser uma imagem WebP válida.")
    return None


def media_type_for(file_name: str, content_type: str | None = None) -> str:
    extension = PurePath(file_name).suffix.lower()
    if extension == ".pdf":
        return "application/pdf"
    return IMAGE_MEDIA_TYPES[extension]


def _multiply_matrix(left: Matrix, right: Matrix) -> Matrix:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re + lc * rf + le,
        lb * re + ld * rf + lf,
    )


def _placement_box(
    ctm: Matrix, page_width: float, page_height: float
) -> tuple[float, float, float, float] | None:
    """Turn the current transformation matrix into a normalized page rectangle."""

    a, b, c, d, e, f = ctm
    points = ((e, f), (a + e, b + f), (c + e, d + f), (a + c + e, b + d + f))
    left = max(0.0, min(point[0] for point in points))
    right = min(page_width, max(point[0] for point in points))
    y_values = [point[1] for point in points]
    top = min(y_values) if d < 0 else page_height - max(y_values)
    bottom = max(y_values) if d < 0 else page_height - min(y_values)
    top = max(0.0, min(page_height, top))
    bottom = max(0.0, min(page_height, bottom))
    if right <= left or bottom <= top:
        return None
    return (
        round(left / page_width, 4),
        round(top / page_height, 4),
        round((right - left) / page_width, 4),
        round((bottom - top) / page_height, 4),
    )


def _image_xobject_sizes(page: PageObject) -> dict[str, tuple[int, int]]:
    """Read the declared size of every image XObject without decoding a single pixel."""

    resources = page.get("/Resources")
    if resources is None:
        return {}
    xobjects = resources.get_object().get("/XObject")
    if xobjects is None:
        return {}
    xobjects = xobjects.get_object()
    sizes: dict[str, tuple[int, int]] = {}
    for name in xobjects:
        try:
            xobject = xobjects[name].get_object()
            if xobject.get("/Subtype") != "/Image":
                continue
            width = int(xobject["/Width"])
            height = int(xobject["/Height"])
        except Exception:
            continue
        if width > 0 and height > 0:
            sizes[str(name)] = (width, height)
    return sizes


def _page_content_data(page: PageObject) -> bytes:
    """Return the decoded content stream, or nothing when it is too large to walk."""

    if "/Contents" not in page:
        return b""
    contents = page["/Contents"]
    if isinstance(contents, StreamObject):
        data = contents.get_data()
        return b"" if len(data) > MAX_CONTENT_STREAM_BYTES else data
    if not isinstance(contents, ArrayObject):
        return b""
    chunks: list[bytes] = []
    total = 0
    for item in contents:
        resolved = item.get_object()
        if not isinstance(resolved, StreamObject):
            continue
        chunk = resolved.get_data()
        total += len(chunk) + 1
        if total > MAX_CONTENT_STREAM_BYTES:
            return b""
        chunks.append(chunk)
    return b"\n".join(chunks)


def _page_preview_candidates(
    page_number: int, page: PageObject, document: PdfReader, budget: int
) -> list[dict[str, Any]]:
    """Locate the drawable images of one page using only declared metadata."""

    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)
    if page_width <= 0 or page_height <= 0:
        return []
    sizes = _image_xobject_sizes(page)
    if not sizes:
        return []
    data = _page_content_data(page)
    if not data:
        return []
    stream = ContentStream(None, document)
    stream.set_data(data)

    candidates: list[dict[str, Any]] = []
    drawn: set[str] = set()
    ctm = IDENTITY_MATRIX
    stack: list[Matrix] = []
    operations_count = 0
    for operands, operator in stream.operations:
        operations_count += 1
        if operations_count > MAX_STREAM_OPERATIONS:
            break
        if operator == b"q":
            if len(stack) < 32:
                stack.append(ctm)
        elif operator == b"Q":
            ctm = stack.pop() if stack else IDENTITY_MATRIX
        elif operator == b"cm":
            if len(operands) != 6:
                continue
            try:
                ctm = _multiply_matrix(ctm, tuple(float(value) for value in operands))
            except (TypeError, ValueError):
                continue
        elif operator == b"Do":
            if not operands:
                continue
            name = str(operands[0])
            if name in drawn:
                # The same XObject drawn again is the same preview.
                continue
            size = sizes.get(name)
            if size is None:
                continue
            image_width, image_height = size
            if min(image_width, image_height) < MIN_PREVIEW_SIDE:
                continue
            if image_width * image_height > MAX_PREVIEW_PIXELS:
                continue
            box = _placement_box(ctm, page_width, page_height)
            if box is None:
                continue
            drawn.add(name)
            left, top, width, height = box
            candidates.append(
                {
                    "page": page_number,
                    "name": name,
                    "pixels": image_width * image_height,
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "sourceWidth": image_width,
                    "sourceHeight": image_height,
                }
            )
            if len(candidates) >= budget:
                break
    return candidates


def _encode_preview(document: PdfReader, candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Decode and encode one chosen image, after the selection is already settled."""

    try:
        image_file = document.pages[candidate["page"] - 1].images[candidate["name"]]
        image = image_file.image
        if image is None:
            return None
        is_jpeg = (getattr(image, "format", None) or "").lower() in {"jpeg", "jpg"}
        max_dim = 1600
        needs_resize = max(image.width, image.height) > max_dim
        if needs_resize:
            scale = max_dim / max(image.width, image.height)
            new_size = (int(image.width * scale), int(image.height * scale))
            image = image.resize(new_size)

        if is_jpeg and not needs_resize:
            image_data = image_file.data
            media_type = "image/jpeg"
        else:
            image_stream = BytesIO()
            if getattr(image, "mode", None) in {"RGBA", "P", "LA"}:
                image = image.convert("RGB")
            image.save(image_stream, format="JPEG", quality=85, optimize=True)
            image_data = image_stream.getvalue()
            media_type = "image/jpeg"
    except Exception:
        return None
    encoded = base64.b64encode(image_data).decode("ascii")
    preview = {key: value for key, value in candidate.items() if key not in {"name", "pixels"}}
    preview["label"] = str(candidate["name"]).lstrip("/")
    preview["primary"] = False
    preview["src"] = f"data:{media_type};base64,{encoded}"
    preview["_raw_data"] = image_data
    preview["_media_type"] = media_type
    return preview


def extract_pdf_previews(document: PdfReader | None) -> list[dict[str, Any]]:
    """Extract prominent embedded PDF images for a local, zoomable preview."""

    if document is None:
        return []
    candidates: list[dict[str, Any]] = []
    try:
        for page_number, page in enumerate(document.pages, start=1):
            if page_number > MAX_PREVIEW_SCAN_PAGES:
                break
            budget = MAX_PREVIEW_CANDIDATES - len(candidates)
            if budget <= 0:
                break
            try:
                candidates.extend(
                    _page_preview_candidates(page_number, page, document, budget)
                )
            except Exception:
                continue
    except Exception:
        return []

    candidates.sort(key=lambda item: (item["page"], -item["pixels"], item["top"]))
    previews: list[dict[str, Any]] = []
    for candidate in candidates:
        if len(previews) >= MAX_PREVIEW_IMAGES:
            break
        preview = _encode_preview(document, candidate)
        if preview is not None:
            previews.append(preview)
    for index, preview in enumerate(previews):
        preview["primary"] = index == 0
        preview["label"] = "Frente" if index == 0 else "Verso" if index == 1 else "Detalhe"
    return previews


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
        field_dict: dict[str, Any] = {
            "value": value.value,
            "confidence": value.confidence,
            "label": FIELD_LABELS[key],
        }
        if value.box_2d is not None:
            field_dict["box2d"] = value.box_2d
        fields[api_key] = field_dict
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
