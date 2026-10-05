# Reliability

## Expected Operation

- Local host: `127.0.0.1`.
- Default port: `8788`.
- Configuration: `.env` loaded via the Uvicorn command.
- Inputs: PDF, JPG, JPEG, PNG, and WebP up to 15 MB; static, readable images.
- Outcome: always subject to human review.

## Resource & Consumption Limits

Limits are defined in `limits.py`. File size and pixel dimensions are validated before pixel reading; parsing and decoding execute in a disposable worker process with its own timeout.

| Limit | Value | Enforcement Point |
| --- | --- | --- |
| Request body | upload + 64 KB envelope | ASGI middleware, prior to multipart parser |
| Upload size | `MAX_UPLOAD_BYTES` (15 MB) | `validate_upload` |
| PDF page count | 20 | `validate_upload` |
| Preview scanned pages | 4 | Embedded image scanner |
| Detail candidates | 24 | Embedded image scanner |
| Pixels per embedded image | 40 MP | Read from declared `/Width` and `/Height` |
| Pixels per uploaded image | 40 MP | Before Pillow verification/loading |
| Content stream per page | 8 MB uncompressed | Prior to interpreting PDF operators |
| Content stream operations | 10,000 | Incremental parser, prior to next operator |
| Preview decoding attempts | 4 | Bounded prior to base64 encode |
| Concurrent extractions | 2 | `/api/extract`, returns `429` beyond this |
| Local document processing | 15 s | Disposable process, killed on timeout/cancel |
| End-to-end analysis timeout | 42 s | Covers local processing & provider retries, returns `504` |
| Latency before fallback | 18 s | Failover to next model if reserve available |
| Model invocations | 3 per model | Shared budget for internal/external retries |

The PDF is opened exactly once per request: `validate_upload` returns the validated `PdfReader`, reused throughout the pipeline.

Detail candidate selection uses metadata declared in the PDF. Up to four candidates are attempted, including decoding failures; only selected XObjects and their masks are decoded. Inline images are not loaded through page enumeration. An XObject drawn multiple times on the same page is deduplicated into a single detail view. Actual JPEG/JPX and mask dimensions are strictly bounded.

The original file name remains within the HTTP process solely for extension validation; the worker receives only the extension and binary content, creating no document files. The multipart parser may use temporary spool files, which are closed immediately upon request completion.

`usage.requests` counts model invocations against the budget, including failures. Reported tokens aggregate only the consumption returned in successful responses, including invalid outputs and fallbacks; token usage is not estimated for unmetered failures. The three-invocation budget applies per model: configured fallback models receive their own budget while remaining bounded by the global timeout.

## Critical Dependencies

1. The FastAPI server must be running.
2. The configured provider must accept multimodal input and have valid credentials.
3. Outbound internet connectivity must be available for remote providers.
4. Provider outputs must adhere to the `DocumentExtraction` schema.

## Known Failure Modes

- Transient failures or latency degradation in the primary model automatically trigger fallback models configured in `PYDANTIC_AI_FALLBACK_MODELS` (default: `google:gemini-3-flash-preview`), ensuring resilience without manual intervention.
- If all models fail, the endpoint returns HTTP 503 after exhausted retries; quota or rate limits return HTTP 429. Non-transient errors (such as invalid credentials) do not trigger fallback. A slow provider triggers HTTP 504 when the local 42s budget expires; the call is cancelled, but tokens consumed upstream cannot be recovered.
- The project has no client authentication or per-client rate limiting: requests beyond 2 concurrent extractions receive HTTP 429 without queueing or automatic retries. See [SECURITY.md](SECURITY.md).
- A single compressed stream may expand up to `pypdf`'s safety ceiling (75 MB) during decompression before the 8 MB per-page limit drops it.
- Fallback models are instantiated lazily; unsupported providers or unauthenticated models are pruned. A fallback instantiation failure does not mask the primary error or prevent a healthy primary from running.
- Output validation retries and transport retries share 3 invocations per model. The budget does not reset across `agent.run()`.
- OpenAI SDK internal retries are disabled; backoff and budget control remain application-managed for both Chat and Responses APIs.
- Embedded image extraction is a preview enhancement: if it fails, PDF analysis proceeds, and the UI notifies that no enlarged detail is available.
- Free-tier provider usage is subject to latency spikes and upstream data retention policies.
- The disposable process bounds CPU time and isolates crashes, but does not enforce an OS-level memory ceiling. Process spawning and IPC cleanup run on threads; if the OS is slow to spawn the child, cleanup awaits process registration before termination, keeping the event loop responsive.
- Incremental parsing and XObject decoding rely on internal `pypdf` helpers. Upgrading `pypdf` requires re-running preparation regression tests.
- Animated images and mask chains with more than 4 images are rejected or omitted from previews, as they fall outside the static ID document scope.

These limits must be addressed before multi-tenant or production deployment.
