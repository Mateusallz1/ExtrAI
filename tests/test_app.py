import asyncio
import json
import logging

from fastapi.testclient import TestClient

from doc_extractor_pydantic import main as main_module
from doc_extractor_pydantic.limits import MULTIPART_OVERHEAD_BYTES

app = main_module.app


def client(host: str = "127.0.0.1", **kwargs) -> TestClient:
    """The pilot only answers loopback, so every test states its address."""

    return TestClient(app, client=(host, 51234), **kwargs)


class SpyApp:
    """Minimal ASGI app that records whether the body ever reached it."""

    def __init__(self) -> None:
        self.body = b""

    async def __call__(self, scope, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            self.body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def drive(middleware, chunks: list[bytes], declared: int | None) -> tuple[int, bytes]:
    headers = [] if declared is None else [(b"content-length", str(declared).encode())]
    pending = list(chunks)
    sent: list[dict] = []

    async def receive():
        if not pending:
            return {"type": "http.disconnect"}
        chunk = pending.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        middleware({"type": "http", "method": "POST", "headers": headers}, receive, send)
    )
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def test_health_does_not_expose_credentials() -> None:
    response = client().get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "OPENAI_API_KEY" not in body
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_api_documentation_is_not_exposed() -> None:
    response = client().get("/api/docs")
    assert response.status_code == 404


def test_csp_forbids_inline_code_and_framing() -> None:
    policy = client().get("/").headers["content-security-policy"]

    assert "'unsafe-inline'" not in policy
    assert "script-src 'self';" in policy
    assert "style-src 'self';" in policy
    assert "frame-ancestors 'none';" in policy


def test_only_the_known_assets_are_served() -> None:
    css = client().get("/static/app.css")
    script = client().get("/static/app.js")
    logo = client().get("/static/logo.png")
    favicon_static = client().get("/static/favicon.ico")
    favicon_root = client().get("/favicon.ico")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert logo.status_code == 200
    assert logo.headers["content-type"].startswith("image/png")
    assert favicon_static.status_code == 200
    assert favicon_static.headers["content-type"].startswith("image/x-icon")
    assert favicon_root.status_code == 200
    assert favicon_root.headers["content-type"].startswith("image/x-icon")
    assert favicon_root.content == favicon_static.content
    assert client().get("/static/../main.py").status_code == 404
    assert client().get("/static/.env").status_code == 404


def test_request_limit_covers_the_upload_plus_the_multipart_envelope() -> None:
    assert main_module.MAX_REQUEST_BYTES == (
        main_module.settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    )
    limiter = next(
        item for item in app.user_middleware if item.cls is main_module.RequestSizeLimitMiddleware
    )
    assert limiter.kwargs["max_body_bytes"] == main_module.MAX_REQUEST_BYTES


def test_declared_oversized_body_is_refused_without_being_read() -> None:
    spy = SpyApp()
    middleware = main_module.RequestSizeLimitMiddleware(spy, max_body_bytes=16, detail="grande")

    status, body = drive(middleware, [b"x" * 64], declared=64)

    assert status == 413
    assert json.loads(body) == {"detail": "grande"}
    assert spy.body == b""


def test_streamed_body_is_cut_at_the_limit() -> None:
    spy = SpyApp()
    middleware = main_module.RequestSizeLimitMiddleware(spy, max_body_bytes=16, detail="grande")

    status, body = drive(middleware, [b"x" * 10, b"x" * 10, b"x" * 10], declared=None)

    assert status == 413
    assert json.loads(body) == {"detail": "grande"}
    assert len(spy.body) <= 16


def test_body_within_the_limit_reaches_the_application() -> None:
    spy = SpyApp()
    middleware = main_module.RequestSizeLimitMiddleware(spy, max_body_bytes=16, detail="grande")

    status, _ = drive(middleware, [b"x" * 8, b"x" * 8], declared=16)

    assert status == 200
    assert spy.body == b"x" * 16


def test_refusal_keeps_the_security_headers() -> None:
    middleware = main_module.RequestSizeLimitMiddleware(SpyApp(), max_body_bytes=1, detail="grande")
    sent: list[dict] = []

    async def send(message) -> None:
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"xx", "more_body": False}

    asyncio.run(middleware({"type": "http", "method": "POST", "headers": []}, receive, send))
    headers = dict(sent[0]["headers"])
    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_refuses_a_caller_from_the_network() -> None:
    response = client(host="192.168.0.10").get("/api/health")

    assert response.status_code == 403
    assert response.json()["detail"] == "Este piloto atende somente o computador local."
    assert response.headers["cache-control"] == "no-store"


def test_refuses_a_request_from_another_origin() -> None:
    response = client().post(
        "/api/extract",
        headers={"origin": "https://evil.example"},
        files={"document": ("test.png", b"\x89PNG\r\n\x1a\nx", "image/png")},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Origem não permitida."


def test_refuses_a_request_with_foreign_host() -> None:
    response = client().get(
        "/api/health",
        headers={"host": "evil.example:8788"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Host não permitido."


def test_accepts_the_local_page_as_origin(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "extractor", FakeExtractor())

    response = client().post(
        "/api/extract",
        headers={"origin": "http://127.0.0.1:8788"},
        files={"document": ("test.png", b"\x89PNG\r\n\x1a\nx", "image/png")},
    )

    assert response.status_code == 200


def test_refuses_a_new_extraction_while_the_limit_is_busy(monkeypatch) -> None:
    fake = FakeExtractor()
    monkeypatch.setattr(main_module, "extractor", fake)
    monkeypatch.setattr(main_module.extractions, "active", main_module.extractions.limit)

    response = client().post(
        "/api/extract",
        files={"document": ("test.png", b"\x89PNG\r\n\x1a\nx", "image/png")},
    )

    assert response.status_code == 429
    assert "outra análise em andamento" in response.json()["detail"]
    assert fake.calls == []


def test_concurrency_limit_releases_every_slot() -> None:
    limit = main_module.ConcurrencyLimit(1)
    assert not limit.full()
    with limit:
        assert limit.full()
    assert limit.active == 0


def test_rejects_unsupported_upload_before_provider_call() -> None:
    response = client().post(
        "/api/extract",
        files={"document": ("malware.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Formato não suportado" in response.json()["detail"]


def test_rejects_malformed_pdf_before_provider_call() -> None:
    response = client().post(
        "/api/extract",
        files={"document": ("document.pdf", b"%PDF-1.7\nnot-a-complete-pdf", "application/pdf")},
    )
    assert response.status_code == 400
    assert "PDF válido" in response.json()["detail"]


class FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str | None]] = []

    async def extract(self, file_name: str, content: bytes, content_type: str | None) -> dict:
        self.calls.append((file_name, content, content_type))
        return {
            "kind": "cnh",
            "pages": 1,
            "fields": {
                "name": {
                    "value": "MARIA DE TESTE",
                    "confidence": "high",
                    "label": "Nome",
                }
            },
            "text": "DOCUMENTO: CNH\nNome: MARIA DE TESTE",
            "warnings": [],
            "durationMs": 12,
        }


def test_returns_extraction_result_without_calling_a_real_provider(monkeypatch) -> None:
    fake = FakeExtractor()
    monkeypatch.setattr(main_module, "extractor", fake)
    content = b"\x89PNG\r\n\x1a\nsynthetic"

    response = client().post(
        "/api/extract",
        files={"document": ("test.png", content, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["fields"]["name"]["value"] == "MARIA DE TESTE"
    assert fake.calls == [("test.png", content, "image/png")]


def test_provider_error_does_not_write_exception_details_to_logs(monkeypatch, caplog) -> None:
    class FailingExtractor:
        async def extract(self, file_name: str, content: bytes, content_type: str | None) -> dict:
            raise RuntimeError("private document value must not be logged")

    monkeypatch.setattr(main_module, "extractor", FailingExtractor())
    content = b"\x89PNG\r\n\x1a\nsynthetic"

    with caplog.at_level(logging.INFO):
        response = client().post(
            "/api/extract",
            files={"document": ("test.png", content, "image/png")},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Não foi possível processar o documento."
    assert "private document value" not in caplog.text


def test_provider_unavailable_is_returned_as_retryable_503(monkeypatch) -> None:
    class UnavailableExtractor:
        async def extract(self, file_name: str, content: bytes, content_type: str | None) -> dict:
            raise main_module.ProviderUnavailableError("provider indisponível")

    monkeypatch.setattr(main_module, "extractor", UnavailableExtractor())
    response = client().post(
        "/api/extract",
        files={"document": ("test.png", b"\x89PNG\r\n\x1a\nsynthetic", "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "provider indisponível"


def test_app_title_is_doclume() -> None:
    assert main_module.app.title == "DocLume"
