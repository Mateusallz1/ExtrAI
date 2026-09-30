from __future__ import annotations

import asyncio
import logging
import multiprocessing
import threading
import time
from io import BytesIO
from multiprocessing.context import SpawnProcess

import pytest
from anyio import create_task_group, sleep
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

import doc_extractor_pydantic.document_processing as processing
from doc_extractor_pydantic.document_processing import (
    DocumentProcessingError,
    DocumentProcessingTimeoutError,
    UploadValidationError,
    extract_pdf_previews,
    process_document,
    process_document_async,
    validate_upload,
)


def synthetic_image(image_format: str = "PNG", size: tuple[int, int] = (20, 20)) -> bytes:
    output = BytesIO()
    with Image.new("RGB", size, (30, 120, 200)) as image:
        image.save(output, format=image_format)
    return output.getvalue()


def synthetic_pdf(*, inline_images: int = 0, xobjects: int = 1) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    images = DictionaryObject()
    operators = []
    for index in range(xobjects):
        image = DecodedStreamObject()
        image.set_data(synthetic_image("JPEG", (300, 300)))
        image.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(300),
                NameObject("/Height"): NumberObject(300),
                NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/Filter"): NameObject("/DCTDecode"),
            }
        )
        images[NameObject(f"/Image{index}")] = writer._add_object(image)
        operators.append(f"q 300 0 0 300 0 0 cm /Image{index} Do Q\n".encode())
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): images})
    contents = DecodedStreamObject()
    contents.set_data(
        b"".join(operators)
        + b"BI /W 1 /H 1 /BPC 8 /CS /RGB ID \x01\x02\x03 EI\n" * inline_images
    )
    page[NameObject("/Contents")] = writer._add_object(contents)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def waiting_worker(connection, extension, content, max_upload_bytes) -> None:
    """Synthetic sleeping child lets tests verify cancellation without CPU stress."""
    try:
        time.sleep(30)
    finally:
        connection.close()


@pytest.fixture
def delayed_worker_start(monkeypatch):
    original_start = SpawnProcess.start
    starting = threading.Event()
    started = []

    def slow_start(self):
        starting.set()
        try:
            time.sleep(0.1)
            original_start(self)
            started.append(self.pid)
        finally:
            starting.clear()

    monkeypatch.setattr(SpawnProcess, "start", slow_start)
    return starting, started


@pytest.mark.parametrize(
    "image_format,extension", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")]
)
def test_valid_images_are_readable(image_format: str, extension: str) -> None:
    assert validate_upload(f"synthetic.{extension}", synthetic_image(image_format), 4096) is None


@pytest.mark.parametrize(
    "file_name,content",
    [
        ("synthetic.png", b"\x89PNG\r\n\x1a\n"),
        ("synthetic.jpg", b"\xff\xd8\xff"),
        ("synthetic.webp", b"RIFFxxxxWEBP"),
    ],
)
def test_image_signatures_without_readable_pixels_are_rejected(
    file_name: str, content: bytes
) -> None:
    with pytest.raises(UploadValidationError, match="válid"):
        validate_upload(file_name, content, 4096)


def test_truncated_jpeg_is_rejected_after_header_verification() -> None:
    content = synthetic_image("JPEG", (100, 100))
    with pytest.raises(UploadValidationError, match="JPEG válida"):
        validate_upload("synthetic.jpg", content[:-20], 4096)


def test_animated_document_image_is_rejected() -> None:
    stream = BytesIO()
    with Image.new("RGB", (20, 20), (30, 120, 200)) as first:
        with Image.new("RGB", (20, 20), (200, 120, 30)) as second:
            first.save(stream, format="WEBP", save_all=True, append_images=[second], duration=20)
    with pytest.raises(UploadValidationError, match="animadas"):
        validate_upload("synthetic.webp", stream.getvalue(), 4096)


def test_image_pixel_limit_precedes_loading_pixels(monkeypatch) -> None:
    content = synthetic_image(size=(20, 20))
    loaded = []
    original_load = Image.Image.load

    def tracked_load(self, *args, **kwargs):
        loaded.append(self.size)
        return original_load(self, *args, **kwargs)

    monkeypatch.setattr(processing, "MAX_IMAGE_PIXELS", 399)
    monkeypatch.setattr(Image.Image, "load", tracked_load)
    with pytest.raises(UploadValidationError, match="pixels"):
        validate_upload("synthetic.png", content, 4096)
    assert loaded == []


def test_process_document_opens_pdf_once(monkeypatch) -> None:
    readers = []
    original_reader = processing.PdfReader

    def tracked_reader(*args, **kwargs):
        readers.append(1)
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(processing, "PdfReader", tracked_reader)
    result = process_document("synthetic.pdf", synthetic_pdf(), 4096)
    assert readers == [1]
    assert result.pages == 1
    assert result.media_type == "application/pdf"
    assert len(result.previews) == 1


def test_pdf_parser_does_not_log_document_content(caplog, capsys) -> None:
    marker = "SYNTHETIC_PRIVATE_VALUE"
    content = synthetic_pdf().replace(
        b"/Type /Catalog", b"/Type /Catalog (" + marker.encode() + b")"
    )
    with caplog.at_level(logging.INFO):
        assert validate_upload("synthetic.pdf", content, 8192) is not None
    captured = capsys.readouterr()
    assert marker not in caplog.text + captured.out + captured.err


def test_operation_budget_stops_before_parsing_trailing_content(monkeypatch) -> None:
    document = PdfReader(BytesIO(synthetic_pdf()))
    monkeypatch.setattr(processing, "MAX_STREAM_OPERATIONS", 3)
    # The final malformed token would fail if the parser materialized the stream.
    operations = list(processing._iter_stream_operations(b"q\n" * 3 + b"(", document))
    assert operations == [([], b"q")] * 3


def test_preview_does_not_decode_unselected_inline_images(monkeypatch) -> None:
    document = validate_upload("synthetic.pdf", synthetic_pdf(inline_images=5), 4096)
    decoded = []
    original_decode = processing._xobj_to_image

    def tracked_decode(xobject, *args, **kwargs):
        decoded.append((xobject["/Width"], xobject["/Height"]))
        return original_decode(xobject, *args, **kwargs)

    monkeypatch.setattr(processing, "_xobj_to_image", tracked_decode)
    previews = extract_pdf_previews(document)
    assert len(previews) == 1
    assert decoded == [(300, 300)]
    assert document.pages[0]._content_stream_images is None


def test_failed_previews_still_consume_decode_attempt_budget(monkeypatch) -> None:
    document = validate_upload("synthetic.pdf", synthetic_pdf(xobjects=6), 20000)
    attempts = []

    def failed_decode(document, candidate):
        attempts.append(candidate["name"])
        return None

    monkeypatch.setattr(processing, "_encode_preview", failed_decode)
    assert extract_pdf_previews(document) == []
    assert len(attempts) == processing.MAX_PREVIEW_IMAGES


def test_encoded_dimensions_are_checked_before_preview_decode(monkeypatch) -> None:
    document = validate_upload("synthetic.pdf", synthetic_pdf(), 4096)
    monkeypatch.setattr(processing, "MAX_PREVIEW_PIXELS", 40000)
    # A small declared size cannot conceal larger dimensions in the JPEG header.
    xobject = document.pages[0]["/Resources"]["/XObject"]["/Image0"]
    xobject[NameObject("/Width")] = NumberObject(200)
    xobject[NameObject("/Height")] = NumberObject(200)

    def unexpected_decode(*args, **kwargs):
        pytest.fail("pixel loading must not begin for an oversized encoded image")

    monkeypatch.setattr(processing, "_xobj_to_image", unexpected_decode)
    assert extract_pdf_previews(document) == []


def test_real_worker_preserves_api_and_keeps_documents_in_memory() -> None:
    result = asyncio.run(process_document_async("private-name.pdf", synthetic_pdf(), 4096))
    assert result.pages == 1
    assert result.media_type == "application/pdf"
    assert len(result.previews) == 1
    assert result.previews[0]["label"] == "Frente"
    assert result.previews[0]["primary"] is True


def test_real_worker_reports_invalid_input() -> None:
    with pytest.raises(UploadValidationError, match="PNG válido"):
        asyncio.run(process_document_async("synthetic.png", b"\x89PNG\r\n\x1a\n", 4096))


def test_real_worker_timeout_releases_child_process(monkeypatch) -> None:
    monkeypatch.setattr(processing, "_document_worker", waiting_worker)
    before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(DocumentProcessingTimeoutError, match="tempo limite"):
        asyncio.run(
            process_document_async("synthetic.png", synthetic_image(), 4096, timeout_seconds=0.2)
        )
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_cancellation_releases_worker_without_blocking_event_loop(monkeypatch) -> None:
    monkeypatch.setattr(processing, "_document_worker", waiting_worker)
    before = {child.pid for child in multiprocessing.active_children()}

    async def exercise() -> None:
        task = asyncio.create_task(process_document_async("synthetic.png", synthetic_image(), 4096))
        await asyncio.sleep(0.05)
        assert not task.done()
        assert {child.pid for child in multiprocessing.active_children()} != before
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_repeated_cancellation_waits_for_worker_cleanup(monkeypatch) -> None:
    monkeypatch.setattr(processing, "_document_worker", waiting_worker)
    original_dispose = processing._dispose_worker
    before = {child.pid for child in multiprocessing.active_children()}

    def delayed_dispose(*args):
        time.sleep(0.05)
        original_dispose(*args)

    monkeypatch.setattr(processing, "_dispose_worker", delayed_dispose)

    async def exercise() -> None:
        task = asyncio.create_task(process_document_async("synthetic.png", synthetic_image(), 4096))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_anyio_cancellation_keeps_cleanup_responsive(monkeypatch) -> None:
    monkeypatch.setattr(processing, "_document_worker", waiting_worker)
    original_dispose = processing._dispose_worker
    cleanup_running = threading.Event()
    heartbeat_during_cleanup = []
    before = {child.pid for child in multiprocessing.active_children()}

    def delayed_dispose(*args):
        cleanup_running.set()
        try:
            time.sleep(0.1)
            original_dispose(*args)
        finally:
            cleanup_running.clear()

    monkeypatch.setattr(processing, "_dispose_worker", delayed_dispose)

    async def exercise() -> None:
        stop = asyncio.Event()

        async def heartbeat() -> None:
            while not stop.is_set():
                await asyncio.sleep(0.01)
                if cleanup_running.is_set():
                    heartbeat_during_cleanup.append(1)

        pulse = asyncio.create_task(heartbeat())
        try:
            async with create_task_group() as group:

                async def cancel_request() -> None:
                    await sleep(0.05)
                    group.cancel_scope.cancel()

                group.start_soon(cancel_request)
                await process_document_async("synthetic.png", synthetic_image(), 4096)
        finally:
            stop.set()
            await pulse

    asyncio.run(exercise())
    assert heartbeat_during_cleanup
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_startup_timeout_stays_responsive_and_waits_before_disposal(delayed_worker_start) -> None:
    starting, started = delayed_worker_start
    heartbeats = []
    before = {child.pid for child in multiprocessing.active_children()}

    async def exercise() -> None:
        stop = asyncio.Event()

        async def heartbeat() -> None:
            while not stop.is_set():
                await asyncio.sleep(0.01)
                if starting.is_set():
                    heartbeats.append(1)

        pulse = asyncio.create_task(heartbeat())
        try:
            with pytest.raises(DocumentProcessingTimeoutError):
                await process_document_async(
                    "synthetic.png", synthetic_image(), 4096, timeout_seconds=0.02
                )
        finally:
            stop.set()
            await pulse

    asyncio.run(exercise())
    assert started and heartbeats
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_cancellation_during_startup_waits_before_disposal(delayed_worker_start) -> None:
    starting, started = delayed_worker_start
    before = {child.pid for child in multiprocessing.active_children()}

    async def exercise() -> None:
        task = asyncio.create_task(process_document_async("synthetic.png", synthetic_image(), 4096))
        while not starting.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert started
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_anyio_cancellation_during_startup_waits_before_disposal(delayed_worker_start) -> None:
    starting, started = delayed_worker_start
    before = {child.pid for child in multiprocessing.active_children()}

    async def exercise() -> None:
        async with create_task_group() as group:

            async def cancel_request() -> None:
                while not starting.is_set():
                    await sleep(0.001)
                group.cancel_scope.cancel()

            group.start_soon(cancel_request)
            await process_document_async("synthetic.png", synthetic_image(), 4096)

    asyncio.run(exercise())
    assert started
    assert {child.pid for child in multiprocessing.active_children()} == before


def test_worker_startup_failure_is_consumed_and_sanitized(monkeypatch) -> None:
    before = {child.pid for child in multiprocessing.active_children()}

    def failed_start(self):
        raise RuntimeError("SYNTHETIC_PRIVATE_STARTUP_VALUE")

    monkeypatch.setattr(SpawnProcess, "start", failed_start)
    with pytest.raises(DocumentProcessingError) as caught:
        asyncio.run(process_document_async("synthetic.png", synthetic_image(), 4096))
    assert "SYNTHETIC_PRIVATE_STARTUP_VALUE" not in str(caught.value)
    assert {child.pid for child in multiprocessing.active_children()} == before
