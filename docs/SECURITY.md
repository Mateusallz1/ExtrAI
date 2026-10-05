# Security and Privacy

## Data Flow

The uploaded document is parsed by the backend and dispatched to the configured
multimodal provider. For PDFs containing embedded images, the primary image is
also transmitted as complementary context for the same extraction request. The
application does not maintain any persistent storage of its own; however, the
external AI provider operates under its own data retention and usage policies.

Never process real identification documents on public/free tiers without
reviewing provider terms and obtaining explicit operational authorization.

## Security Rules

- Never commit API keys to source code, Git history, test fixtures, or documentation.
- Never transmit original file names to the model; analyze binary content only.
- Never log extracted document contents, fields, images, PDFs, or file names (Zero PII).
- The `pypdf` logger is silenced prior to parsing, as upstream debug logs may leak
  document content tokens. This rule is verified by malformed synthetic PDF regressions.
- Enforce `Cache-Control: no-store` and protective security headers to prevent
  client-side caching or MIME sniffing in the browser.
- Keep CSS and JavaScript in dedicated static files: Content Security Policy (CSP)
  disallows `'unsafe-inline'` and enforces `frame-ancestors 'none'`. Never reintroduce
  inline `<style>`, `<script>`, or `style="..."` attributes in HTML.
- Serve strictly the explicit static assets declared in `STATIC_ASSETS`, never arbitrary
  filesystem paths from URL parameters.
- Explicitly close uploaded files upon request completion to release any temporary
  spool resources utilized by the multipart parser.
- Use `textContent` in the web frontend for any data rendered from model responses.
- Enforce human review prior to any operational downstream usage.
- Use synthetic documents only across all automated tests.
- Local parsing/decoding executes inside a disposable worker process. Communication
  occurs via in-memory IPC pipes carrying only extension and raw bytes; timeout or
  cancellation terminates the worker and closes the pipe before releasing concurrency slots.
- CSV export sanitizes spreadsheet formula injection prefixes (`=`, `+`, `-`, `@`, tab).
  This does not alter the original value displayed or exported in JSON.

## Endpoint Exposure & Boundary Controls

The project is designed exclusively for local machine operation and does not implement
user authentication. Two mechanical boundaries enforce this constraint:

- Any `HOST` value outside loopback halts startup in `Settings.from_env()`.
- `LoopbackOnlyMiddleware` responds with `403 Forbidden` whenever the client IP is not
  a loopback address (regardless of binding address), and whenever an incoming request
  carries a non-local `Origin` header.
- `ConcurrencyLimit` responds with `429 Too Many Requests` beyond two concurrent
  extractions to prevent token exhaustion bursts from local clients.

Before deploying to a shared network, additional safeguards are required: user
authentication, allowed host whitelisting, per-client rate limiting, and revised
concurrency control.

## Change Review Checklist

Before altering document flows, verify: byte destination, error messages and log outputs,
temporary spool files, size and page boundaries, secret handling, and safeguards against
adversarial document prompts attempting to override extraction rules.
