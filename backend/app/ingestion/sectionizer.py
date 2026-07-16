"""Initial deterministic sectionization over ``DocIR v1`` (M2).

Groups the parser's block stream into sections: heading-aware, source-ordered,
split at block boundaries, with documented size bounds. No classification, no
claim extraction, no taxonomy reasoning, and — deliberately — none of the M3
anchor/citation identity algorithm.

Size bounds (documented M2 sectionizer behavior; SECTIONIZER_VERSION bumps if
any of them changes):

* ``MIN_SECTION_CHARS`` (200)  — a *split fragment* smaller than this merges
  back into the previous fragment. Authored short sections (a real heading
  with a short body) are kept as written: collapsing an author's structure
  would misrepresent the document.
* ``MAX_SECTION_CHARS`` (4000) — oversized sections split at block
  boundaries; a single oversized block splits at line, then sentence
  boundaries. Code blocks and tables are kept whole whenever the block itself
  fits, so they are never split mid-structure unless one block alone exceeds
  the bound.
* ``EXCERPT_CHARS`` (1200)     — the display excerpt is a *derivation* of the
  full text (cut at a sentence, then word boundary). Scoring metadata
  (``token_set``, ``char_count``) always derives from the full section text.

Transitional identity (recorded in DECISIONS.md, 2026-07-16): the M3 anchor
algorithm — heading-path hashing, inheritance, tie-breaking, golden fixtures —
is a frozen-forever surface this milestone must not pre-empt. But
``document_sections.anchor_id`` / ``citation_id`` are NOT NULL. M2 therefore
writes ordinal-based *internal* identifiers (``s0007`` / ``pre-m3:s0007``)
and stamps ``anchor_algo_version = "pre-m3-transitional"`` on the version.
These ids are never exposed through any API or UI and never reach a report
(generation cannot read tenant sections until M4, which depends on M3), so no
public citation identity is invented; M3 re-anchors these versions through
the same defined re-processing trigger as a parser upgrade.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.contracts import DocBlock, DocIR

SECTIONIZER_VERSION = "m2.1"
ANCHOR_ALGO_TRANSITIONAL = "pre-m3-transitional"

MIN_SECTION_CHARS = 200
MAX_SECTION_CHARS = 4000
EXCERPT_CHARS = 1200

_TITLE_CHARS = 60
_OMITTED_MARKER = "[content omitted:"

_TOKEN_RE = re.compile(r"[^a-z0-9\s]+")


def tokenize(text: str) -> List[str]:
    """Deterministic token set for precomputed scoring metadata: lowercase
    alphanumeric words of length >= 2, sorted, unique. A superset of what the
    M4 scorers filter (stop/generic-term policy stays theirs)."""
    words = _TOKEN_RE.sub(" ", text.lower()).split()
    return sorted({w for w in words if len(w) >= 2})


@dataclass
class SectionDraft:
    """One section ready for persistence (maps onto DocumentSection rows)."""

    ordinal: int
    anchor_id: str
    citation_id: str
    title: str
    heading_path: List[str]
    depth: int
    text: str
    excerpt: str
    text_sha256: str
    char_count: int
    token_set: List[str]
    has_tables: bool = False
    has_omitted_content: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _RawSection:
    title: str
    heading_path: List[str]
    depth: int
    blocks: List[DocBlock] = field(default_factory=list)
    synthesized_title: bool = False


def sectionize(doc: DocIR) -> List[SectionDraft]:
    """DocIR -> ordered SectionDrafts. Deterministic: identical DocIR always
    produces identical sections (ordering, ids, text, excerpts)."""
    raw_sections = _group_by_headings(doc.blocks)
    fragments: List[Tuple[_RawSection, str, Dict[str, Any]]] = []
    for raw in raw_sections:
        for text, meta in _bounded_fragments(raw.blocks):
            fragments.append((raw, text, meta))

    drafts: List[SectionDraft] = []
    for ordinal, (raw, text, meta) in enumerate(fragments):
        anchor = f"s{ordinal:04d}"
        blocks = meta.pop("_blocks", [])
        drafts.append(
            SectionDraft(
                ordinal=ordinal,
                anchor_id=anchor,
                citation_id=f"pre-m3:{anchor}",
                title=raw.title,
                heading_path=list(raw.heading_path),
                depth=raw.depth,
                text=text,
                excerpt=_derive_excerpt(text),
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                char_count=len(text),
                token_set=tokenize(f"{raw.title}\n{text}"),
                has_tables=any(b.kind == "table" for b in blocks),
                has_omitted_content=(
                    any(b.kind == "omitted" or b.meta.get("has_omitted") for b in blocks)
                    or _OMITTED_MARKER in text
                ),
                meta=meta,
            )
        )
    return drafts


def manifest_sha256(drafts: List[SectionDraft]) -> str:
    """Ordered (anchor, text hash) pairs -> one whole-version content hash."""
    payload = "\n".join(f"{d.anchor_id}:{d.text_sha256}" for d in drafts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# grouping
# --------------------------------------------------------------------------- #


def _group_by_headings(blocks: Tuple[DocBlock, ...]) -> List[_RawSection]:
    sections: List[_RawSection] = []
    # heading stack: (level, title) of the current ancestry
    stack: List[Tuple[int, str]] = []
    current: Optional[_RawSection] = None

    def close_current() -> None:
        nonlocal current
        if current is not None and current.blocks:
            sections.append(current)
        current = None

    for block in blocks:
        if block.kind == "heading":
            close_current()
            level = block.level or 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, block.text))
            current = _RawSection(
                title=block.text,
                heading_path=[title for _lvl, title in stack],
                depth=level,
            )
            continue

        if current is None:
            # preamble (or heading-less document): synthesize a title from the
            # section's own first content — derived, never invented.
            title = _derive_title(block.text)
            current = _RawSection(
                title=title, heading_path=[title], depth=1, synthesized_title=True
            )
        current.blocks.append(block)

    close_current()
    return sections


def _derive_title(text: str) -> str:
    first_line = text.split("\n", 1)[0].strip()
    sentence = re.split(r"(?<=[.!?])\s", first_line, maxsplit=1)[0].strip()
    if len(sentence) <= _TITLE_CHARS:
        return sentence or "Untitled section"
    cut = sentence[:_TITLE_CHARS]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.") or "Untitled section"


# --------------------------------------------------------------------------- #
# size bounds: split / merge
# --------------------------------------------------------------------------- #


def _bounded_fragments(blocks: List[DocBlock]) -> List[Tuple[str, Dict[str, Any]]]:
    """Pack a section's blocks into fragments of at most MAX_SECTION_CHARS,
    splitting only at block boundaries when possible. A trailing fragment
    smaller than MIN_SECTION_CHARS merges back into the previous one (it may
    then modestly exceed MAX — honest completeness beats a dangling scrap)."""
    pieces: List[Tuple[str, List[DocBlock]]] = []
    for block in blocks:
        if len(block.text) > MAX_SECTION_CHARS:
            for chunk in _split_oversized_text(block.text):
                pieces.append((chunk, [block]))
        else:
            pieces.append((block.text, [block]))

    fragments: List[Tuple[str, List[DocBlock]]] = []
    buf_text: List[str] = []
    buf_blocks: List[DocBlock] = []
    size = 0
    for text, piece_blocks in pieces:
        extra = len(text) + (2 if buf_text else 0)
        if buf_text and size + extra > MAX_SECTION_CHARS:
            fragments.append(("\n\n".join(buf_text), buf_blocks))
            buf_text, buf_blocks, size = [], [], 0
            extra = len(text)
        buf_text.append(text)
        buf_blocks = buf_blocks + piece_blocks
        size += extra
    if buf_text:
        fragments.append(("\n\n".join(buf_text), buf_blocks))

    # merge an undersized trailing split fragment into its predecessor
    if len(fragments) >= 2 and len(fragments[-1][0]) < MIN_SECTION_CHARS:
        prev_text, prev_blocks = fragments[-2]
        last_text, last_blocks = fragments[-1]
        fragments[-2] = (f"{prev_text}\n\n{last_text}", prev_blocks + last_blocks)
        fragments.pop()

    total = len(fragments)
    result: List[Tuple[str, Dict[str, Any]]] = []
    for index, (text, frag_blocks) in enumerate(fragments):
        meta: Dict[str, Any] = {"_blocks": frag_blocks}
        if total > 1:
            meta["split_part"] = index + 1
            meta["split_total"] = total
        result.append((text, meta))
    return result


def _split_oversized_text(text: str) -> List[str]:
    """Split one oversized block: at line boundaries first, then sentence
    boundaries, then (only as a last resort) a hard cut. Deterministic."""
    units: List[str] = []
    for line in text.split("\n"):
        if len(line) <= MAX_SECTION_CHARS:
            units.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        for sentence in sentences:
            while len(sentence) > MAX_SECTION_CHARS:
                units.append(sentence[:MAX_SECTION_CHARS])
                sentence = sentence[MAX_SECTION_CHARS:]
            units.append(sentence)

    chunks: List[str] = []
    buf: List[str] = []
    size = 0
    for unit in units:
        extra = len(unit) + (1 if buf else 0)
        if buf and size + extra > MAX_SECTION_CHARS:
            chunks.append("\n".join(buf))
            buf, size = [], 0
            extra = len(unit)
        buf.append(unit)
        size += extra
    if buf:
        chunks.append("\n".join(buf))
    return [c for c in chunks if c.strip()]


def _derive_excerpt(text: str) -> str:
    if len(text) <= EXCERPT_CHARS:
        return text
    window = text[:EXCERPT_CHARS]
    sentence_cut = max(window.rfind(". "), window.rfind(".\n"))
    if sentence_cut >= EXCERPT_CHARS // 3:
        return window[: sentence_cut + 1]
    if " " in window:
        return window[: window.rfind(" ")]
    return window
