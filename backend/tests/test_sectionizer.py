"""M2 — deterministic sectionization over DocIR v1.

Pins: heading-aware grouping with hierarchy, source order, documented size
bounds (split at block boundaries, undersized trailing fragments merged),
bounded excerpts derived from the full text, full-text token/count metadata,
honest omitted-content markers, deterministic retries, and — deliberately —
no classification and no M3 anchor algorithm (transitional internal ids only).
"""

from __future__ import annotations

from app.contracts import DocBlock, DocIR
from app.ingestion.sectionizer import (
    ANCHOR_ALGO_TRANSITIONAL,
    EXCERPT_CHARS,
    MAX_SECTION_CHARS,
    MIN_SECTION_CHARS,
    manifest_sha256,
    sectionize,
    tokenize,
)


def heading(text: str, level: int = 1) -> DocBlock:
    return DocBlock(kind="heading", level=level, text=text)


def para(text: str) -> DocBlock:
    return DocBlock(kind="paragraph", text=text)


def doc(*blocks: DocBlock) -> DocIR:
    return DocIR(blocks=tuple(blocks))


class TestGrouping:
    def test_heading_aware_grouping_and_hierarchy(self):
        ir = doc(
            heading("Policy", 1),
            para("Intro body."),
            heading("Controls", 2),
            para("Control body."),
            heading("Encryption", 3),
            para("Encryption body."),
            heading("Appendix", 1),
            para("Appendix body."),
        )
        drafts = sectionize(ir)
        assert [d.title for d in drafts] == ["Policy", "Controls", "Encryption", "Appendix"]
        assert drafts[1].heading_path == ["Policy", "Controls"]
        assert drafts[2].heading_path == ["Policy", "Controls", "Encryption"]
        assert drafts[2].depth == 3
        assert drafts[3].heading_path == ["Appendix"]

    def test_source_order_and_ordinals(self):
        ir = doc(*(b for i in range(5) for b in (heading(f"H{i}"), para(f"body {i}"))))
        drafts = sectionize(ir)
        assert [d.ordinal for d in drafts] == [0, 1, 2, 3, 4]
        assert [d.title for d in drafts] == [f"H{i}" for i in range(5)]

    def test_heading_less_document_gets_derived_title(self):
        ir = doc(para("Access reviews run quarterly. Extra detail follows."))
        drafts = sectionize(ir)
        assert len(drafts) == 1
        assert drafts[0].title == "Access reviews run quarterly."
        assert drafts[0].heading_path == [drafts[0].title]

    def test_empty_heading_sections_are_skipped(self):
        ir = doc(heading("Empty"), heading("Full"), para("body"))
        drafts = sectionize(ir)
        assert [d.title for d in drafts] == ["Full"]

    def test_preamble_before_first_heading(self):
        ir = doc(para("Preamble text before any heading."), heading("Real"), para("body"))
        drafts = sectionize(ir)
        assert drafts[0].title.startswith("Preamble text")
        assert drafts[1].title == "Real"


class TestSizeBounds:
    def test_oversized_section_splits_at_block_boundaries(self):
        blocks = [heading("Big")] + [para("x" * 900) for _ in range(6)]  # ~5.4k chars
        drafts = sectionize(doc(*blocks))
        assert len(drafts) == 2
        assert all(d.title == "Big" for d in drafts)
        assert all(len(d.text) <= MAX_SECTION_CHARS for d in drafts)
        assert drafts[0].meta["split_part"] == 1
        assert drafts[0].meta["split_total"] == 2
        # no paragraph was cut mid-block
        assert all("x" * 900 in d.text for d in drafts)

    def test_single_oversized_block_splits_at_line_boundaries(self):
        giant = "\n".join(f"line {i} " + "y" * 80 for i in range(100))  # ~8.7k chars
        drafts = sectionize(doc(heading("Log"), DocBlock(kind="paragraph", text=giant)))
        assert len(drafts) >= 2
        assert all(len(d.text) <= MAX_SECTION_CHARS for d in drafts)
        rejoined = "\n".join(d.text for d in drafts)
        for i in range(100):
            assert f"line {i} " in rejoined  # nothing lost

    def test_undersized_trailing_fragment_merges_into_previous(self):
        # 3 x 1330 chars (+ separators) fills a fragment to ~3994; the 50-char
        # tail would be a dangling scrap below MIN, so it merges back into the
        # previous fragment (which may then modestly exceed MAX).
        blocks = [heading("S")] + [para("x" * 1330) for _ in range(3)] + [para("tail " * 10)]
        drafts = sectionize(doc(*blocks))
        assert len(drafts) == 1
        assert drafts[0].text.rstrip().endswith("tail")
        assert len(drafts[0].text) > MAX_SECTION_CHARS  # documented modest overflow
        assert len(drafts[0].text) < MAX_SECTION_CHARS + MIN_SECTION_CHARS

    def test_short_authored_section_is_kept(self):
        drafts = sectionize(doc(heading("Short"), para("Tiny body."), heading("Next"), para("y" * 300)))
        assert [d.title for d in drafts] == ["Short", "Next"]

    def test_code_and_table_blocks_not_split_when_they_fit(self):
        code = DocBlock(kind="paragraph", text="def f():\n    return 1", meta={"code": True})
        table = DocBlock(kind="table", text="| a | b |\n| 1 | 2 |")
        drafts = sectionize(doc(heading("H"), para("x" * 3900), code, table))
        joined = [d.text for d in drafts]
        assert any("def f():\n    return 1" in t for t in joined)
        assert any("| a | b |\n| 1 | 2 |" in t for t in joined)


class TestContentMetadata:
    def test_full_text_retained_and_excerpt_bounded(self):
        body = ". ".join(f"Sentence number {i} about controls" for i in range(200))
        drafts = sectionize(doc(heading("H"), para(body[:3500])))
        d = drafts[0]
        assert d.text == body[:3500]
        assert len(d.excerpt) <= EXCERPT_CHARS
        assert d.excerpt == d.text[: len(d.excerpt)]

    def test_token_and_count_metadata_derive_from_full_text(self):
        early = "alpha " * 50
        late = "zebra-signal appears only after the excerpt bound. "
        body = early + "b " * 1500 + late
        drafts = sectionize(doc(heading("H"), para(body[:3900])))
        d = drafts[0]
        assert len(d.excerpt) < d.char_count  # excerpt is truncated
        assert "zebra" in d.token_set  # token came from beyond the excerpt
        assert d.char_count == len(d.text)

    def test_omitted_content_markers_preserved(self):
        drafts = sectionize(
            doc(heading("H"), DocBlock(kind="omitted", text='[content omitted: image "diagram"]'))
        )
        d = drafts[0]
        assert d.has_omitted_content is True
        assert '[content omitted: image "diagram"]' in d.text

    def test_has_tables_flag(self):
        drafts = sectionize(doc(heading("H"), DocBlock(kind="table", text="| a |")))
        assert drafts[0].has_tables is True

    def test_no_invented_text(self):
        source_texts = ["only authored content here", "and this second block"]
        drafts = sectionize(doc(heading("Title"), *(para(t) for t in source_texts)))
        for token in drafts[0].text.replace("\n", " ").split():
            assert token in " ".join(["Title"] + source_texts)

    def test_no_classification(self):
        drafts = sectionize(doc(heading("Security"), para("encryption at rest")))
        d = drafts[0]
        assert not hasattr(d, "category")
        assert not hasattr(d, "topics")


class TestIdentityAndDeterminism:
    def test_transitional_internal_ids_only(self):
        drafts = sectionize(doc(heading("H"), para("body text goes here")))
        assert drafts[0].anchor_id == "s0000"
        assert drafts[0].citation_id == "pre-m3:s0000"
        assert ANCHOR_ALGO_TRANSITIONAL == "pre-m3-transitional"
        # NOT the M3 rendered shape ("{PREFIX}-{hash}"): no invented public identity
        assert not drafts[0].citation_id.isupper()

    def test_retries_produce_identical_sections(self):
        ir = doc(
            heading("A"), para("first body " * 30),
            heading("B"), para("second body " * 40),
        )
        first = sectionize(ir)
        second = sectionize(ir)
        assert [(d.anchor_id, d.ordinal, d.text_sha256, d.excerpt) for d in first] == [
            (d.anchor_id, d.ordinal, d.text_sha256, d.excerpt) for d in second
        ]
        assert manifest_sha256(first) == manifest_sha256(second)

    def test_manifest_changes_when_content_changes(self):
        a = sectionize(doc(heading("H"), para("version one")))
        b = sectionize(doc(heading("H"), para("version two")))
        assert manifest_sha256(a) != manifest_sha256(b)

    def test_tokenize_is_sorted_unique_lowercase(self):
        tokens = tokenize("Alpha beta ALPHA beta-2 x")
        assert tokens == sorted(set(tokens))
        assert "alpha" in tokens and "beta" in tokens
        assert "x" not in tokens  # single-char dropped
