# Architecture

## Scope

Local pilot for extracting RG and CNH data from images and PDFs. There is no
database, message queue, permanent storage, or automated submission to external
systems.

## Main Flow

```text
browser
  -> FastAPI /api/extract
  -> DocumentExtractor
  -> disposable local document worker (in-memory IPC, cancel/timeout)
  -> upload validation and bounded PDF/image preparation
  -> primary embedded image as support, when present
  -> PydanticAI Agent
  -> configured multimodal provider
  -> DocumentExtraction validated by Pydantic
  -> structured response for human review
```

## Layers

- `main.py`: HTTP runtime, health checks, and error mappings.
- `document_processing.py`: local upload validation, PDF metadata, bounded
  embedded-image preparation, and the disposable processing worker.
- `privacy_logging.py`: suppress dependency diagnostics that can expose document
  content before parsing.
- `extractor.py`: multimodal input, lazy model fallback, shared request budgets,
  and API contract. Upload/preview helpers are re-exported for compatibility.
- `provider_usage.py`: count calls at the model boundary and accumulate only usage
  metadata across retries and fallbacks.
- `models.py`: Pydantic models and semantic field validations.
- `prompts.py`: extraction instructions and rules preventing data hallucination.
- `static/index.html`, `static/app.css`, `static/app.js`: local interface, zoomed
  detail view, review, and copying. Split into three files so the CSP does not
  require `'unsafe-inline'`.
- `tests/`: tests running without external calls to the provider.

## Dependency Boundaries

- The frontend interface must not know provider details, prompts, or credentials.
- The model must not be treated as a source of truth without validation and review.
- The backend must not persist uploaded documents.
- Security and privacy rules must be mechanically enforceable by tests or checks
  whenever possible.
