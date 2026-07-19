"""Document-safety helpers (Phase 5).

Every field of a persisted report and every citation excerpt is **untrusted
text**: it originated in a tenant-uploaded document or an LLM narrative. The
renderer must place that text into a Word document without letting it corrupt
the XML, escape into a relationship/field, inflate the output without bound, or
poison a filename.

The contract is narrow on purpose: sanitize **only** for DOCX/XML validity and
bounded size. Legitimate content is never silently reworded — the sole
transformation applied to visible prose is the removal of characters that are
illegal in XML 1.0 and the enforcement of explicit length caps. python-docx does
its own XML *escaping* (``&``, ``<``, ``>`` become entities); what it does not do
is strip codepoints that no XML 1.0 document may contain at all, which is what
:func:`clean_text` handles.
"""

from __future__ import annotations

import re
import unicodedata

# Codepoints permitted in an XML 1.0 document (XML spec §2.2 Char production):
#   #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
# Everything else (control chars, lone surrogates, #xFFFE/#xFFFF, ...) is illegal
# even when escaped, and python-docx will happily write it and produce a file
# Word refuses to open. We strip exactly those.
_ILLEGAL_XML = re.compile(
    "["
    "\x00-\x08"
    "\x0b\x0c"
    "\x0e-\x1f"
    "\ud800-\udfff"
    "￾￿"
    "]"
)

# A hard ceiling on any single text run placed in the document. No legitimate
# report field or bounded excerpt approaches this; it is a guard against a
# pathological field ballooning the part stream. Applied per field, after which
# the whole-document budget in the renderer still applies.
MAX_FIELD_CHARS = 20_000

# Filenames are built from a slug of tenant-supplied display text, so they are
# reduced to a conservative, path-safe alphabet and bounded length.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
MAX_SLUG_CHARS = 48
MAX_FILENAME_STEM = 96


def clean_text(value: object, *, limit: int = MAX_FIELD_CHARS) -> str:
    """Return ``value`` as XML-safe, length-bounded text.

    - Non-strings are coerced via ``str`` (numbers, ``None`` → ``"None"`` is
      avoided by callers, which pass ``""`` for absent values).
    - Illegal XML codepoints are removed.
    - The result is truncated to ``limit`` characters with an ellipsis so an
      unbounded field cannot inflate the document.

    No other change is made — casing, punctuation and wording are preserved.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    # Normalize to NFC so combining sequences are compact and stable, then drop
    # codepoints XML forbids outright.
    text = unicodedata.normalize("NFC", text)
    text = _ILLEGAL_XML.sub("", text)
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def clean_multiline(value: object, *, limit: int = MAX_FIELD_CHARS) -> str:
    """Like :func:`clean_text` but preserves newlines (used for excerpts)."""
    return clean_text(value, limit=limit)


def slugify(value: object, *, fallback: str = "report") -> str:
    """A conservative, path-safe slug: lowercase ``[a-z0-9-]``, bounded length.

    This is never used as a path — it is only a *stem* embedded in a fixed
    filename template — but it is defended as if it were: no separators, no dots,
    no traversal sequences can survive.
    """
    text = "" if value is None else (value if isinstance(value, str) else str(value))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    if len(text) > MAX_SLUG_CHARS:
        text = text[:MAX_SLUG_CHARS].strip("-")
    return text or fallback


def safe_short_id(value: object, *, length: int = 8) -> str:
    """A short, path-safe id fragment for the filename.

    Report ids are server-minted UUIDs, but a legacy/migrated id could be
    anything, so it is reduced to ``[a-z0-9]`` and bounded. Never trusted as a
    path component.
    """
    text = "" if value is None else str(value)
    text = re.sub(r"[^a-zA-Z0-9]+", "", text).lower()
    return text[:length] or "report"


def safe_filename(persona: object, market: object, report_id: object, *, extension: str = "docx") -> str:
    """Build a deterministic, path-safe download filename.

    Shape: ``evidentia-<persona-slug>-<market-slug>-<shortid>.docx``. Every
    component is slugified; a hostile persona/market/title cannot introduce a
    path separator, a parent-directory hop, or a second extension.
    """
    persona_slug = slugify(persona, fallback="report")
    market_slug = slugify(market, fallback="all")
    short = safe_short_id(report_id)
    stem = f"evidentia-{persona_slug}-{market_slug}-{short}"
    if len(stem) > MAX_FILENAME_STEM:
        stem = stem[:MAX_FILENAME_STEM].strip("-")
    ext = _SLUG_STRIP.sub("", extension.lower()) or "docx"
    return f"{stem}.{ext}"
