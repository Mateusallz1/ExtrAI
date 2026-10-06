from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings, is_loopback
from .extractor import (
    DocumentExtractor,
    ExtractionTimeoutError,
    ProviderConnectionError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    UploadValidationError,
)
from .limits import (
    MAX_CONCURRENT_EXTRACTIONS,
    MULTIPART_OVERHEAD_BYTES,
    upload_limit_message,
)
from .privacy_logging import configure_sensitive_dependency_logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
configure_sensitive_dependency_logging()
logger = logging.getLogger(__name__)

settings = Settings.from_env()
extractor = DocumentExtractor(settings)
STATIC_DIR = Path(__file__).with_name("static")
static_index = STATIC_DIR / "index.html"
STATIC_ASSETS = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "logo.png": "image/png",
    "favicon.ico": "image/x-icon",
}
STATIC_FILES = {
    "app.css": STATIC_DIR / "app.css",
    "app.js": STATIC_DIR / "app.js",
    "logo.png": STATIC_DIR / "logo.png",
    "favicon.ico": STATIC_DIR / "favicon.ico",
}


MAX_REQUEST_BYTES = settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
LAST_EXTRACTION_TTL_SECONDS = 30 * 60
last_extraction_result: dict | None = None
last_extraction_timestamp: float = 0.0
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' blob: data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    ),
}

app = FastAPI(
    title="ExtrAI",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


async def send_json(send: Send, status: int, detail: str) -> None:
    """Answer straight from a middleware, keeping the security headers."""

    body = json.dumps({"detail": detail}).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    headers.extend(
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in SECURITY_HEADERS.items()
    )
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _header(scope: Scope, name: bytes) -> bytes | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return value
    return None


class LoopbackOnlyMiddleware:
    """Serve only this machine, whatever address the server was told to bind."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        if not client or not is_loopback(client[0]):
            await send_json(send, 403, "Este piloto atende somente o computador local.")
            return

        host_header = _header(scope, b"host")
        if host_header is not None:
            host = urlsplit(b"//" + host_header).hostname
            host_str = host.decode("latin-1") if host else None
            if not is_loopback(host_str):
                await send_json(send, 403, "Host não permitido.")
                return

        origin = _header(scope, b"origin")
        if origin is not None:
            origin_str = origin.decode("latin-1")
            parsed = urlsplit(origin_str)
            is_ext = parsed.scheme in ("chrome-extension", "moz-extension")
            if not is_ext and not is_loopback(parsed.hostname):
                await send_json(send, 403, "Origem não permitida.")
                return

        await self.app(scope, receive, send)


class ConcurrencyLimit:
    """Bound how many extractions this single process keeps in flight."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.active = 0

    def full(self) -> bool:
        return self.active >= self.limit

    def __enter__(self) -> ConcurrencyLimit:
        self.active += 1
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.active -= 1


extractions = ConcurrencyLimit(MAX_CONCURRENT_EXTRACTIONS)


class RequestSizeLimitMiddleware:
    """Refuse an oversized body before the multipart parser spools it to disk."""

    def __init__(self, app: ASGIApp, max_body_bytes: int, detail: str) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.detail = detail

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if _declared_length(scope) > self.max_body_bytes:
            await self._refuse(send)
            return

        remaining = self.max_body_bytes
        refused = False

        async def guarded_receive() -> Message:
            nonlocal remaining, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] != "http.request":
                return message
            remaining -= len(message.get("body", b""))
            if remaining < 0:
                # Answer here: downstream never sees the rest of the body.
                refused = True
                await self._refuse(send)
                return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not refused:
                await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except Exception:
            if not refused:
                raise

    async def _refuse(self, send: Send) -> None:
        await send_json(send, 413, self.detail)


def _declared_length(scope: Scope) -> int:
    value = _header(scope, b"content-length")
    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    origin = request.headers.get("origin")
    is_ext = bool(
        origin
        and (origin.startswith("chrome-extension://") or origin.startswith("moz-extension://"))
    )
    if request.method == "OPTIONS" and is_ext:
        response = Response(status_code=204)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if is_ext:
        response.headers["Access-Control-Allow-Origin"] = origin
    return response


# Added last runs first: refuse foreign callers, then oversized bodies.
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_bytes=MAX_REQUEST_BYTES,
    detail=upload_limit_message(settings.max_upload_bytes),
)
app.add_middleware(LoopbackOnlyMiddleware)


STATIC_CACHE: dict[str, bytes] = {
    "index.html": static_index.read_bytes(),
    "app.css": (STATIC_DIR / "app.css").read_bytes(),
    "app.js": (STATIC_DIR / "app.js").read_bytes(),
    "logo.png": (STATIC_DIR / "logo.png").read_bytes(),
    "favicon.ico": (STATIC_DIR / "favicon.ico").read_bytes(),
}


@app.get("/favicon.ico")
async def favicon() -> Response:
    content = STATIC_CACHE.get("favicon.ico")
    if content is None:
        content = (STATIC_DIR / "favicon.ico").read_bytes()
    return Response(content=content, media_type="image/x-icon")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    content = STATIC_CACHE.get("index.html")
    if content is None:
        content = static_index.read_bytes()
    return HTMLResponse(content.decode("utf-8"))


@app.get("/static/{asset}")
async def static_asset(asset: str) -> Response:
    """Serve only the known assets, never an arbitrary path."""

    media_type = STATIC_ASSETS.get(asset)
    file_path = STATIC_FILES.get(asset)
    if media_type is None or file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    content = STATIC_CACHE.get(asset)
    if content is None:
        content = file_path.read_bytes()
    return Response(
        content=content,
        media_type=media_type,
    )


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "storage": "temporary-only",
        "model": settings.model,
        "providerConfigured": settings.provider_configured(),
        "fallbackModels": list(settings.configured_fallback_models()),
    }


async def _cleanup_extraction(document: UploadFile, tasks: list[asyncio.Task[object]]) -> None:
    """Drain children and close the upload even when the HTTP task is cancelled."""

    for task in tasks:
        if not task.done():
            task.cancel()

    async def cleanup() -> None:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await document.close()

    cleanup_task = asyncio.create_task(cleanup())
    cancellation: asyncio.CancelledError | None = None
    # Starlette uses AnyIO cancellation scopes; shield their repeated cancellation
    # as well as direct asyncio cancellation while the child cleanup finishes.
    with anyio.CancelScope(shield=True):
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError as error:
                cancellation = error
        cleanup_task.result()
    if cancellation is not None:
        raise cancellation


@app.post("/api/extract")
async def extract(request: Request, document: UploadFile = File(...)) -> dict[str, object]:
    if extractions.full():
        await _cleanup_extraction(document, [])
        raise HTTPException(
            status_code=429,
            detail="Há outra análise em andamento. Tente novamente em instantes.",
        )
    with extractions:
        tasks: list[asyncio.Task[object]] = []
        try:
            content = await document.read(settings.max_upload_bytes + 1)
            extract_task = asyncio.create_task(
                extractor.extract(
                    file_name=document.filename or "",
                    content=content,
                    content_type=document.content_type,
                )
            )
            tasks.append(extract_task)

            async def wait_disconnect() -> None:
                while True:
                    message = await request.receive()
                    if message.get("type") == "http.disconnect":
                        return

            disconnect_task = asyncio.create_task(wait_disconnect())
            tasks.append(disconnect_task)
            done, _ = await asyncio.wait(
                [extract_task, disconnect_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect_task in done:
                logger.info("document extraction aborted by client")
                raise HTTPException(
                    status_code=499,
                    detail="Análise cancelada pelo cliente.",
                )

            result = extract_task.result()
        except UploadValidationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ProviderNotConfiguredError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ProviderRateLimitError as error:
            logger.warning("provider rate limit: error_type=%s", type(error).__name__)
            raise HTTPException(status_code=429, detail=str(error)) from error
        except ProviderUnavailableError as error:
            logger.warning("provider unavailable: error_type=%s", type(error).__name__)
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ProviderConnectionError as error:
            logger.warning("provider connection failed: error_type=%s", type(error).__name__)
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ExtractionTimeoutError as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
        except HTTPException:
            raise
        except Exception as error:
            logger.error(
                "document extraction failed: error_type=%s",
                type(error).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail="Não foi possível processar o documento.",
            ) from None
        finally:
            await _cleanup_extraction(document, tasks)

    usage_info = result.get("usage") or {}
    logger.info(
        "document extraction completed: kind=%s pages=%s fields=%s duration_ms=%s "
        "tokens_in=%s tokens_out=%s model=%s",
        result["kind"],
        result["pages"],
        len(result["fields"]),
        result["durationMs"],
        usage_info.get("inputTokens", 0),
        usage_info.get("outputTokens", 0),
        result.get("modelUsed", settings.model),
    )
    global last_extraction_result, last_extraction_timestamp
    last_extraction_result = result
    last_extraction_timestamp = time.monotonic()
    return result


@app.get("/api/last-extraction")
async def get_last_extraction() -> dict:
    global last_extraction_result, last_extraction_timestamp
    if (
        last_extraction_result is not None
        and (time.monotonic() - last_extraction_timestamp) > LAST_EXTRACTION_TTL_SECONDS
    ):
        last_extraction_result = None
        last_extraction_timestamp = 0.0

    if last_extraction_result is None:
        return {"hasData": False, "data": None}
    return {"hasData": True, "data": last_extraction_result}


@app.delete("/api/last-extraction")
async def clear_last_extraction() -> dict:
    global last_extraction_result, last_extraction_timestamp
    last_extraction_result = None
    last_extraction_timestamp = 0.0
    return {"status": "cleared"}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "doc_extractor_pydantic.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
