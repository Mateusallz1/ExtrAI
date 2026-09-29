"""Local operational limits applied before expensive processing on documents."""

from __future__ import annotations

MULTIPART_OVERHEAD_BYTES = 64 * 1024
"""Allowance for multipart envelope surrounding uploaded file."""

MAX_PDF_PAGES = 20
"""Maximum allowed pages in an ID/driver license PDF."""

MAX_PREVIEW_IMAGES = 4
"""Maximum preview details displayed in the interface."""

MAX_PREVIEW_SCAN_PAGES = 4
"""Pages scanned when searching for embedded images."""

MAX_PREVIEW_CANDIDATES = 24
"""Candidate images collected before sorting and trimming."""

MAX_PREVIEW_PIXELS = 40_000_000
"""Maximum allowed pixels in an embedded image, checked without decompression."""

MAX_CONTENT_STREAM_BYTES = 8 * 1024 * 1024
"""Maximum decompressed bytes accepted in a single page content stream."""

MIN_PREVIEW_SIDE = 200
"""Minimum pixel dimension for an image to become a focus detail."""

MAX_STREAM_OPERATIONS = 10_000
"""Limit on stream operators scanned per page to prevent CPU starvation."""

MAX_CONCURRENT_EXTRACTIONS = 2
"""Maximum concurrent extraction requests handled by this server process."""

EXTRACTION_TIMEOUT_SECONDS = 90.0
"""Total time budget allowed for provider responses, including retries."""

MODEL_TIMEOUT_SECONDS = 45.0
"""Time budget allowed for a single model attempt before failing over to a fallback model."""

PROVIDER_RETRIES = 2
"""Additional attempts for invalid structured output or transient provider failure."""

PROVIDER_BACKOFF_SECONDS = 2.0
"""Initial exponential backoff delay before retrying transient provider failures."""


def upload_limit_message(max_upload_bytes: int) -> str:
    return f"O arquivo excede o limite local de {max_upload_bytes / (1024 * 1024):g} MB."
