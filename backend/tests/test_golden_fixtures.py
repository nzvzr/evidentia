"""M3 — golden fixture corpus for the permanent identity surfaces.

Each committed ``tests/golden/expected/*.json`` file pins ordered sections,
final anchor ids, inheritance decisions, internal citation ids,
classification labels, matched rule ids, classification signatures, the
complete finalization target and the final manifest for one fixture. Tests
compare EXACT equality and never regenerate: changed output means a
permanent identity change that must be made deliberately via
``python scripts/regenerate_golden_fixtures.py`` and explained in review.
"""

from __future__ import annotations

import pytest

from app.ingestion.anchors import (
    ANCHOR_ALGO_VERSION,
    ANCHOR_INHERITANCE_VERSION,
    is_canonical_anchor,
    validate_anchor_provenance,
)
from tests.golden_harness import (
    FIXTURE_PLAN,
    FIXTURES_DIR,
    GOLDEN_PREFIX,
    REQUIRED_GOLDEN_CASES,
    compute_fixture,
    expected_path,
    load_expected,
)


@pytest.mark.parametrize("name", sorted(FIXTURE_PLAN))
def test_every_golden_anchor_is_canonical(name):
    """Every committed golden anchor id — and every lineage anchor named by a
    golden provenance — parses under THE canonical anchor grammar (bare slug,
    dup >= 2, part >= 1, canonical decimal). Byte-for-byte golden stability is
    separately pinned by the exact-equality fixture tests."""
    for section in load_expected(name)["sections"]:
        assert is_canonical_anchor(section["anchorId"]), (name, section["anchorId"])
        inherited = section["anchorProvenance"].get("inheritedFrom")
        if inherited is not None:
            assert is_canonical_anchor(inherited), (name, inherited)


@pytest.mark.parametrize("name", sorted(FIXTURE_PLAN))
def test_every_golden_provenance_is_semantically_valid(name):
    """Every committed golden section's anchorProvenance must pass the FULL
    semantic validator (decision matrix, current-anchor lineage, similarity
    thresholds) with its own anchor — the producer and the validator agree on
    the frozen contract across the whole pinned corpus, including the
    split-lineage and inherited-similar cases."""
    for section in load_expected(name)["sections"]:
        reason = validate_anchor_provenance(
            section["anchorProvenance"],
            anchor_id=section["anchorId"],
            algo=ANCHOR_ALGO_VERSION,
            inheritance=ANCHOR_INHERITANCE_VERSION,
        )
        assert reason is None, (name, section["anchorId"], reason)


def test_required_cases_equal_registered_cases_exactly():
    """No permanent behavior can silently drop out of the corpus: the
    reviewed REQUIRED set and the registered plan must be identical, and
    every required case must have a committed expectation and input."""
    assert set(FIXTURE_PLAN) == REQUIRED_GOLDEN_CASES
    for name in sorted(REQUIRED_GOLDEN_CASES):
        assert expected_path(name).is_file(), f"missing committed golden output for {name!r}"
        assert (FIXTURES_DIR / FIXTURE_PLAN[name]["file"]).is_file(), (
            f"missing authored input fixture for {name!r}"
        )


@pytest.mark.parametrize("name", sorted(FIXTURE_PLAN))
def test_golden_fixture_matches_committed_expectation(name):
    assert expected_path(name).is_file(), (
        f"missing committed golden output for {name!r}; run the explicit "
        "regeneration command and review the diff"
    )
    assert compute_fixture(name) == load_expected(name)


def test_identical_reprocessing_produces_identical_output():
    assert compute_fixture("base") == compute_fixture("reprocess") | {"fixture": "base"}


def test_inheritance_preserves_every_anchor_on_identical_content():
    base = load_expected("base")
    inherited = load_expected("inherit-identical")
    assert [s["anchorId"] for s in base["sections"]] == [
        s["anchorId"] for s in inherited["sections"]
    ]
    assert all(s["decision"] == "unchanged" for s in inherited["sections"])


def test_corpus_covers_required_cases():
    """The §20 case list is demonstrably present in the committed corpus."""
    base = load_expected("base")
    sections = base["sections"]

    # duplicate/repeated headings
    titles = [s["title"] for s in sections]
    assert titles.count("Escalation") == 2
    # heading-less preamble (synthesized title)
    assert sections[0]["headingPath"][0].startswith("This handbook opens")
    # tables + image omission markers
    assert any(s["hasTables"] for s in sections)
    assert any(s["hasOmittedContent"] for s in sections)
    # compliance-positive / exclusion-negative / unclassified
    assert any(s["category"] == "Compliance" for s in sections)
    style = next(s for s in sections if s["title"] == "Style Notes")
    assert style["category"] == "General"
    assert "compliance.exclusion.style-guide" in style["matchedRules"]
    assert any(
        s["category"] == "General" and not s["matchedRules"] for s in sections
    )
    # injection flags recorded as data
    support = next(s for s in sections if s["title"] == "Notes From Support")
    assert "instruction-override" in support["injectionFlags"]

    # variant decisions
    assert any(
        s["decision"] == "minted" for s in load_expected("insert-section")["sections"]
    )
    light = load_expected("light-edit")["sections"]
    assert any(s["decision"] == "heading-kept" for s in light)
    assert any(s["decision"] == "inherited-exact" for s in light)
    rewrite = load_expected("rewrite")["sections"]
    assert any(s["decision"] == "inherited-similar" for s in rewrite)
    assert any(s["decision"] == "minted" for s in rewrite)
    dup_insert = load_expected("duplicates-insert-before")["sections"]
    assert sum(1 for s in dup_insert if s["decision"] == "reattached-exact") == 3
    split = load_expected("split")["sections"]
    assert [s["anchorId"].rsplit(".", 1)[-1] for s in split] == ["p1", "p2"]
    # move: the moved unchanged section retains its anchor
    base_arch = next(s for s in sections if s["title"] == "Architecture Overview")
    moved = next(
        s for s in load_expected("move-section")["sections"]
        if s["title"] == "Architecture Overview"
    )
    assert moved["anchorId"] == base_arch["anchorId"]
    assert moved["decision"] == "unchanged"


def test_merge_case_pins_surviving_identity():
    """Merging two sections keeps the surviving heading's anchor (edited
    content under a kept heading) and retires the absorbed anchor."""
    base = {s["title"]: s for s in load_expected("base")["sections"]}
    merged = {s["title"]: s for s in load_expected("merge")["sections"]}
    survivor = merged["Data Residency"]
    assert survivor["anchorId"] == base["Data Residency"]["anchorId"]
    assert survivor["decision"] == "heading-kept"
    # the absorbed section's heading and anchor are gone — never transferred
    assert "Access Control" not in merged
    absorbed_anchor = base["Access Control"]["anchorId"]
    assert all(s["anchorId"] != absorbed_anchor for s in load_expected("merge")["sections"])


def test_rename_plus_split_case_pins_lineage():
    """A renamed section that also grew past the size bound: part 1 inherits
    the original anchor (citation lineage survives); part 2 is minted under
    the new heading's slug."""
    base = {s["title"]: s for s in load_expected("base")["sections"]}
    renamed = load_expected("rename-split")["sections"]
    parts = [s for s in renamed if s["title"] == "Access Governance"]
    assert len(parts) == 2
    old_anchor = base["Access Control"]["anchorId"]
    assert parts[0]["anchorId"] == old_anchor
    assert parts[0]["decision"] in ("inherited-exact", "inherited-similar")
    assert parts[0]["inheritedFrom"] == old_anchor
    assert parts[1]["decision"] == "minted"
    assert parts[1]["anchorId"] != old_anchor
    assert parts[1]["anchorId"].endswith(".p2")


def test_oscillation_case_pins_stable_round_trip():
    """small -> big (split, lineage through .p1) -> small again (the bare
    heading anchor is restored, byte-identically)."""
    small = load_expected("oscillate-base")["sections"]
    grown = load_expected("oscillate-grow")["sections"]
    shrunk = load_expected("oscillate-shrink")["sections"]
    base_anchor = small[0]["anchorId"]
    assert grown[0]["anchorId"] == f"{base_anchor}.p1"
    assert grown[0]["decision"] == "split-lineage"
    assert grown[0]["inheritedFrom"] == base_anchor
    assert shrunk[0]["anchorId"] == base_anchor
    # identical inputs at rest reproduce identical outputs
    assert shrunk[0]["textSha256"] == small[0]["textSha256"]


# --------------------------------------------------------------------------- #
# integration golden: the ACTUAL M2 -> M3 finalization path
# --------------------------------------------------------------------------- #


def test_integration_golden_finalization_matches_corpus(
    alice, session_factory, db_session, monkeypatch
):
    """Upload the base fixture through the real API, run the real M2 ingest
    and M3 finalization pipeline (worker, database, persistence), and compare
    the PERSISTED identity surfaces to the committed golden expectation —
    no harness-side reconstruction of pipeline metadata."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.ingestion.worker import IngestionWorker
    from app.models.db_models import Document, DocumentSection, DocumentVersion

    monkeypatch.setattr(get_settings(), "evidentia_tenant_corpus_enabled", True)

    payload = (FIXTURES_DIR / "base.md").read_bytes()
    res = alice.post(
        "/api/documents/upload", files={"file": ("base.md", payload, "text/markdown")}
    )
    assert res.status_code == 202, res.text
    document_id = res.json()["documentId"]

    worker = IngestionWorker(session_factory, poll_seconds=0.01, max_attempts=3)
    while worker.process_one():
        pass
    res = alice.post(f"/api/documents/{document_id}/finalize")
    assert res.status_code == 202, res.text
    while worker.process_one():
        pass

    successor = db_session.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_no.desc())
    ).scalars().first()
    assert successor.status == "ready"

    document = db_session.execute(
        select(Document).where(Document.id == document_id)
    ).scalar_one()
    prefix = document.citation_prefix
    assert prefix

    rows = db_session.execute(
        select(DocumentSection)
        .where(DocumentSection.version_id == successor.id)
        .order_by(DocumentSection.ordinal.asc())
    ).scalars().all()

    expected = load_expected("base")
    assert successor.finalization_engine == expected["finalizationTarget"]
    assert successor.engine_versions["target"] == expected["finalizationTarget"]
    assert len(rows) == len(expected["sections"])
    for row, exp in zip(rows, expected["sections"]):
        assert row.ordinal == exp["ordinal"]
        assert row.anchor_id == exp["anchorId"]
        assert row.anchor_provenance["decision"] == exp["decision"]
        assert row.text_sha256 == exp["textSha256"]
        assert row.category == exp["category"]
        assert row.matched_rules == exp["matchedRules"]
        # signatures are prefix-independent (they commit to the anchor and
        # heading input, not the tenant prefix): must match the golden values
        assert row.classification_signature == exp["classificationSignature"]
        # citation ids differ from the golden fixture ONLY by tenant prefix
        assert row.citation_id == f"{prefix}-{row.anchor_id}"
        golden_citation = exp["citationId"]
        assert golden_citation == f"{GOLDEN_PREFIX}-{exp['anchorId']}"
    assert (
        successor.classification_signature == expected["versionClassificationSignature"]
    )
