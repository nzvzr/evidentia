"""Deterministic shared text normalization (M2).

One normalization layer feeds both parsers so identical bytes always produce
identical extracted text:

* decode: UTF-8 only (an optional BOM is stripped). Anything that does not
  decode — or that carries NUL bytes, the giveaway of a binary payload with a
  text extension — fails with a stable typed code instead of a lossy
  ``errors="replace"`` decode that would hide major corruption.
* newlines: CRLF and lone CR become ``\n``.
* Unicode: NFC (the form the platform architecture picked for ingestion —
  DOCUMENT_INGESTION_ARCHITECTURE.md §1 step 4).
* control characters: stripped, except ``\n`` and ``\t`` (tabs are structure
  in plain text and inside Markdown code blocks).
* size: the extracted-character cap is enforced here, before any parsing —
  oversized input fails honestly (``extraction_too_large``), never silently
  truncated.

Whitespace *collapse* is deliberately not done here: paragraphs collapse their
internal runs, code blocks must stay verbatim, so that decision belongs to the
parsers/sectionizer which know the block kind. Nothing in this module invents,
summarizes, translates or executes content.
"""

from __future__ import annotations

import re
import unicodedata

from app.ingestion.errors import (
    ERROR_EXTRACTION_TOO_LARGE,
    ERROR_INVALID_ENCODING,
    IngestionError,
)

# Versioned with the ingestion engine: the normalization rules participate in
# M3 manifests/engine_versions, so a behavior change here must bump this.
NORMALIZER_VERSION = "m2.1"

_UTF8_BOM = b"\xef\xbb\xbf"

# Control characters except \t (0x09) and \n (0x0a); \r is gone before this
# runs. DEL (0x7f) and the C1 range are included.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")

# Collapse for prose text: runs of spaces/tabs become one space.
_INLINE_WS = re.compile(r"[ \t]+")


def decode_bytes(data: bytes) -> str:
    """UTF-8 decode with typed failure. NUL bytes are treated as binary
    content even when they happen to be valid UTF-8 (they never are in a real
    text document)."""
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM):]
    if b"\x00" in data:
        raise IngestionError(
            ERROR_INVALID_ENCODING,
            "The file is not valid UTF-8 text.",
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise IngestionError(
            ERROR_INVALID_ENCODING,
            "The file is not valid UTF-8 text. Save it as UTF-8 and upload again.",
        ) from None


def normalize_text(text: str, *, max_chars: int) -> str:
    """Deterministic document-level normalization (see module docstring)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS.sub("", text)
    if len(text) > max_chars:
        raise IngestionError(
            ERROR_EXTRACTION_TOO_LARGE,
            f"The document text exceeds the {max_chars:,}-character limit.",
        )
    return text


def decode_and_normalize(data: bytes, *, max_chars: int) -> str:
    return normalize_text(decode_bytes(data), max_chars=max_chars)


def collapse_inline_whitespace(text: str) -> str:
    """Collapse space/tab runs inside one line of prose. Never applied to code
    blocks (verbatim by contract) and never across newlines."""
    return _INLINE_WS.sub(" ", text).strip()
