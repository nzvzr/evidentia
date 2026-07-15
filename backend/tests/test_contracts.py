"""Typed platform contracts (M1).

The load-bearing property is compatibility: the pipeline currency dict every
scorer/gate/binder consumes today must be a strict projection of
`SectionRecord v1`, so the tenant corpus can slot in at M4 without a single
downstream change. The rest is contract hygiene: closed vocabularies are
closed, identity fields are required, and instances are immutable.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from app.agents.document_reader import document_reader
from app.contracts import (
    CLAIM_FAMILIES,
    DOC_BLOCK_KINDS,
    CanonicalAnalysisDocument,
    ClaimCandidate,
    ClaimSpec,
    DocBlock,
    DocIR,
    EvidenceBinding,
    Finding,
    RawDocument,
    RawDocumentOrigin,
    Recommendation,
    SectionRecord,
    SectionRef,
)


def make_section_record(**overrides) -> SectionRecord:
    base = dict(
        document_id="data-residency-sovereignty-policy",
        version_id="v-1",
        anchor_id="k3f9x",
        citation_id="RES-14",
        heading_path=("Data Residency", "Default processing"),
        title="Default processing regions",
        ordinal=0,
        depth=2,
        text="Customer data is processed in the region selected at onboarding.",
        excerpt="Customer data is processed in the region selected at onboarding.",
        text_sha256="0" * 64,
        token_set=frozenset({"customer", "data", "region"}),
        char_count=65,
        category="Compliance",
    )
    base.update(overrides)
    return SectionRecord(**base)


class TestSectionRecordProjection:
    def test_projection_matches_pipeline_currency_shape_exactly(self):
        """The demo reader's dict is the pipeline-wide currency; the projection
        must produce exactly its key set — no more (nothing internal may leak),
        no less (nothing downstream may go missing)."""
        _, sections = document_reader([])
        assert sections, "demo corpus must yield sections"
        currency_keys = set(sections[0].keys())

        projected = make_section_record().to_pipeline_section("Data Residency & Sovereignty Policy")
        assert set(projected.keys()) == currency_keys

    def test_projection_values_are_field_for_field(self):
        record = make_section_record()
        projected = record.to_pipeline_section("Data Residency & Sovereignty Policy")
        assert projected == {
            "documentId": "data-residency-sovereignty-policy",
            "source": "Data Residency & Sovereignty Policy",
            "sectionTitle": "Default processing regions",
            "excerpt": record.excerpt,
            "category": "Compliance",
            "citationId": "RES-14",
        }

    def test_identity_fields_are_required(self):
        for field_name in ("document_id", "version_id", "anchor_id", "citation_id"):
            with pytest.raises(ValueError, match=field_name):
                make_section_record(**{field_name: ""})

    def test_records_are_immutable(self):
        record = make_section_record()
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.category = "Security"  # type: ignore[misc]


class TestDocIR:
    def test_block_kinds_are_a_closed_set(self):
        for kind in DOC_BLOCK_KINDS:
            DocBlock(kind=kind, text="x")
        with pytest.raises(ValueError, match="unknown DocIR block kind"):
            DocBlock(kind="image", text="x")

    def test_heading_level_must_be_positive_when_present(self):
        DocBlock(kind="heading", text="Title", level=1)
        with pytest.raises(ValueError, match="level"):
            DocBlock(kind="heading", text="Title", level=0)

    def test_docir_is_an_ordered_block_stream(self):
        ir = DocIR(blocks=(DocBlock(kind="heading", text="A", level=1), DocBlock(kind="paragraph", text="b")))
        assert [b.kind for b in ir.blocks] == ["heading", "paragraph"]
        assert DocIR.contract_version == 1


class TestRawDocument:
    def _origin(self, source_type="upload"):
        return RawDocumentOrigin(source_type=source_type)

    def test_known_and_connector_source_types_accepted(self):
        self._origin("upload")
        self._origin("api")
        self._origin("connector:sharepoint")
        with pytest.raises(ValueError, match="source_type"):
            self._origin("ftp")

    def test_tenant_ref_required(self):
        with pytest.raises(ValueError, match="tenant_ref"):
            RawDocument(
                data=b"x",
                declared_mime="text/plain",
                origin=self._origin(),
                tenant_ref="",
                received_at=datetime.now(timezone.utc),
            )


class TestClaimContracts:
    def test_claim_families_are_a_closed_set(self):
        for family in CLAIM_FAMILIES:
            ClaimSpec(id="compliance.x", module="compliance", version="1.0.0", family=family)
        with pytest.raises(ValueError, match="family"):
            ClaimSpec(id="compliance.x", module="compliance", version="1.0.0", family="risk")

    def test_evidence_binding_decision_is_closed(self):
        ref = SectionRef(document_id="d", version_id="v", anchor_id="a")
        for decision in ("accepted", "insufficient"):
            EvidenceBinding(
                claim_ref="c",
                section_ref=ref,
                citation_id="RES-14",
                matched_signals=("residency",),
                matched_phrases=(),
                support_score=3.0,
                threshold_policy_version=None,
                decision=decision,
            )
        with pytest.raises(ValueError, match="decision"):
            EvidenceBinding(
                claim_ref="c",
                section_ref=ref,
                citation_id="RES-14",
                matched_signals=(),
                matched_phrases=(),
                support_score=0.0,
                threshold_policy_version=None,
                decision="rejected",
            )

    def test_claim_candidate_requires_exactly_one_source(self):
        ClaimCandidate(spec_ref="compliance.x@1.0.0")
        ClaimCandidate(proposer_ref={"kind": "llm", "model": "m", "promptVersion": "1"})
        with pytest.raises(ValueError, match="exactly one"):
            ClaimCandidate()
        with pytest.raises(ValueError, match="exactly one"):
            ClaimCandidate(spec_ref="x", proposer_ref={"kind": "llm"})


class TestVersioning:
    def test_every_contract_declares_version_1(self):
        for contract in (
            RawDocument,
            DocIR,
            SectionRecord,
            EvidenceBinding,
            ClaimSpec,
            ClaimCandidate,
            Finding,
            Recommendation,
            CanonicalAnalysisDocument,
        ):
            assert contract.contract_version == 1
