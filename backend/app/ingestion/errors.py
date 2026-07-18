"""Typed ingestion failures.

Every failure is a typed terminal-or-retryable state (DOCUMENT_INGESTION_
ARCHITECTURE.md §11): a stable machine-readable ``code`` persisted on the
version row, a bounded user-safe ``user_message`` for the UI, and a
``retryable`` classification the worker uses against the attempts cap.
Internal tracebacks stay in server logs; neither field ever carries document
text or a stack trace.
"""

from __future__ import annotations

# Stable error codes (persisted in document_versions.error_code).
ERROR_INVALID_ENCODING = "invalid_encoding"
ERROR_EXTRACTION_TOO_LARGE = "extraction_too_large"
ERROR_PARSE_FAILED = "parse_failed"
ERROR_EMPTY_DOCUMENT = "empty_document"
ERROR_UNSUPPORTED_FORMAT = "unsupported_format"
ERROR_MISSING_BLOB = "missing_blob"
ERROR_INTERNAL = "ingestion_failed"
ERROR_STALE_ABANDONED = "stale_abandoned"

# M3 finalization failures (typed, per stage).
ERROR_ANCHORING_FAILED = "anchoring_failed"
ERROR_CLASSIFICATION_FAILED = "classification_failed"
ERROR_MODULE_INVALID = "module_invalid"
ERROR_CITATION_PREFIX_FAILED = "citation_prefix_failed"
# The queued job pins a complete finalization target this process cannot
# reproduce exactly (older/newer code, different module pack/config). Fail
# closed: never generate a different artifact than the one requested.
ERROR_UNSUPPORTED_TARGET = "unsupported_finalization_target"

_MAX_DETAIL_CHARS = 300


class IngestionError(Exception):
    """A classified ingestion failure. ``user_message`` must be safe to show
    to the uploading tenant; it is bounded and never includes document text."""

    def __init__(self, code: str, user_message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = (user_message or "")[:_MAX_DETAIL_CHARS]
        self.retryable = retryable
