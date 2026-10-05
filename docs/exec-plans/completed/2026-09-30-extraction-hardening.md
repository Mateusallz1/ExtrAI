# Privacy, Reliability, and Verification Hardening

## Goal and Scope

Fix the regression scenarios reproduced during review of commit `5841ea8`: parser
logs leaking document content, incomplete PDF limits, retry budget accounting,
HTTP task cancellation leaks, premature fallback instantiation, dropped mixed
warnings, incomplete manual validation, formula-interpretable CSV exports, and
document/warning clipping in the UI. Also reject structurally invalid images.

Maintain API contracts, default model and minimal thinking level, loopback on
port 8788, human review invariants, and zero document persistence.

Does not include new providers, real documents, UI migration, production
authentication, commit, push, merge, or deployment.

## Milestones

1. Register plan and work on local branch `fix/extraction-hardening`.
2. Apply backend fixes and synthetic regression tests.
3. Apply UI fixes and behavioral tests in Chromium.
4. Update domain documentation with final decisions and operational limits.
5. Execute harness and all quality gates; review diff, staged, untracked, and ignored files.
6. Move this plan to `completed/` upon meeting all completion criteria.

## Decisions and Risks

- Logging controls must encompass PDF dependencies without recording messages
  or values derived from file content.
- A coroutine timeout does not interrupt synchronous parsing/decoding. Local work
  is isolated in a cancellable worker process with memory-only IPC.
- Resource limits must enforce bounds before expensive parsing/decoding and count
  attempts, not only successful previews.
- Internal and external retries must share an invocation budget; reported usage
  accumulates executions without claiming strict equivalence to provider billing.
- Budget enforcement applies at `Model.request`. OpenAI SDK internal retries are
  disabled to prevent multiplying HTTP requests under the hood.
- Worker spawning and IPC cleanup run on threads. Cleanup awaits process registration
  by the OS before terminating the child, keeping the event loop responsive.
- There is no hard OS memory ceiling. Stream limits apply after decompression;
  document CPU consumption is isolated in the cancellable worker.
- Manual editing remains allowed: incomplete values are flagged upon finishing
  edits; CSV exports are not silent when inconsistencies exist.
- Code review does not authorize live provider calls or secret reads.

## Validation and Completion Criteria

Use synthetic documents and mocked responses only. Exercise malformed PDF logs,
bounded parsing/decoding, image readability, local timeout/cancellation, HTTP
cleanup, retries/accumulated usage/fallback, mixed warnings, and UI workflows.

Run `uv run python scripts/check_harness.py`, pytest, Ruff, compileall,
`uv lock --check`, `uv pip check`, and frontend `node --check`. Do not install
or upgrade dependencies unnecessarily; use local environments and caches.

Completion requires all quality gates passing, diff review, and documented
residual risks. External Git decisions remain separate.

## Results and Final Validation

- Completed on branch `fix/extraction-hardening`, based on `5841ea8`.
- All nine review scenarios and image readability validations were resolved,
  preserving the HTTP contract and pilot invariants.
- Full test suite passed: **203 tests in 16.84 seconds**, covering worker processes,
  asyncio/AnyIO cancellation, simulated HTTP transports, and headless Chromium.
- Harness, Ruff, compileall, lockfile checks, dependency checks, JavaScript syntax,
  and whitespace reviews passed cleanly. No dependencies were installed or modified.
- Diff, staged, untracked, and ignored files were reviewed. Staging was clean; new
  files belong strictly to implementation/plan/tests; caches remain ignored.
- Independent diff review revealed no material defects.
- Zero real providers or real documents were accessed. No commit, push, merge,
  or deployment was executed; decisions remain distinct.
- Initial suite revealed Playwright synchronous event loop interference with new
  provider tests. These tests now run in their own thread event loop; cohabitation
  between browser and provider tests was validated.

## Residual Risks

- Decompression may reach `pypdf`'s internal safety ceiling before the 8 MB page
  cutoff; no OS hard memory ceiling exists. The disposable worker bounds CPU and time.
- Process spawning by the OS is non-preemptible; cleanup awaits process spawn
  completion on a thread before terminating, preserving event loop responsiveness.
- Internal `pypdf` helpers require existing regression coverage across lock updates.
- Tokens unavailable in error responses are not estimated. Real-world accuracy,
  availability, and latency of external providers were not measured in this change.
