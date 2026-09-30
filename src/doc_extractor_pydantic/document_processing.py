"""Validate and prepare documents without provider calls or document persistence."""

from __future__ import annotations

import asyncio
import base64
import math
import multiprocessing
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Any

from anyio import CancelScope
from PIL import Image
from pypdf import PageObject, PdfReader
from pypdf._utils import read_non_whitespace, read_until_regex
from pypdf.generic import ArrayObject, ContentStream, NameObject, StreamObject, read_object
from pypdf.generic._image_xobject import _xobj_to_image

from .limits import (
    LOCAL_PROCESSING_TIMEOUT_SECONDS,
    MAX_CONTENT_STREAM_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_PDF_PAGES,
    MAX_PREVIEW_CANDIDATES,
    MAX_PREVIEW_IMAGES,
    MAX_PREVIEW_PIXELS,
    MAX_PREVIEW_SCAN_PAGES,
    MAX_STREAM_OPERATIONS,
    MIN_PREVIEW_SIDE,
    upload_limit_message,
)
from .privacy_logging import configure_sensitive_dependency_logging

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
    """An upload is not a readable supported document."""


class DocumentProcessingError(RuntimeError):
    """The isolated local worker failed without exposing its exception details."""


class DocumentProcessingTimeoutError(DocumentProcessingError):
    """The document exceeded its local processing budget."""


@dataclass(frozen=True)
class ProcessedDocument:
    media_type: str
    pages: int
    previews: list[dict[str, Any]]


def _upload_extension(file_name: str | None, content: bytes, max_upload_bytes: int) -> str:
    if not file_name:
        raise UploadValidationError("Selecione um arquivo.")
    extension = PurePath(file_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Formato não suportado. Use PDF, JPG, JPEG, PNG ou WEBP.")
    if not content:
        raise UploadValidationError("O arquivo está vazio.")
    if len(content) > max_upload_bytes:
        raise UploadValidationError(upload_limit_message(max_upload_bytes))
    return extension


def _check_image_size(image: Image.Image, pixel_limit: int) -> None:
    if image.width <= 0 or image.height <= 0 or image.width * image.height > pixel_limit:
        raise UploadValidationError("A imagem excede o limite local de pixels.")


def _validate_image(content: bytes, extension: str) -> None:
    expected_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[
        extension
    ]
    invalid_message = {
        "PNG": "O arquivo não parece ser um PNG válido.",
        "JPEG": "O arquivo não parece ser uma imagem JPEG válida.",
        "WEBP": "O arquivo não parece ser uma imagem WebP válida.",
    }[expected_format]
    try:
        with Image.open(BytesIO(content), formats=[expected_format]) as image:
            _check_image_size(image, MAX_IMAGE_PIXELS)
            if getattr(image, "n_frames", 1) != 1:
                raise UploadValidationError("Imagens animadas não são suportadas.")
            image.verify()
        # JPEG verification alone checks headers, not whether its pixels can be read.
        with Image.open(BytesIO(content), formats=[expected_format]) as image:
            _check_image_size(image, MAX_IMAGE_PIXELS)
            image.load()
    except UploadValidationError:
        raise
    except Exception:
        raise UploadValidationError(invalid_message) from None


def validate_upload(
    file_name: str | None, content: bytes, max_upload_bytes: int
) -> PdfReader | None:
    """Return the single validated PDF reader, or validate all pixels of an image."""

    configure_sensitive_dependency_logging()
    extension = _upload_extension(file_name, content, max_upload_bytes)
    if extension != ".pdf":
        _validate_image(content, extension)
        return None
    if not content.startswith(b"%PDF-"):
        raise UploadValidationError("O arquivo não parece ser um PDF válido.")
    try:
        document = PdfReader(BytesIO(content))
        if document.is_encrypted:
            raise UploadValidationError("PDF protegido por senha não é suportado.")
        pages = len(document.pages)
    except UploadValidationError:
        raise
    except Exception:
        raise UploadValidationError("O arquivo não parece ser um PDF válido.") from None
    if pages < 1:
        raise UploadValidationError("O PDF não contém nenhuma página válida.")
    if pages > MAX_PDF_PAGES:
        raise UploadValidationError(
            f"O PDF tem {pages} páginas e o limite local é de {MAX_PDF_PAGES}."
        )
    return document


def media_type_for(file_name: str, content_type: str | None = None) -> str:
    extension = PurePath(file_name).suffix.lower()
    return "application/pdf" if extension == ".pdf" else IMAGE_MEDIA_TYPES[extension]


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
    if not all(math.isfinite(value) for value in (*ctm, page_width, page_height)):
        return None
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
    resources = page.get("/Resources")
    if resources is None:
        return {}
    xobjects = resources.get_object().get("/XObject")
    if xobjects is None:
        return {}
    sizes: dict[str, tuple[int, int]] = {}
    for name, reference in xobjects.get_object().items():
        try:
            xobject = reference.get_object()
            if xobject.get("/Subtype") != "/Image":
                continue
            width, height = int(xobject["/Width"]), int(xobject["/Height"])
            if width > 0 and height > 0:
                sizes[str(name)] = (width, height)
        except Exception:
            continue
    return sizes


def _page_content_data(page: PageObject) -> bytes:
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


def _iter_stream_operations(data: bytes, document: PdfReader) -> Iterator[tuple[Any, bytes]]:
    """Read one operation at a time, stopping before parsing beyond the budget.

    pypdf's operations property materializes the entire stream before iteration.
    Reuse its token readers and inline-image scanner without invoking that property.
    Inline image bytes are scanned for syntax only; their pixels are never decoded.
    """

    stream = BytesIO(data)
    inline_parser = ContentStream(None, document)
    operands: list[Any] = []
    operation_count = 0
    while operation_count < MAX_STREAM_OPERATIONS:
        peek = read_non_whitespace(stream)
        if not peek:
            return
        stream.seek(-1, 1)
        if peek.isalpha() or peek in (b"'", b'"'):
            operator = read_until_regex(
                stream=stream, regex=NameObject.delimiter_pattern, length=64
            )
            if operator == b"BI":
                if operands:
                    return
                inline_parser._read_inline_image(stream)
                operator = b"INLINE IMAGE"
            operation_count += 1
            yield operands, operator
            operands = []
        elif peek == b"%":
            while peek not in (b"\r", b"\n", b""):
                peek = stream.read(1)
        else:
            if len(operands) >= 64:
                return
            operands.append(read_object(stream, None))


def _page_preview_candidates(
    page_number: int, page: PageObject, document: PdfReader, budget: int
) -> list[dict[str, Any]]:
    page_width, page_height = float(page.mediabox.width), float(page.mediabox.height)
    if page_width <= 0 or page_height <= 0 or budget <= 0:
        return []
    sizes = _image_xobject_sizes(page)
    if not sizes:
        return []
    data = _page_content_data(page)
    candidates: list[dict[str, Any]] = []
    drawn: set[str] = set()
    ctm = IDENTITY_MATRIX
    stack: list[Matrix] = []
    for operands, operator in _iter_stream_operations(data, document):
        if operator == b"q":
            if len(stack) < 32:
                stack.append(ctm)
        elif operator == b"Q":
            ctm = stack.pop() if stack else IDENTITY_MATRIX
        elif operator == b"cm" and len(operands) == 6:
            try:
                ctm = _multiply_matrix(ctm, tuple(float(value) for value in operands))
            except (TypeError, ValueError):
                continue
        elif operator == b"Do" and operands:
            name = str(operands[0])
            size = sizes.get(name)
            if name in drawn or size is None:
                continue
            image_width, image_height = size
            if min(size) < MIN_PREVIEW_SIDE or image_width * image_height > MAX_PREVIEW_PIXELS:
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


def _validate_xobject_sizes(xobject: Any, seen: set[int] | None = None) -> None:
    """Check the chosen image and its soft masks before pypdf loads any pixels."""

    seen = set() if seen is None else seen
    if id(xobject) in seen or len(seen) >= 4:
        raise ValueError("Unsupported mask chain")
    seen.add(id(xobject))
    width, height = int(xobject["/Width"]), int(xobject["/Height"])
    if width <= 0 or height <= 0 or width * height > MAX_PREVIEW_PIXELS:
        raise ValueError("Image exceeds pixel limit")
    filters = xobject.get("/Filter")
    last_filter = filters[-1] if isinstance(filters, ArrayObject) else filters
    if last_filter in {"/DCTDecode", "/JPXDecode"}:
        # Encoded dimensions can disagree with untrusted PDF dictionary metadata.
        with Image.open(BytesIO(xobject.get_data())) as image:
            _check_image_size(image, MAX_PREVIEW_PIXELS)
    mask = xobject.get("/SMask")
    if mask is not None:
        _validate_xobject_sizes(mask.get_object(), seen)


def _encode_preview(document: PdfReader, candidate: dict[str, Any]) -> dict[str, Any] | None:
    try:
        page = document.pages[candidate["page"] - 1]
        xobject = page["/Resources"]["/XObject"][candidate["name"]].get_object()
        _validate_xobject_sizes(xobject)
        # page.images[name] enumerates and decodes unrelated inline images first.
        _, original_data, image = _xobj_to_image(xobject)
        if image is None:
            return None
        try:
            _check_image_size(image, MAX_PREVIEW_PIXELS)
            is_jpeg = (getattr(image, "format", None) or "").lower() in {"jpeg", "jpg"}
            needs_resize = max(image.size) > 1600
            if needs_resize:
                scale = 1600 / max(image.size)
                resized = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
                )
                image.close()
                image = resized
            if is_jpeg and not needs_resize:
                image_data = original_data
            else:
                if image.mode not in {"RGB", "L"}:
                    converted = image.convert("RGB")
                    image.close()
                    image = converted
                output = BytesIO()
                image.save(output, format="JPEG", quality=85, optimize=True)
                image_data = output.getvalue()
        finally:
            image.close()
    except Exception:
        return None
    encoded = base64.b64encode(image_data).decode("ascii")
    preview = {key: value for key, value in candidate.items() if key not in {"name", "pixels"}}
    preview.update(
        label=str(candidate["name"]).lstrip("/"),
        primary=False,
        src=f"data:image/jpeg;base64,{encoded}",
        _raw_data=image_data,
        _media_type="image/jpeg",
    )
    return preview


def extract_pdf_previews(document: PdfReader | None) -> list[dict[str, Any]]:
    configure_sensitive_dependency_logging()
    if document is None:
        return []
    candidates: list[dict[str, Any]] = []
    for page_index in range(min(len(document.pages), MAX_PREVIEW_SCAN_PAGES)):
        budget = MAX_PREVIEW_CANDIDATES - len(candidates)
        if budget <= 0:
            break
        try:
            candidates.extend(
                _page_preview_candidates(
                    page_index + 1, document.pages[page_index], document, budget
                )
            )
        except Exception:
            continue
    candidates.sort(key=lambda item: (item["page"], -item["pixels"], item["top"]))
    previews = []
    for candidate in candidates[:MAX_PREVIEW_IMAGES]:
        preview = _encode_preview(document, candidate)
        if preview is not None:
            previews.append(preview)
    for index, preview in enumerate(previews):
        preview["primary"] = index == 0
        preview["label"] = "Frente" if index == 0 else "Verso" if index == 1 else "Detalhe"
    return previews


def process_document(file_name: str, content: bytes, max_upload_bytes: int) -> ProcessedDocument:
    document = validate_upload(file_name, content, max_upload_bytes)
    return ProcessedDocument(
        media_type=media_type_for(file_name),
        pages=len(document.pages) if document is not None else 1,
        previews=extract_pdf_previews(document),
    )


def _document_worker(
    connection: Any, extension: str, content: bytes, max_upload_bytes: int
) -> None:
    configure_sensitive_dependency_logging()
    try:
        result = process_document("document" + extension, content, max_upload_bytes)
        connection.send(("ok", result))
    except UploadValidationError as error:
        connection.send(("invalid", str(error)))
    except Exception:
        connection.send(("failed", None))
    finally:
        connection.close()


def _make_worker(extension: str, content: bytes, max_upload_bytes: int) -> tuple[Any, Any, Any]:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_document_worker, args=(sender, extension, content, max_upload_bytes), daemon=True
    )
    return process, receiver, sender


def _dispose_worker(process: Any, receiver: Any, sender: Any) -> None:
    sender.close()
    if process.pid is not None:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
    receiver.close()
    if process.pid is None or not process.is_alive():
        process.close()


async def _finish_worker_startup_and_dispose(
    startup: asyncio.Task[None], process: Any, receiver: Any, sender: Any
) -> None:
    # Creating an OS process cannot be interrupted safely. If the caller times
    # out while start() is running, wait for its outcome before disposing it.
    try:
        await asyncio.shield(startup)
    except Exception:
        pass
    await asyncio.to_thread(_dispose_worker, process, receiver, sender)


async def process_document_async(
    file_name: str,
    content: bytes,
    max_upload_bytes: int,
    content_type: str | None = None,
    *,
    timeout_seconds: float | None = None,
) -> ProcessedDocument:
    """Run document CPU work in a disposable process and stop it on cancel/timeout.

    Only an extension and content bytes enter the worker; documents remain in
    memory. Threads create the process and wait for IPC/cleanup, never parse a document.
    """

    extension = _upload_extension(file_name, content, max_upload_bytes)
    process, receiver, sender = _make_worker(extension, content, max_upload_bytes)
    budget = LOCAL_PROCESSING_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    startup = asyncio.create_task(asyncio.to_thread(process.start))
    try:
        async with asyncio.timeout(budget):
            await asyncio.shield(startup)
            sender.close()
            status, result = await asyncio.to_thread(receiver.recv)
        if status == "invalid":
            raise UploadValidationError(result)
        if status != "ok" or not isinstance(result, ProcessedDocument):
            raise DocumentProcessingError("Não foi possível processar o documento localmente.")
        return result
    except TimeoutError:
        raise DocumentProcessingTimeoutError(
            "O documento excedeu o tempo limite de processamento local."
        ) from None
    except (EOFError, OSError):
        raise DocumentProcessingError(
            "Não foi possível processar o documento localmente."
        ) from None
    except (UploadValidationError, DocumentProcessingError):
        raise
    except Exception:
        raise DocumentProcessingError(
            "Não foi possível processar o documento localmente."
        ) from None
    finally:
        cleanup = asyncio.create_task(
            _finish_worker_startup_and_dispose(startup, process, receiver, sender)
        )
        cancelled_during_cleanup = False
        # Repeated cancellation must not leave a child process or open pipe behind.
        with CancelScope(shield=True):
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled_during_cleanup = True
        cleanup.result()
        if cancelled_during_cleanup:
            raise asyncio.CancelledError
