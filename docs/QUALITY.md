# Quality

## Required Gates

```powershell
uv run pytest
uv run ruff check src tests
uv run python -m compileall -q src tests
uv lock --check
uv pip check
node --check src/doc_extractor_pydantic/static/app.js
```

The harness consistency check is run with:

```powershell
uv run python scripts/check_harness.py
```

Browser tests require Playwright's Chromium binary (installed once):

```powershell
uv run playwright install chromium
```

Without it, `tests/test_frontend_dom.py` fails rather than passing silently.

## Acceptance Criteria

- Invalid uploads are rejected before reaching the provider.
- Images must be readable, static, and within pixel boundaries before loading data. A valid signature alone is not sufficient.
- Request bodies exceeding limits are rejected with 413 before the multipart body is processed.
- PDFs must be readable and contain between 1 and the maximum page limit.
- The PDF is opened only once per request.
- No image is decoded or encoded in base64 before the final crop.
- Previews only inspect selected XObjects: inline images are not decoded as side effects. A limit of 4 attempts is enforced.
- The PDF content stream is parsed incrementally up to the operation limit, without materializing the whole list up front.
- Local processing runs inside a cancellable worker process and does not block the event loop during parsing/decoding. Timeout or cancellation terminates the child.
- Parser logs must not leak private markers from malformed synthetic PDFs.
- Invalid outputs are removed and accompanied by warnings, including when a field does not belong to the identified document kind.
- Warnings pertaining exclusively to fields that the identified document kind does not possess are discarded. Mixed warnings preserve information on applicable fields.
- The interface never mixes results across different files.
- Extraction begins automatically when a valid file is selected, dropped, or pasted. The main action button adapts between submit/retry and "Clear analysis" when results are visible, supporting resubmission via Ctrl+Enter.
- When embedded images exist, the primary front page appears in zoomable detail, and other elements appear as thumbnails.
- Clipboard copy works or presents clear manual instructions.
- Incomplete CPF/dates are flagged upon ending input editing. Manual export remains permitted with explicit inconsistency warnings.
- CSV exports sanitize formula injection prefixes, even after whitespace/control characters.
- Images fit entirely within the initial zoom viewport, and warnings remain scrollable on narrow viewports.
- Transient model failure or latency degradation triggers automatic fallback to configured models.
- Each model is allowed up to 3 invocations, shared across output and transport retries. Usage includes previous responses and fallback; backup models are instantiated lazily on demand.
- Cancelling the HTTP task terminates and awaits child processes before releasing concurrency slots; read failure/cancellation also closes the upload.
- Automated tests make no live calls to Gemini or any remote provider.

## Current Testing Scope and Limitations

- There are no automated accuracy benchmarks against real documents.
- Provider tests are isolated with mock agents and local configurations.
- `node` validation is strictly syntactic. Runtime behavior is verified by `tests/test_frontend_dom.py` and `tests/test_frontend_extension.py`, running headless Chromium against mocked routes.
- `tests/test_frontend.py` verifies HTML fragments as a fast safety net, not behavioral proof.
- There is no automated visual regression testing; layout, color, and spacing are verified locally in the browser.
- Automatic zooming to field-specific bounding boxes is not part of the current viewer.
