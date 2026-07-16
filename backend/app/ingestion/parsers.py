"""Format parsers (M2): Markdown and plain text -> ``DocIR v1``.

Parsers are the only format-aware code in the platform (L2). Input is
*normalized* text (see ``normalize.py``); output is the typed ``DocIR``
contract from ``app/contracts.py`` — an ordered block stream with heading
hierarchy. Everything downstream (sectionizer now, anchors/classification in
M3) consumes DocIR and never sees a format again.

Security posture (M2 contract):

* No HTML/JavaScript execution — Markdown is parsed with ``html=False``
  (markdown-it-py "js-default"), so raw HTML stays literal authored text and
  is later rendered escaped, never trusted.
* No remote fetches of any kind: images and links contribute only their
  authored alt/text; an image becomes an explicit omitted-content marker
  (``[content omitted: image "alt"]``) — content is never invented for it.
* Unsupported formats fail with the stable ``unsupported_format`` code.

Determinism: identical normalized text always yields an identical block
stream. Parser name/version are recorded per document version so a parser
upgrade has a defined re-ingestion trigger.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.contracts import DocBlock, DocIR
from app.ingestion.errors import ERROR_UNSUPPORTED_FORMAT, IngestionError
from app.ingestion.normalize import collapse_inline_whitespace

# Source formats supported in M2. PDF/DOCX/HTML/OCR/XLSX/PPTX are later
# milestones (M6/M7); they are new parsers behind this same interface.
FORMAT_MARKDOWN = "markdown"
FORMAT_TEXT = "text"
SUPPORTED_FORMATS = frozenset({FORMAT_MARKDOWN, FORMAT_TEXT})


def omitted_marker(kind: str, label: str) -> str:
    """The honest inline stand-in for content extraction cannot represent."""
    label = collapse_inline_whitespace(label or "")
    return f'[content omitted: {kind} "{label}"]' if label else f"[content omitted: {kind}]"


class DocumentParser(Protocol):
    """Typed parser seam: normalized text in, DocIR v1 out."""

    name: str
    version: str

    def parse(self, text: str) -> DocIR:  # pragma: no cover - protocol
        ...


def get_parser(source_format: str) -> DocumentParser:
    if source_format == FORMAT_MARKDOWN:
        return MarkdownParser()
    if source_format == FORMAT_TEXT:
        return PlainTextParser()
    raise IngestionError(
        ERROR_UNSUPPORTED_FORMAT,
        f"Unsupported document format {source_format!r}. Supported: Markdown (.md) and plain text (.txt).",
    )


# --------------------------------------------------------------------------- #
# Markdown (markdown-it-py, CommonMark + tables, html disabled)
# --------------------------------------------------------------------------- #


class MarkdownParser:
    """CommonMark parsing via markdown-it-py's token stream.

    Supported structure: heading levels 1–6 with hierarchy, paragraphs,
    ordered/unordered/nested lists, block quotes, fenced and indented code
    blocks (kept verbatim as paragraph blocks with ``meta.code``), tables
    (flattened to pipe-text), images (omitted-content markers preserving alt
    text), links (authored text kept; hrefs preserved as safe meta).
    Horizontal rules carry no text and are dropped (they already terminate the
    enclosing block). Raw HTML is never executed: with ``html=False`` it stays
    literal text in the block stream.
    """

    name = "markdown-it-py"
    version = "m2.1"

    def __init__(self) -> None:
        # "js-default": CommonMark + table/strikethrough, html=False (raw HTML
        # stays text), no linkification, no plugins.
        self._md = MarkdownIt("js-default")

    def parse(self, text: str) -> DocIR:
        tokens = self._md.parse(text)
        blocks: List[DocBlock] = []
        i = 0
        while i < len(tokens):
            i = self._consume(tokens, i, blocks, blockquote_depth=0)
        return DocIR(blocks=tuple(blocks))

    # -- token walkers ------------------------------------------------------ #

    def _consume(
        self, tokens: Sequence[Token], i: int, blocks: List[DocBlock], *, blockquote_depth: int
    ) -> int:
        token = tokens[i]

        if token.type == "heading_open":
            level = int(token.tag[1])  # "h1".."h6"
            inline = tokens[i + 1]
            text, inline_meta = self._flatten_inline(inline)
            meta = self._base_meta(token, inline_meta, blockquote_depth)
            if text or inline_meta.get("has_omitted"):
                blocks.append(DocBlock(kind="heading", level=level, text=text, meta=meta))
            return i + 3  # open, inline, close

        if token.type == "paragraph_open":
            inline = tokens[i + 1]
            text, inline_meta = self._flatten_inline(inline)
            meta = self._base_meta(token, inline_meta, blockquote_depth)
            if inline_meta.get("has_omitted") and not inline_meta.get("has_text"):
                # e.g. a paragraph that is only an image
                blocks.append(DocBlock(kind="omitted", text=text, meta=meta))
            elif text:
                blocks.append(DocBlock(kind="paragraph", text=text, meta=meta))
            return i + 3

        if token.type in ("fence", "code_block"):
            meta = self._base_meta(token, {}, blockquote_depth)
            meta["code"] = True
            if token.type == "fence" and token.info:
                meta["code_info"] = collapse_inline_whitespace(token.info)[:40]
            body = token.content.rstrip("\n")
            if body.strip():
                blocks.append(DocBlock(kind="paragraph", text=body, meta=meta))
            return i + 1

        if token.type in ("bullet_list_open", "ordered_list_open"):
            end = self._matching_close(tokens, i)
            lines: List[str] = []
            omitted = self._flatten_list(tokens, i, end, depth=0, lines=lines)
            meta = self._base_meta(token, {}, blockquote_depth)
            meta["ordered"] = token.type == "ordered_list_open"
            if omitted:
                meta["has_omitted"] = True
            if lines:
                blocks.append(DocBlock(kind="list", text="\n".join(lines), meta=meta))
            return end + 1

        if token.type == "blockquote_open":
            end = self._matching_close(tokens, i)
            j = i + 1
            while j < end:
                j = self._consume(tokens, j, blocks, blockquote_depth=blockquote_depth + 1)
            return end + 1

        if token.type == "table_open":
            end = self._matching_close(tokens, i)
            text = self._flatten_table(tokens, i, end)
            meta = self._base_meta(token, {}, blockquote_depth)
            if text:
                blocks.append(DocBlock(kind="table", text=text, meta=meta))
            return end + 1

        # hr carries no authored text; html_block cannot occur with html=False.
        return i + 1

    @staticmethod
    def _matching_close(tokens: Sequence[Token], i: int) -> int:
        depth = 0
        for j in range(i, len(tokens)):
            if tokens[j].type.endswith("_open"):
                depth += 1
            elif tokens[j].type.endswith("_close"):
                depth -= 1
                if depth == 0:
                    return j
        return len(tokens) - 1

    @staticmethod
    def _base_meta(
        token: Token, inline_meta: Dict[str, Any], blockquote_depth: int
    ) -> Dict[str, Any]:
        meta: Dict[str, Any] = {}
        if token.map:
            meta["line_start"], meta["line_end"] = int(token.map[0]), int(token.map[1])
        if blockquote_depth:
            meta["blockquote"] = blockquote_depth
        if inline_meta.get("has_omitted"):
            meta["has_omitted"] = True
        if inline_meta.get("links"):
            meta["links"] = inline_meta["links"]
        return meta

    def _flatten_inline(self, inline: Token) -> Tuple[str, Dict[str, Any]]:
        """Inline children -> plain authored text. Images become omitted
        markers; link/emphasis markup contributes only its text content."""
        parts: List[str] = []
        links: List[str] = []
        has_omitted = False
        has_text = False

        def walk(children: Optional[Sequence[Token]]) -> None:
            nonlocal has_omitted, has_text
            for child in children or []:
                if child.type in ("text", "code_inline"):
                    if child.content.strip():
                        has_text = True
                    parts.append(child.content)
                elif child.type in ("softbreak", "hardbreak"):
                    parts.append(" ")
                elif child.type == "image":
                    # The marker carries the alt text; do NOT also descend into
                    # the image's children (they hold the same alt as text).
                    alt = child.content or str(child.attrs.get("alt", "") or "")
                    parts.append(omitted_marker("image", alt))
                    has_omitted = True
                    continue
                elif child.type == "link_open":
                    href = str(child.attrs.get("href", "") or "")
                    if href:
                        links.append(href[:500])
                elif child.type == "html_inline":
                    # html=False makes this rare; keep it as literal text.
                    parts.append(child.content)
                    if child.content.strip():
                        has_text = True
                if child.children:
                    walk(child.children)

        walk(inline.children)
        text = collapse_inline_whitespace("".join(parts))
        meta: Dict[str, Any] = {"has_omitted": has_omitted, "has_text": has_text}
        if links:
            meta["links"] = links[:20]
        return text, meta

    def _flatten_list(
        self, tokens: Sequence[Token], start: int, end: int, *, depth: int, lines: List[str]
    ) -> bool:
        """Flatten a (possibly nested) list into ``- `` / ``1. `` lines."""
        ordered = tokens[start].type == "ordered_list_open"
        index = 1
        if ordered:
            try:
                index = int(tokens[start].attrs.get("start", 1) or 1)
            except (TypeError, ValueError):
                index = 1
        omitted = False
        j = start + 1
        item_open = False
        while j < end:
            token = tokens[j]
            if token.type == "list_item_open" and token.level == tokens[start].level + 1:
                item_open = True
                j += 1
                continue
            if token.type == "list_item_close" and token.level == tokens[start].level + 1:
                item_open = False
                index += 1
                j += 1
                continue
            if item_open and token.type == "inline":
                text, inline_meta = self._flatten_inline(token)
                omitted = omitted or bool(inline_meta.get("has_omitted"))
                if text:
                    marker = f"{index}." if ordered else "-"
                    lines.append(f"{'  ' * depth}{marker} {text}")
                j += 1
                continue
            if token.type in ("bullet_list_open", "ordered_list_open"):
                sub_end = self._matching_close(tokens, j)
                omitted = self._flatten_list(tokens, j, sub_end, depth=depth + 1, lines=lines) or omitted
                j = sub_end + 1
                continue
            j += 1
        return omitted

    def _flatten_table(self, tokens: Sequence[Token], start: int, end: int) -> str:
        rows: List[List[str]] = []
        current: Optional[List[str]] = None
        for j in range(start + 1, end):
            token = tokens[j]
            if token.type == "tr_open":
                current = []
            elif token.type == "tr_close":
                if current is not None:
                    rows.append(current)
                current = None
            elif token.type == "inline" and current is not None:
                text, _meta = self._flatten_inline(token)
                current.append(text)
        return "\n".join("| " + " | ".join(row) + " |" for row in rows if row)


# --------------------------------------------------------------------------- #
# Plain text (deterministic heuristics)
# --------------------------------------------------------------------------- #

# Heading heuristics — deliberately cautious (DOCUMENT_INGESTION_ARCHITECTURE
# .md §2, TXT row). All constants are documented behavior of this parser
# version; changing them is a parser version bump.
#
# * numbered heading:   "1. Scope", "2.3 Controls", "3)" style — the numeric
#   path gives the depth. Rejected when the title part is long (> 60 chars or
#   > 8 words), ends like a sentence, or the line sits in a run of >= 2
#   consecutive numbered lines (that is a numbered *list*).
# * ALL-CAPS heading:   2–60 chars, >= 2 letters, no lowercase, <= 8 words,
#   no sentence-final punctuation. A long uppercase sentence fails the length
#   or word bound.
# * underlined heading: a qualifying line followed by ==== (level 1) or ----
#   (level 2), at least 3 underline characters.
# * fallback: fewer than 2 heading candidates in the whole document => no
#   heading detection at all; the document becomes paragraph/list blocks in
#   source order (safe paragraph grouping — no invented hierarchy).

_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(\S.*)$")
_UNDERLINE_EQ = re.compile(r"^={3,}\s*$")
_UNDERLINE_DASH = re.compile(r"^-{3,}\s*$")
_BULLET = re.compile(r"^\s*[-*•]\s+\S")
_NUMBERED_ITEM = re.compile(r"^\s*\d+(?:\.\d+)*[.)]\s+\S")

_MAX_HEADING_CHARS = 60
_MAX_HEADING_WORDS = 8
_SENTENCE_END = (".", ",", ";", ":", "!", "?")


class PlainTextParser:
    """Deterministic structure detection for .txt sources (no LLM, no domain
    assumptions). See the heuristics block above for exact behavior."""

    name = "plaintext-heuristic"
    version = "m2.1"

    def parse(self, text: str) -> DocIR:
        lines = text.split("\n")
        headings = self._heading_candidates(lines)
        detect_headings = len(headings) >= 2

        blocks: List[DocBlock] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue

            if detect_headings and i in headings:
                kind, level, title = headings[i]
                blocks.append(
                    DocBlock(
                        kind="heading",
                        level=level,
                        text=collapse_inline_whitespace(title),
                        meta={"line_start": i, "line_end": i + 1, "heading_style": kind},
                    )
                )
                i += 2 if kind == "underline" else 1
                continue

            if self._is_list_line(line):
                start = i
                items: List[str] = []
                while i < n and self._is_list_line(lines[i]):
                    items.append(collapse_inline_whitespace(lines[i]))
                    i += 1
                blocks.append(
                    DocBlock(
                        kind="list",
                        text="\n".join(items),
                        meta={"line_start": start, "line_end": i},
                    )
                )
                continue

            # paragraph: consecutive non-blank, non-structural lines
            start = i
            para: List[str] = []
            while i < n and lines[i].strip():
                if self._is_list_line(lines[i]) or (detect_headings and i in headings):
                    break
                para.append(lines[i])
                i += 1
            text_joined = collapse_inline_whitespace(" ".join(para))
            if text_joined:
                blocks.append(
                    DocBlock(
                        kind="paragraph",
                        text=text_joined,
                        meta={"line_start": start, "line_end": i},
                    )
                )

        return DocIR(blocks=tuple(blocks))

    # -- heuristics ---------------------------------------------------------- #

    def _heading_candidates(self, lines: List[str]) -> Dict[int, Tuple[str, int, str]]:
        """line index -> (style, level, title) for every cautious candidate."""
        found: Dict[int, Tuple[str, int, str]] = {}
        for i, raw in enumerate(lines):
            line = raw.strip()
            if not line:
                continue

            # underline style: this line is the title, the next the underline.
            if i + 1 < len(lines) and len(line) <= 80 and not self._is_list_line(raw):
                underline = lines[i + 1].strip()
                if _UNDERLINE_EQ.match(underline):
                    found[i] = ("underline", 1, line)
                    continue
                if _UNDERLINE_DASH.match(underline) and self._titleish(line):
                    found[i] = ("underline", 2, line)
                    continue

            numbered = _NUMBERED.match(line)
            if numbered and self._titleish(numbered.group(2)) and not self._in_numbered_run(lines, i):
                depth = min(numbered.group(1).count(".") + 1, 6)
                found[i] = ("numbered", depth, line)  # authored text, as written
                continue

            if self._all_caps_heading(line):
                found[i] = ("caps", 1, line)

        return found

    @staticmethod
    def _titleish(text: str) -> bool:
        text = text.strip()
        return (
            0 < len(text) <= _MAX_HEADING_CHARS
            and len(text.split()) <= _MAX_HEADING_WORDS
            and not text.endswith(_SENTENCE_END)
        )

    @staticmethod
    def _all_caps_heading(line: str) -> bool:
        if not (2 <= len(line) <= _MAX_HEADING_CHARS):
            return False
        letters = [c for c in line if c.isalpha()]
        if len(letters) < 2 or any(c.islower() for c in letters):
            return False
        if len(line.split()) > _MAX_HEADING_WORDS:
            return False
        return not line.endswith(_SENTENCE_END)

    @staticmethod
    def _numbered_depth(line: str) -> Optional[int]:
        match = _NUMBERED.match(line.strip())
        return match.group(1).count(".") + 1 if match else None

    @classmethod
    def _in_numbered_run(cls, lines: List[str], i: int) -> bool:
        """>= 2 *adjacent* numbered lines at the SAME depth are a numbered
        list, not headings. Different depths ("2. Controls" directly above
        "2.1 Encryption") are a heading hierarchy, and a blank line between
        numbered lines breaks the run."""
        depth = cls._numbered_depth(lines[i])
        if depth is None:
            return False
        for neighbor in (i - 1, i + 1):
            if 0 <= neighbor < len(lines) and cls._numbered_depth(lines[neighbor]) == depth:
                return True
        return False

    @staticmethod
    def _is_list_line(line: str) -> bool:
        if _BULLET.match(line):
            return True
        match = _NUMBERED_ITEM.match(line)
        if not match:
            return False
        # A numbered line is list-like only inside a run; single numbered
        # lines are handled by the heading heuristic or stay paragraph text.
        return True
