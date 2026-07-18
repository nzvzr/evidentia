"""M3 — the final anchor algorithm (`heading-path-v1`), inheritance
(`content-match-v1`) and citation-prefix derivation. Pure-input tests: no
database, no tenant, no clock — determinism is the contract."""

from __future__ import annotations

import pytest

from app.ingestion import anchors as anchors_module
from app.ingestion.anchors import (
    ANCHOR_ALGO_VERSION,
    ANCHOR_INHERITANCE_VERSION,
    ANCHOR_INHERITED_DECISIONS,
    JACCARD_INHERIT_THRESHOLD,
    DECISION_HEADING_KEPT,
    DECISION_INHERITED_EXACT,
    DECISION_INHERITED_SIMILAR,
    DECISION_MINTED,
    DECISION_REATTACHED,
    DECISION_SPLIT_LINEAGE,
    DECISION_UNCHANGED,
    PREFIX_COLUMN_CHARS,
    SLUG_CHARS,
    PriorSection,
    assign_anchors,
    derive_citation_prefix,
    heading_path_digest,
    heading_slug,
    jaccard,
    normalize_heading_path,
    is_canonical_anchor,
    prefix_candidates,
    render_citation_id,
    validate_anchor_provenance,
)
from app.ingestion.normalize import decode_and_normalize
from app.ingestion.parsers import get_parser
from app.ingestion.sectionizer import sectionize


def drafts_from(markdown: str):
    text = decode_and_normalize(markdown.encode("utf-8"), max_chars=1_000_000)
    return sectionize(get_parser("markdown").parse(text))


def priors_from(markdown: str, prior=None):
    drafts = drafts_from(markdown)
    assignments = assign_anchors(drafts, prior or [])
    return [
        PriorSection(
            anchor_id=a.anchor_id,
            text_sha256=d.text_sha256,
            token_set=tuple(d.token_set),
            ordinal=d.ordinal,
            heading_path=tuple(d.heading_path),
        )
        for d, a in zip(drafts, assignments)
    ]


BASE = """# Guide

## Alpha

Alpha body content that stays completely stable across every revision here.

## Beta

Beta body content that also stays stable and long enough to carry tokens.

## Gamma

Gamma body content, stable and distinctive with its own vocabulary set.
"""


class TestDeterminism:
    def test_same_input_same_anchors(self):
        a = [x.anchor_id for x in assign_anchors(drafts_from(BASE))]
        b = [x.anchor_id for x in assign_anchors(drafts_from(BASE))]
        assert a == b

    def test_anchor_is_a_function_of_heading_path_only(self):
        one = drafts_from("## Alpha\n\nSome body.\n")
        other = drafts_from("## Alpha\n\nCompletely different body text.\n")
        assert assign_anchors(one)[0].anchor_id == assign_anchors(other)[0].anchor_id

    def test_normalization_rules(self):
        assert normalize_heading_path(["  Alpha   Beta "]) == "alpha beta"
        assert heading_slug(["Alpha Beta"]) == heading_slug(["alpha   beta"])
        # distinct paths hash apart
        assert heading_slug(["Guide", "Alpha"]) != heading_slug(["Alpha"])

    def test_no_collisions_and_slug_grammar(self):
        assignments = assign_anchors(drafts_from(BASE))
        anchors = [a.anchor_id for a in assignments]
        assert len(set(anchors)) == len(anchors)
        for anchor in anchors:
            assert len(anchor.split(".")[0].split("-")[0]) == SLUG_CHARS
        assert SLUG_CHARS == 12

    def test_ordinal_does_not_define_identity(self):
        """Reversing unrelated sections keeps every heading's anchor."""
        reordered = """# Guide

## Gamma

Gamma body content, stable and distinctive with its own vocabulary set.

## Beta

Beta body content, that also stays stable and long enough to carry tokens.

## Alpha

Alpha body content that stays completely stable across every revision here.
"""
        base_map = {
            d.title: a.anchor_id
            for d, a in zip(drafts_from(BASE), assign_anchors(drafts_from(BASE)))
        }
        re_map = {
            d.title: a.anchor_id
            for d, a in zip(drafts_from(reordered), assign_anchors(drafts_from(reordered)))
        }
        for title in ("Alpha", "Beta", "Gamma"):
            assert base_map[title] == re_map[title]


class TestInheritance:
    def test_identical_reprocessing_is_all_unchanged(self):
        prior = priors_from(BASE)
        assignments = assign_anchors(drafts_from(BASE), prior)
        assert all(a.decision == DECISION_UNCHANGED for a in assignments)
        assert [a.anchor_id for a in assignments] == [p.anchor_id for p in prior]

    def test_insertion_preserves_unaffected_anchors(self):
        prior = priors_from(BASE)
        inserted = BASE.replace(
            "## Beta", "## Inserted\n\nBrand new content nobody saw before.\n\n## Beta"
        )
        assignments = assign_anchors(drafts_from(inserted), prior)
        by_title = {
            d.title: a for d, a in zip(drafts_from(inserted), assignments)
        }
        assert by_title["Inserted"].decision == DECISION_MINTED
        for title in ("Alpha", "Beta", "Gamma"):
            assert by_title[title].decision == DECISION_UNCHANGED

    def test_deletion_preserves_unaffected_anchors(self):
        prior = priors_from(BASE)
        deleted = BASE.replace(
            "## Beta\n\nBeta body content that also stays stable and long enough to carry tokens.\n",
            "",
        )
        assignments = assign_anchors(drafts_from(deleted), prior)
        assert all(a.decision == DECISION_UNCHANGED for a in assignments)

    def test_edit_under_unchanged_heading_keeps_anchor(self):
        prior = priors_from(BASE)
        edited = BASE.replace("Alpha body content", "Alpha body content, revised,")
        assignments = assign_anchors(drafts_from(edited), prior)
        alpha = assignments[0]
        assert alpha.decision == DECISION_HEADING_KEPT
        assert alpha.anchor_id == prior[0].anchor_id

    def test_rename_with_identical_content_inherits_exact(self):
        prior = priors_from(BASE)
        renamed = BASE.replace("## Alpha", "## Alpha Renamed")
        assignments = assign_anchors(drafts_from(renamed), prior)
        alpha = assignments[0]
        assert alpha.decision == DECISION_INHERITED_EXACT
        assert alpha.anchor_id == prior[0].anchor_id
        assert alpha.inherited_from == prior[0].anchor_id

    def test_rename_with_light_edit_inherits_similar(self):
        long_doc = (
            "## Retention Rules\n\n"
            "The retention schedule covers every record class the platform stores, "
            "and each class lists its owner, its legal basis, its review cadence, "
            "and the archival destination that applies once the active period ends. "
            "Owners review their classes quarterly and record the outcome.\n"
        )
        prior = priors_from(long_doc)
        renamed = long_doc.replace("## Retention Rules", "## Retention Policy").replace(
            "quarterly", "annually"
        )
        assignments = assign_anchors(drafts_from(renamed), prior)
        section = assignments[0]
        assert section.decision == DECISION_INHERITED_SIMILAR
        assert section.anchor_id == prior[0].anchor_id
        assert section.similarity is not None and section.similarity >= 0.8

    def test_material_rewrite_mints_new_anchor(self):
        prior = priors_from(BASE)
        rewritten = BASE.replace("## Alpha", "## Totally Different").replace(
            "Alpha body content that stays completely stable across every revision here.",
            "An entirely new subject with none of the earlier words remaining at all.",
        )
        assignments = assign_anchors(drafts_from(rewritten), prior)
        assert assignments[0].decision == DECISION_MINTED
        assert assignments[0].anchor_id != prior[0].anchor_id

    def test_one_prior_anchor_cannot_be_inherited_twice(self):
        prior = priors_from(BASE)
        # Two new sections with the SAME content as old Alpha, both renamed.
        doubled = """# Guide

## First Copy

Alpha body content that stays completely stable across every revision here.

## Second Copy

Alpha body content that stays completely stable across every revision here.

## Beta

Beta body content that also stays stable and long enough to carry tokens.

## Gamma

Gamma body content, stable and distinctive with its own vocabulary set.
"""
        assignments = assign_anchors(drafts_from(doubled), prior)
        inherited = [a for a in assignments if a.inherited_from == prior[0].anchor_id]
        assert len(inherited) == 1
        # tie-break: nearest ordinal (both delta 0 vs 1 from old ordinal 0) ->
        # the earlier draft wins deterministically
        assert inherited[0].anchor_id == prior[0].anchor_id
        anchors = [a.anchor_id for a in assignments]
        assert len(set(anchors)) == len(anchors)

    def test_ambiguous_candidates_resolve_deterministically(self):
        """Repeated runs of an ambiguous revision produce identical outputs."""
        prior = priors_from(BASE)
        ambiguous = BASE.replace("## Alpha", "## Renamed A").replace("## Beta", "## Renamed B")
        first = [(a.anchor_id, a.decision) for a in assign_anchors(drafts_from(ambiguous), prior)]
        for _ in range(3):
            again = [(a.anchor_id, a.decision) for a in assign_anchors(drafts_from(ambiguous), prior)]
            assert again == first


class TestDuplicatesAndSplits:
    DUPES = """# Runbook

## Checklist

Confirm the window and page the on-call before starting anything at all.

## Checklist

Confirm the window and page the on-call before starting anything at all.
"""

    def test_duplicates_get_document_order_suffixes(self):
        assignments = assign_anchors(drafts_from(self.DUPES))
        anchors = [a.anchor_id for a in assignments]
        assert anchors[1] == f"{anchors[0]}-2"

    def test_insert_before_duplicates_reattaches_unchanged(self):
        prior = priors_from(self.DUPES)
        inserted = """# Runbook

## Checklist

A new first checklist with different words entirely.

## Checklist

Confirm the window and page the on-call before starting anything at all.

## Checklist

Confirm the window and page the on-call before starting anything at all.
"""
        drafts = drafts_from(inserted)
        assignments = assign_anchors(drafts, prior)
        # the two unchanged duplicates keep their old anchors
        assert assignments[1].anchor_id == prior[0].anchor_id
        assert assignments[1].decision == DECISION_REATTACHED
        assert assignments[2].anchor_id == prior[1].anchor_id
        # the new occurrence takes the next free index instead of stealing one
        assert assignments[0].decision == DECISION_MINTED
        assert assignments[0].anchor_id.endswith("-3")

    def test_split_parts_and_lineage(self):
        body = " ".join(f"Sentence number {i} about the retention schedule." for i in range(200))
        small = f"## Records\n\nShort body that fits well under the split bound.\n"
        big = f"## Records\n\n{body}\n"
        prior = priors_from(small)
        drafts = drafts_from(big)
        assert len(drafts) > 1
        assignments = assign_anchors(drafts, prior)
        assert assignments[0].anchor_id == f"{prior[0].anchor_id}.p1"
        assert assignments[0].decision == DECISION_SPLIT_LINEAGE
        assert assignments[0].inherited_from == prior[0].anchor_id
        assert assignments[1].anchor_id == f"{prior[0].anchor_id}.p2"
        assert assignments[1].decision == DECISION_MINTED

    def test_oscillation_restores_the_base_anchor(self):
        body = " ".join(f"Sentence number {i} about the retention schedule." for i in range(200))
        small = "## Records\n\nShort body that fits well under the split bound.\n"
        big = f"## Records\n\n{body}\n"
        v1 = priors_from(small)
        v2_drafts = drafts_from(big)
        v2_assign = assign_anchors(v2_drafts, v1)
        v2 = [
            PriorSection(
                a.anchor_id, d.text_sha256, tuple(d.token_set), d.ordinal,
                tuple(d.heading_path),
            )
            for d, a in zip(v2_drafts, v2_assign)
        ]
        v3_assign = assign_anchors(drafts_from(small), v2)
        # shrinking back under the bound restores the bare heading anchor
        assert v3_assign[0].anchor_id == v1[0].anchor_id


class TestTruncatedSlugCollisions:
    """The truncated display slug is NEVER identity. This pair collides on the
    old 5-char slug ('mfpfz'); the corrected algorithm must keep the two
    headings fully independent at every length where their slugs coincide."""

    HEADING_A = "Adversarial heading 8720"
    HEADING_B = "Adversarial heading 9588"
    DOC_A = "## Adversarial heading 8720\n\nOriginal content of the eighty-seven-twenty section that stays put here.\n"
    DOC_B = "## Adversarial heading 9588\n\nCompletely different content for the ninety-five-eighty-eight replacement.\n"

    def test_adversarial_pair_produces_distinct_anchors(self):
        a = assign_anchors(drafts_from(self.DOC_A))[0].anchor_id
        b = assign_anchors(drafts_from(self.DOC_B))[0].anchor_id
        assert a != b
        # they DO share the historical 5-char prefix — the very collision the
        # 12-char slug and full-digest identity must survive
        assert a[:5] == b[:5] == "mfpfz"

    def test_replacing_one_heading_never_inherits_the_other_anchor(self):
        prior = priors_from(self.DOC_A)
        assignments = assign_anchors(drafts_from(self.DOC_B), prior)
        assert assignments[0].decision == DECISION_MINTED
        assert assignments[0].anchor_id != prior[0].anchor_id
        assert assignments[0].inherited_from is None

    def test_both_headings_in_one_document_stay_distinct(self):
        drafts = drafts_from(self.DOC_A + "\n" + self.DOC_B)
        assignments = assign_anchors(drafts)
        anchors = [a.anchor_id for a in assignments]
        assert len(set(anchors)) == 2
        # never grouped as duplicates of one base
        assert not any(a.endswith("-2") for a in anchors)

    def test_editing_either_heading_cannot_perturb_the_other(self):
        both = self.DOC_A + "\n" + self.DOC_B
        prior = priors_from(both)
        by_anchor = {p.heading_path[-1]: p.anchor_id for p in prior}

        # delete A: B keeps its anchor, unchanged
        only_b = assign_anchors(drafts_from(self.DOC_B), prior)
        assert only_b[0].anchor_id == by_anchor[self.HEADING_B]
        assert only_b[0].decision == DECISION_UNCHANGED

        # delete B: A keeps its anchor, unchanged
        only_a = assign_anchors(drafts_from(self.DOC_A), prior)
        assert only_a[0].anchor_id == by_anchor[self.HEADING_A]

        # edit A's body, insert a new section: both keep their anchors
        edited = self.DOC_A.replace("stays put", "was edited but stays put")
        combined = edited + "\n## Unrelated Insert\n\nBrand new content nobody saw before.\n\n" + self.DOC_B
        assignments = assign_anchors(drafts_from(combined), prior)
        titles = [d.title for d in drafts_from(combined)]
        by_title = dict(zip(titles, assignments))
        assert by_title[self.HEADING_A].anchor_id == by_anchor[self.HEADING_A]
        assert by_title[self.HEADING_A].decision == DECISION_HEADING_KEPT
        assert by_title[self.HEADING_B].anchor_id == by_anchor[self.HEADING_B]
        assert by_title[self.HEADING_B].decision == DECISION_UNCHANGED

    def test_forced_truncated_collision_uses_full_canonical_identity(self, monkeypatch):
        """Force the truncated slugs to actually collide (5 chars) and prove
        the machinery holds for ANY collision, not just today's examples:
        distinct canonical identities are never grouped, never inherit, and
        the document remains finalizable via deterministic extension."""
        monkeypatch.setattr(anchors_module, "SLUG_CHARS", 5)
        assert heading_slug([self.HEADING_A]) == heading_slug([self.HEADING_B]) == "mfpfz"
        assert heading_path_digest([self.HEADING_A]) != heading_path_digest([self.HEADING_B])

        # both in one document: finalizable, distinct, extended deterministically
        drafts = drafts_from(self.DOC_A + "\n" + self.DOC_B)
        assignments = assign_anchors(drafts)
        anchors = [a.anchor_id for a in assignments]
        assert len(set(anchors)) == 2
        assert not any(a.endswith("-2") for a in anchors)
        for anchor in anchors:
            assert len(anchor) > 5  # extended from each heading's OWN digest
        again = [a.anchor_id for a in assign_anchors(drafts)]
        assert again == anchors  # byte-identical reprocessing

        # replacement across versions: never inherits through the collision
        prior = priors_from(self.DOC_A)
        replaced = assign_anchors(drafts_from(self.DOC_B), prior)
        assert replaced[0].decision == DECISION_MINTED
        assert replaced[0].anchor_id != prior[0].anchor_id

    def test_extended_anchor_survives_later_revisions(self, monkeypatch):
        """An anchor minted in extended form is identity forever: later
        revisions (even ones where the collision partner disappeared) keep it
        through full-canonical-path matching, not slug recomputation."""
        monkeypatch.setattr(anchors_module, "SLUG_CHARS", 5)
        both = self.DOC_A + "\n" + self.DOC_B
        prior = priors_from(both)
        extended_a = next(p.anchor_id for p in prior if p.heading_path[-1] == self.HEADING_A)
        assert len(extended_a) > 5
        # B deleted; A edited: A keeps its extended anchor via heading identity
        edited_a = self.DOC_A.replace("stays put", "revised and expanded")
        assignments = assign_anchors(drafts_from(edited_a), prior)
        assert assignments[0].anchor_id == extended_a
        assert assignments[0].decision == DECISION_HEADING_KEPT


class TestJaccard:
    def test_bounds(self):
        assert jaccard([], []) == 0.0
        assert jaccard(["a", "b"], ["a", "b"]) == 1.0
        assert jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


class TestCitationPrefix:
    def test_derivation_examples(self):
        assert derive_citation_prefix("Data Handling Policy") == "DHP"
        assert derive_citation_prefix("Security & Compliance Whitepaper") == "SCW"
        assert derive_citation_prefix("The Incident Response Runbook Guide") == "IRRG"
        assert derive_citation_prefix("SLA") == "SLX"  # consonant/X padding
        assert derive_citation_prefix("") == "DOC"

    def test_candidates_sequence(self):
        cands = list(prefix_candidates("Data Handling Policy", limit=3))
        assert cands[:3] == ["DHP", "DHP2", "DHP3"]

    def test_candidate_capacity_covers_the_configured_quota(self):
        """The default candidate count must cover the documented tenant
        document quota (500) even when EVERY title derives the same base."""
        from app.core.config import get_settings

        quota = get_settings().evidentia_tenant_max_documents
        for title in ("", "!!!", "日本語のタイトル", "Data Handling Policy"):
            cands = list(prefix_candidates(title, limit=quota))
            assert len(cands) >= quota
            assert len(set(cands)) == len(cands)

    def test_candidates_never_overflow_the_column(self):
        for title in ("", "Data Handling Policy Extra Words", "只有中文"):
            for cand in prefix_candidates(title, limit=10_000):
                assert len(cand) <= PREFIX_COLUMN_CHARS

    def test_punctuation_and_non_latin_titles_fall_back_to_doc(self):
        assert derive_citation_prefix("!!! ???") == "DOC"
        assert derive_citation_prefix("日本語だけ") == "DOC"
        cands = list(prefix_candidates("日本語だけ", limit=500))
        assert cands[0] == "DOC" and cands[500] == "DOC501"

    def test_unicode_titles_fold_to_ascii(self):
        prefix = derive_citation_prefix("Résumé Écran Ünion")
        assert prefix.isascii() and 3 <= len(prefix) <= 5

    def test_render_citation_id(self):
        assert render_citation_id("DHP", "k3f9x.p2") == "DHP-k3f9x.p2"


class TestVersioning:
    def test_algorithm_version_is_final_and_stable(self):
        assert ANCHOR_ALGO_VERSION == "heading-path-v1"
        assert ANCHOR_ALGO_VERSION != "pre-m3-transitional"


class TestCanonicalAnchorGrammar:
    """THE one permanent-anchor grammar (`ANCHOR_GRAMMAR_RE` /
    `is_canonical_anchor`): bare slug for the first occurrence, duplicate
    suffixes starting at 2, split parts starting at 1, canonical decimal only —
    no leading zeros, no "-0"/"-1"."""

    SLUG = "abcdefghijkl"  # 12 chars, the minimum
    EXTENDED = "abcdefghijklmnop"  # 16 chars (one deterministic extension step)
    FULL = "a" * 31  # the maximum (full base36 digest rendering)

    @pytest.mark.parametrize(
        "anchor",
        [
            SLUG,
            f"{SLUG}-2",
            f"{SLUG}-3",
            f"{SLUG}-10",
            f"{SLUG}.p1",
            f"{SLUG}.p2",
            f"{SLUG}-2.p1",
            f"{SLUG}-10.p3",
            EXTENDED,
            f"{EXTENDED}-2.p1",
            FULL,
        ],
    )
    def test_valid_anchors(self, anchor):
        assert is_canonical_anchor(anchor)

    @pytest.mark.parametrize(
        "anchor",
        [
            f"{SLUG}-0",
            f"{SLUG}-1",
            f"{SLUG}-01",
            f"{SLUG}-00",
            f"{SLUG}-002",
            f"{SLUG}-.p1",
            f"{SLUG}-0.p1",
            f"{SLUG}-1.p1",
            f"{SLUG}-01.p1",
            f"{SLUG}-2.p0",
            f"{SLUG}-2.p01",
            f"{SLUG}.p0",
            f"{SLUG}.p01",
            "abcdefghijk",  # 11 chars: below the frozen 12-char minimum
            "a" * 32,  # beyond the full digest rendering
            "s0007",  # transitional ordinal id
            "ABCDEFGHIJKL",  # not base36-lowercase
            "",
        ],
    )
    def test_invalid_anchors(self, anchor):
        assert not is_canonical_anchor(anchor)

    def test_non_string_is_not_an_anchor(self):
        assert not is_canonical_anchor(None)
        assert not is_canonical_anchor(12)

    TRAILING_OR_PADDED = [
        f"{SLUG}\n",
        f"{SLUG}\r",
        f"{SLUG}\r\n",
        f"{SLUG} ",
        f" {SLUG}",
        f"{SLUG}\t",
        f"{SLUG}-2.p1\n",
    ]
    # Python `\d` matches Unicode decimal digits; the canonical grammar is
    # strict ASCII, so none of these may parse (or be int()-converted).
    UNICODE_DIGIT_DUPS = [
        f"{SLUG}-٢",       # Arabic-Indic 2
        f"{SLUG}-2٢",      # ASCII 2 + Arabic-Indic 2 (old \d accepted this)
        f"{SLUG}-１２",     # fullwidth 12
        f"{SLUG}-२",       # Devanagari 2
    ]
    UNICODE_DIGIT_PARTS = [
        f"{SLUG}.p١",      # Arabic-Indic 1
        f"{SLUG}.p1٢",     # ASCII 1 + Arabic-Indic 2 (old \d accepted this)
        f"{SLUG}-2.p１２",  # fullwidth 12
        f"{SLUG}-2.p२",    # Devanagari 2
    ]

    @pytest.mark.parametrize(
        "anchor", TRAILING_OR_PADDED + UNICODE_DIGIT_DUPS + UNICODE_DIGIT_PARTS
    )
    def test_trailing_characters_and_unicode_digits_reject(self, anchor):
        """The parser validates an already-canonical STORED identifier: it must
        match the entire string exactly (no `$`-before-newline laxness) and
        accept ASCII digits only — never normalizing, stripping or converting
        Unicode digits through int()."""
        assert not is_canonical_anchor(anchor)
        assert anchors_module._parse_anchor(anchor) == ("\x00", 1, None)

    CANONICAL_PARSES = [
        (SLUG, (SLUG, 1, None)),
        (f"{SLUG}-2", (SLUG, 2, None)),
        (f"{SLUG}-10", (SLUG, 10, None)),
        (f"{SLUG}.p1", (SLUG, 1, 1)),
        (f"{SLUG}-2.p1", (SLUG, 2, 1)),
        (f"{SLUG}-2.p10", (SLUG, 2, 10)),
    ]

    @pytest.mark.parametrize("anchor,expected", CANONICAL_PARSES)
    def test_valid_ascii_anchors_parse_exactly(self, anchor, expected):
        assert is_canonical_anchor(anchor)
        assert anchors_module._parse_anchor(anchor) == expected

    def test_predicate_and_parser_agree_on_every_tested_input(self):
        """For every input in this class's corpus — valid and malformed —
        `is_canonical_anchor(x)` is True exactly when `_parse_anchor(x)` does
        NOT return the invalid sentinel."""
        corpus = (
            [anchor for anchor, _expected in self.CANONICAL_PARSES]
            + [
                self.SLUG,
                f"{self.SLUG}-3",
                f"{self.SLUG}.p2",
                f"{self.SLUG}-10.p3",
                self.EXTENDED,
                f"{self.EXTENDED}-2.p1",
                self.FULL,
            ]
            + [
                f"{self.SLUG}-0",
                f"{self.SLUG}-1",
                f"{self.SLUG}-01",
                f"{self.SLUG}-00",
                f"{self.SLUG}-002",
                f"{self.SLUG}-.p1",
                f"{self.SLUG}-2.p0",
                f"{self.SLUG}-2.p01",
                f"{self.SLUG}.p0",
                "abcdefghijk",
                "a" * 32,
                "s0007",
                "ABCDEFGHIJKL",
                "",
            ]
            + self.TRAILING_OR_PADDED
            + self.UNICODE_DIGIT_DUPS
            + self.UNICODE_DIGIT_PARTS
        )
        sentinel = ("\x00", 1, None)
        for anchor in corpus:
            parsed_valid = anchors_module._parse_anchor(anchor) != sentinel
            assert is_canonical_anchor(anchor) == parsed_valid, anchor

    @pytest.mark.parametrize(
        "anchor", [f"{SLUG}-0", f"{SLUG}-1", f"{SLUG}-01", f"{SLUG}-2.p0"]
    )
    def test_parser_maps_malformed_suffixes_to_never_matching(self, anchor):
        """`_parse_anchor` must not quietly normalize a malformed suffix (the
        old parser read "-1" as the bare form and "-01" as dup 1): malformed
        anchors map to the never-matching sentinel."""
        assert anchors_module._parse_anchor(anchor) == ("\x00", 1, None)

    def test_parser_reads_canonical_forms(self):
        assert anchors_module._parse_anchor(self.SLUG) == (self.SLUG, 1, None)
        assert anchors_module._parse_anchor(f"{self.SLUG}-2") == (self.SLUG, 2, None)
        assert anchors_module._parse_anchor(f"{self.SLUG}-10.p3") == (self.SLUG, 10, 3)
        assert anchors_module._parse_anchor(f"{self.SLUG}.p1") == (self.SLUG, 1, 1)

    def test_every_real_assignment_emits_canonical_anchors(self):
        """Producer/parser agreement: everything `assign_anchors` emits —
        including duplicate suffixes and inherited lineage — parses under the
        canonical grammar."""
        dups = """# Doc

## Escalation

First escalation body with enough words to carry a distinct token set.

## Escalation

Second escalation body, also distinct enough to stand on its own here.
"""
        prior = priors_from(BASE)
        scenarios = [
            assign_anchors(drafts_from(BASE), prior),
            assign_anchors(
                drafts_from(BASE.replace("## Beta", "## Beta Renamed")), prior
            ),
            assign_anchors(drafts_from(dups)),
            assign_anchors(drafts_from(dups), priors_from(dups)),
        ]
        for assignments in scenarios:
            for a in assignments:
                assert is_canonical_anchor(a.anchor_id), a.anchor_id
                if a.inherited_from is not None:
                    assert is_canonical_anchor(a.inherited_from), a.inherited_from


class TestProvenanceValidation:
    """The frozen decision-semantics matrix of ``validate_anchor_provenance``:
    the validator receives the section's CURRENT anchor and enforces the
    relationships ``assign_anchors`` actually produces — not just field shape."""

    ANCHOR = "abcdef012345"
    OTHER = "zzzzzz999999"

    def _validate(self, prov, anchor=None):
        return validate_anchor_provenance(
            prov,
            anchor_id=self.ANCHOR if anchor is None else anchor,
            algo=ANCHOR_ALGO_VERSION,
            inheritance=ANCHOR_INHERITANCE_VERSION,
        )

    def _prov(self, decision, **extra):
        return {
            "algo": ANCHOR_ALGO_VERSION,
            "inheritance": ANCHOR_INHERITANCE_VERSION,
            "decision": decision,
            **extra,
        }

    # -- minted: a fresh identity has NO predecessor lineage ------------------ #

    def test_minted_is_valid_bare(self):
        assert self._validate(self._prov(DECISION_MINTED)) is None

    def test_minted_with_inherited_from_rejects(self):
        prov = self._prov(DECISION_MINTED, inheritedFrom=self.ANCHOR)
        assert self._validate(prov) == "anchor_minted_has_inherited_from"

    def test_minted_with_similarity_rejects(self):
        prov = self._prov(DECISION_MINTED, similarity=1.0)
        assert self._validate(prov) == "anchor_similarity_unexpected"

    # -- preserved-anchor decisions: inheritedFrom IS the current anchor ------ #

    @pytest.mark.parametrize(
        "decision", [DECISION_UNCHANGED, DECISION_HEADING_KEPT, DECISION_REATTACHED]
    )
    def test_preserved_anchor_with_self_lineage_is_valid(self, decision):
        prov = self._prov(decision, inheritedFrom=self.ANCHOR)
        assert self._validate(prov) is None

    @pytest.mark.parametrize(
        "decision", [DECISION_UNCHANGED, DECISION_HEADING_KEPT, DECISION_REATTACHED]
    )
    def test_preserved_anchor_with_unrelated_lineage_rejects(self, decision):
        prov = self._prov(decision, inheritedFrom=self.OTHER)
        assert self._validate(prov) == "anchor_lineage_mismatch"

    @pytest.mark.parametrize(
        "decision", sorted(ANCHOR_INHERITED_DECISIONS)
    )
    def test_lineage_decision_without_inherited_from_rejects(self, decision):
        assert self._validate(self._prov(decision)) == "anchor_inherited_missing_from"

    def test_preserved_anchor_with_arbitrary_similarity_rejects(self):
        prov = self._prov(
            DECISION_UNCHANGED, inheritedFrom=self.ANCHOR, similarity=0.2
        )
        assert self._validate(prov) == "anchor_similarity_unexpected"

    # -- inherited-exact: adopted anchor + EXACTLY the frozen exact value ----- #

    def test_inherited_exact_valid(self):
        prov = self._prov(
            DECISION_INHERITED_EXACT, inheritedFrom=self.ANCHOR, similarity=1.0
        )
        assert self._validate(prov) is None

    def test_inherited_exact_similarity_0_2_rejects(self):
        prov = self._prov(
            DECISION_INHERITED_EXACT, inheritedFrom=self.ANCHOR, similarity=0.2
        )
        assert self._validate(prov) == "anchor_similarity_not_exact"

    def test_inherited_exact_missing_similarity_rejects(self):
        prov = self._prov(DECISION_INHERITED_EXACT, inheritedFrom=self.ANCHOR)
        assert self._validate(prov) == "anchor_similarity_missing"

    def test_inherited_exact_unrelated_anchor_rejects(self):
        prov = self._prov(
            DECISION_INHERITED_EXACT, inheritedFrom=self.OTHER, similarity=1.0
        )
        assert self._validate(prov) == "anchor_lineage_mismatch"

    # -- inherited-similar: frozen Jaccard threshold ---------------------------- #

    def test_inherited_similar_at_threshold_is_valid(self):
        prov = self._prov(
            DECISION_INHERITED_SIMILAR,
            inheritedFrom=self.ANCHOR,
            similarity=JACCARD_INHERIT_THRESHOLD,
        )
        assert self._validate(prov) is None

    def test_inherited_similar_below_threshold_rejects(self):
        prov = self._prov(
            DECISION_INHERITED_SIMILAR, inheritedFrom=self.ANCHOR, similarity=0.1
        )
        assert self._validate(prov) == "anchor_similarity_below_threshold"

    def test_inherited_similar_above_one_rejects(self):
        prov = self._prov(
            DECISION_INHERITED_SIMILAR, inheritedFrom=self.ANCHOR, similarity=1.01
        )
        assert self._validate(prov) == "anchor_similarity_invalid"

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_inherited_similar_non_finite_rejects(self, bad):
        prov = self._prov(
            DECISION_INHERITED_SIMILAR, inheritedFrom=self.ANCHOR, similarity=bad
        )
        assert self._validate(prov) == "anchor_similarity_invalid"

    def test_inherited_similar_missing_similarity_rejects(self):
        prov = self._prov(DECISION_INHERITED_SIMILAR, inheritedFrom=self.ANCHOR)
        assert self._validate(prov) == "anchor_similarity_missing"

    # -- split lineage: current anchor == "{parent}.p1", parent part-free ------ #

    def test_split_lineage_valid(self):
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=self.ANCHOR)
        assert self._validate(prov, anchor=f"{self.ANCHOR}.p1") is None

    def test_split_lineage_valid_with_dup_parent(self):
        parent = f"{self.ANCHOR}-2"
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=parent)
        assert self._validate(prov, anchor=f"{parent}.p1") is None

    def test_split_lineage_parent_equal_to_child_rejects(self):
        anchor = f"{self.ANCHOR}.p1"
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=anchor)
        assert self._validate(prov, anchor=anchor) == "anchor_split_lineage_invalid"

    def test_split_lineage_wrong_part_rejects(self):
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=self.ANCHOR)
        assert (
            self._validate(prov, anchor=f"{self.ANCHOR}.p2")
            == "anchor_split_lineage_invalid"
        )

    def test_split_lineage_unrelated_parent_rejects(self):
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=self.OTHER)
        assert (
            self._validate(prov, anchor=f"{self.ANCHOR}.p1")
            == "anchor_split_lineage_invalid"
        )

    def test_split_lineage_part_suffixed_parent_rejects(self):
        parent = f"{self.ANCHOR}.p1"
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=parent)
        assert (
            self._validate(prov, anchor=f"{parent}.p1")
            == "anchor_split_lineage_invalid"
        )

    @pytest.mark.parametrize("suffix", ["-0", "-1", "-01", "-00", "-002"])
    def test_split_lineage_non_canonical_dup_parent_rejects(self, suffix):
        """A parent with a malformed duplicate suffix fails the canonical
        grammar BEFORE the relationship comparison — even though the child
        string is exactly parent + '.p1'."""
        parent = f"{self.ANCHOR}{suffix}"
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=parent)
        assert (
            self._validate(prov, anchor=f"{parent}.p1")
            == "anchor_split_lineage_invalid"
        )

    @pytest.mark.parametrize("child_suffix", [".p0", ".p01"])
    def test_split_lineage_non_canonical_child_part_rejects(self, child_suffix):
        parent = f"{self.ANCHOR}-2"
        prov = self._prov(DECISION_SPLIT_LINEAGE, inheritedFrom=parent)
        assert (
            self._validate(prov, anchor=f"{parent}{child_suffix}")
            == "anchor_split_lineage_invalid"
        )

    # -- schema-level rejections ------------------------------------------------ #

    def test_unknown_decision_rejects(self):
        assert self._validate(self._prov("teleported")) == "anchor_decision_invalid"

    def test_extra_key_rejects(self):
        prov = self._prov(DECISION_MINTED, note="x")
        assert self._validate(prov) == "anchor_provenance_extra_field"

    def test_wrong_algo_and_inheritance_reject(self):
        assert (
            self._validate({**self._prov(DECISION_MINTED), "algo": "heading-path-v999"})
            == "anchor_algo_mismatch"
        )
        assert (
            self._validate(
                {**self._prov(DECISION_MINTED), "inheritance": "content-match-v999"}
            )
            == "anchor_inheritance_mismatch"
        )

    def test_non_dict_rejects(self):
        assert self._validate(None) == "anchor_provenance_missing"
        assert self._validate("minted") == "anchor_provenance_missing"

    # -- producer/validator agreement: every REAL assignment validates --------- #

    def test_every_real_assignment_produces_valid_provenance(self):
        """Everything ``assign_anchors`` persists — minted, unchanged,
        heading-kept, reattached, inherited-exact, inherited-similar and
        split-lineage across the revision scenarios above — must pass the
        semantic validator with its own current anchor."""
        scenarios = []
        prior = priors_from(BASE)
        scenarios.append(assign_anchors(drafts_from(BASE), prior))  # unchanged
        edited = BASE.replace("Alpha body content", "Alpha body content, edited,")
        scenarios.append(assign_anchors(drafts_from(edited), prior))  # heading-kept
        renamed = BASE.replace("## Beta", "## Beta Renamed")
        scenarios.append(assign_anchors(drafts_from(renamed), prior))  # inherited-*
        decisions_seen = set()
        for assignments in scenarios:
            for assignment in assignments:
                decisions_seen.add(assignment.decision)
                assert (
                    validate_anchor_provenance(
                        assignment.provenance(),
                        anchor_id=assignment.anchor_id,
                        algo=ANCHOR_ALGO_VERSION,
                        inheritance=ANCHOR_INHERITANCE_VERSION,
                    )
                    is None
                ), (assignment.decision, assignment.anchor_id)
        assert DECISION_UNCHANGED in decisions_seen
