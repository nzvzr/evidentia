"""M2 — normalization and the MD/TXT parsers (DocIR v1 out).

Pins the parser contract: deterministic block streams, honest omitted-content
markers, no HTML execution, no remote fetches, cautious plain-text heading
heuristics, and typed failures for invalid encodings and oversized text.
"""

from __future__ import annotations

import pytest

from app.contracts import DOC_BLOCK_KINDS, DocIR
from app.ingestion.errors import IngestionError
from app.ingestion.normalize import (
    collapse_inline_whitespace,
    decode_and_normalize,
    decode_bytes,
    normalize_text,
)
from app.ingestion.parsers import (
    FORMAT_MARKDOWN,
    FORMAT_TEXT,
    MarkdownParser,
    PlainTextParser,
    get_parser,
)

BIG = 1_000_000


def norm(text: str) -> str:
    return normalize_text(text, max_chars=BIG)


# --------------------------------------------------------------------------- #
# normalization
# --------------------------------------------------------------------------- #


class TestNormalization:
    def test_crlf_and_cr_become_lf(self):
        assert norm("a\r\nb\rc\nd") == "a\nb\nc\nd"

    def test_unicode_nfc(self):
        # e + combining acute (NFD) must normalize to the composed form.
        assert norm("café") == "café"

    def test_control_characters_removed_tabs_and_newlines_kept(self):
        assert norm("a\x00b\x07c\td\ne\x7f\x9f") == "abc\td\ne"

    def test_inline_whitespace_collapse_is_per_line(self):
        assert collapse_inline_whitespace("a   b\t\tc") == "a b c"

    def test_invalid_utf8_is_typed(self):
        with pytest.raises(IngestionError) as exc:
            decode_bytes(b"\xff\xfe invalid")
        assert exc.value.code == "invalid_encoding"

    def test_nul_bytes_are_treated_as_binary(self):
        with pytest.raises(IngestionError) as exc:
            decode_bytes(b"looks like text\x00but is not")
        assert exc.value.code == "invalid_encoding"

    def test_utf8_bom_is_stripped(self):
        assert decode_bytes(b"\xef\xbb\xbfhello") == "hello"

    def test_extracted_char_limit_is_typed(self):
        with pytest.raises(IngestionError) as exc:
            normalize_text("x" * 101, max_chars=100)
        assert exc.value.code == "extraction_too_large"

    def test_no_invented_text(self):
        # Everything in the output exists in the input (modulo removed CRs).
        source = "line one\r\nline  two"
        out = decode_and_normalize(source.encode("utf-8"), max_chars=BIG)
        assert out == "line one\nline  two"

    def test_deterministic(self):
        data = "# T\r\ncafé  \ttext".encode("utf-8")
        assert decode_and_normalize(data, max_chars=BIG) == decode_and_normalize(
            data, max_chars=BIG
        )


# --------------------------------------------------------------------------- #
# parser seam
# --------------------------------------------------------------------------- #


class TestParserSeam:
    def test_known_formats_resolve(self):
        assert isinstance(get_parser(FORMAT_MARKDOWN), MarkdownParser)
        assert isinstance(get_parser(FORMAT_TEXT), PlainTextParser)

    def test_unsupported_format_is_typed(self):
        with pytest.raises(IngestionError) as exc:
            get_parser("pdf")
        assert exc.value.code == "unsupported_format"

    def test_all_blocks_use_closed_kinds(self):
        ir = MarkdownParser().parse(norm("# A\n\ntext\n\n- x\n\n> q\n\n| a |\n|---|\n| 1 |\n"))
        assert isinstance(ir, DocIR)
        assert all(b.kind in DOC_BLOCK_KINDS for b in ir.blocks)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #


class TestMarkdownParser:
    def parse(self, text: str) -> DocIR:
        return MarkdownParser().parse(norm(text))

    def test_heading_levels_and_hierarchy(self):
        ir = self.parse("# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six\n")
        headings = [(b.level, b.text) for b in ir.blocks if b.kind == "heading"]
        assert headings == [
            (1, "One"), (2, "Two"), (3, "Three"), (4, "Four"), (5, "Five"), (6, "Six"),
        ]

    def test_paragraphs(self):
        ir = self.parse("First paragraph.\n\nSecond   paragraph with  runs.\n")
        paras = [b.text for b in ir.blocks if b.kind == "paragraph"]
        assert paras == ["First paragraph.", "Second paragraph with runs."]

    def test_ordered_and_unordered_lists(self):
        ir = self.parse("- alpha\n- beta\n\n1. first\n2. second\n")
        lists = [b for b in ir.blocks if b.kind == "list"]
        assert lists[0].text == "- alpha\n- beta"
        assert lists[0].meta["ordered"] is False
        assert lists[1].text == "1. first\n2. second"
        assert lists[1].meta["ordered"] is True

    def test_nested_lists(self):
        ir = self.parse("- outer\n  - inner one\n  - inner two\n- outer two\n")
        block = next(b for b in ir.blocks if b.kind == "list")
        assert block.text.splitlines() == [
            "- outer", "  - inner one", "  - inner two", "- outer two",
        ]

    def test_block_quotes(self):
        ir = self.parse("> quoted wisdom\n")
        block = next(b for b in ir.blocks if b.kind == "paragraph")
        assert block.text == "quoted wisdom"
        assert block.meta["blockquote"] == 1

    def test_fenced_code_kept_verbatim(self):
        ir = self.parse("```python\ndef  f():\n    return   1\n```\n")
        block = next(b for b in ir.blocks if b.meta.get("code"))
        assert block.text == "def  f():\n    return   1"  # no whitespace collapse
        assert block.meta["code_info"] == "python"

    def test_indented_code_block(self):
        ir = self.parse("para\n\n    indented code\n    line two\n")
        block = next(b for b in ir.blocks if b.meta.get("code"))
        assert "indented code" in block.text

    def test_tables_flattened_to_pipe_text(self):
        ir = self.parse("| a | b |\n|---|---|\n| 1 | 2 |\n")
        block = next(b for b in ir.blocks if b.kind == "table")
        assert block.text == "| a | b |\n| 1 | 2 |"

    def test_images_become_omitted_markers_with_alt(self):
        ir = self.parse("![Q3 architecture diagram](https://cdn.example/x.png)\n")
        block = ir.blocks[0]
        assert block.kind == "omitted"
        assert block.text == '[content omitted: image "Q3 architecture diagram"]'
        # the URL is never fetched and never appears as content
        assert "cdn.example" not in block.text

    def test_inline_image_marks_paragraph_omitted(self):
        ir = self.parse("Before ![alt](i.png) after.\n")
        block = ir.blocks[0]
        assert block.kind == "paragraph"
        assert '[content omitted: image "alt"]' in block.text
        assert block.meta.get("has_omitted") is True

    def test_links_keep_authored_text_href_in_meta(self):
        ir = self.parse("See [the policy](https://x.example/policy) now.\n")
        block = ir.blocks[0]
        assert block.text == "See the policy now."
        assert block.meta["links"] == ["https://x.example/policy"]

    def test_raw_html_is_literal_text_never_executed(self):
        ir = self.parse("<script>alert(1)</script>\n\n<div onclick=x>hi</div>\n")
        text = "\n".join(b.text for b in ir.blocks)
        # preserved as authored text (rendered escaped downstream), not parsed
        assert "<script>alert(1)</script>" in text
        assert all(b.kind in ("paragraph",) for b in ir.blocks)

    def test_deterministic(self):
        src = norm("# A\n\ntext ![i](x.png)\n\n- l1\n- l2\n\n| a |\n|---|\n| 1 |\n")
        assert MarkdownParser().parse(src) == MarkdownParser().parse(src)


# --------------------------------------------------------------------------- #
# plain text
# --------------------------------------------------------------------------- #


class TestPlainTextParser:
    def parse(self, text: str) -> DocIR:
        return PlainTextParser().parse(norm(text))

    def test_numbered_headings(self):
        ir = self.parse("1. Scope\n\nBody text.\n\n2. Controls\n\nMore body.\n")
        headings = [(b.level, b.text) for b in ir.blocks if b.kind == "heading"]
        assert headings == [(1, "1. Scope"), (1, "2. Controls")]

    def test_decimal_nested_numbered_headings(self):
        ir = self.parse("2. Controls\n2.1 Encryption\n\nAll data is encrypted.\n\n2.2 Access\n\nLeast privilege.\n")
        headings = [(b.level, b.text) for b in ir.blocks if b.kind == "heading"]
        assert (1, "2. Controls") in headings
        assert (2, "2.1 Encryption") in headings
        assert (2, "2.2 Access") in headings

    def test_short_all_caps_heading(self):
        ir = self.parse("SECURITY CONTROLS\n\nWe rotate keys.\n\nAPPENDIX\n\nExtra.\n")
        headings = [b.text for b in ir.blocks if b.kind == "heading"]
        assert headings == ["SECURITY CONTROLS", "APPENDIX"]

    def test_underline_style_headings(self):
        ir = self.parse("Main Title\n==========\n\nBody.\n\nSubsection\n----------\n\nMore.\n")
        headings = [(b.level, b.text) for b in ir.blocks if b.kind == "heading"]
        assert headings == [(1, "Main Title"), (2, "Subsection")]

    def test_heading_less_document_falls_back_to_paragraphs(self):
        ir = self.parse("Just a normal paragraph.\n\nAnother normal paragraph follows here.\n")
        assert [b.kind for b in ir.blocks] == ["paragraph", "paragraph"]

    def test_single_candidate_is_not_enough(self):
        # fewer than 2 candidates in the whole document => no heading detection
        ir = self.parse("INTRO\n\nParagraph one text.\n\nParagraph two text.\n")
        assert all(b.kind == "paragraph" for b in ir.blocks)

    def test_paragraph_boundaries(self):
        ir = self.parse("1. A\n\ntext one\ncontinues here\n\ntext two\n\n2. B\n\nlast\n")
        paras = [b.text for b in ir.blocks if b.kind == "paragraph"]
        assert paras == ["text one continues here", "text two", "last"]

    def test_list_like_lines(self):
        ir = self.parse("1. A\n\nItems:\n- laptops\n- servers\n\n2. B\n\nbody\n")
        block = next(b for b in ir.blocks if b.kind == "list")
        assert block.text == "- laptops\n- servers"

    def test_numbered_run_is_a_list_not_headings(self):
        ir = self.parse("Steps:\n1. do the first thing\n2. do the second thing\n3. finish\n")
        assert not any(b.kind == "heading" for b in ir.blocks)
        block = next(b for b in ir.blocks if b.kind == "list")
        assert block.text.splitlines()[0] == "1. do the first thing"

    def test_long_uppercase_sentence_is_not_a_heading(self):
        long_caps = (
            "THIS IS A VERY LONG UPPERCASE SENTENCE THAT SHOULD NEVER BE TREATED "
            "AS A HEADING BECAUSE IT IS FAR TOO LONG AND WORDY."
        )
        ir = self.parse(f"1. Scope\n\nBody.\n\n2. Controls\n\n{long_caps}\n")
        heading_texts = [b.text for b in ir.blocks if b.kind == "heading"]
        assert long_caps not in heading_texts

    def test_long_numbered_sentence_is_not_a_heading(self):
        line = "1. This numbered line is a complete long sentence explaining the first of several onboarding steps in detail."
        ir = self.parse(f"HEADING ONE\n\nBody.\n\nHEADING TWO\n\n{line}\n")
        heading_texts = [b.text for b in ir.blocks if b.kind == "heading"]
        assert line not in heading_texts

    def test_deterministic(self):
        src = norm("1. Scope\n\nBody.\n\n2. Controls\n\n- a\n- b\n")
        assert PlainTextParser().parse(src) == PlainTextParser().parse(src)
