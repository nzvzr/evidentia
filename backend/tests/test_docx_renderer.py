"""Unit and safety tests for the DOCX renderer (Phase 10).

These exercise the renderer as a pure function — no database, no network, no
FastAPI — over hand-built persisted snapshots. They assert the DOCX is a valid,
editable Word document, that optional sections are honestly omitted, that
untrusted text cannot corrupt the output or escape the filename, and that the
output is deterministic.
"""

from __future__ import annotations

import io
import zipfile
from xml.dom import minidom

import pytest

from app.renderers.docx_renderer import DocxRenderer, RENDERER_VERSION
from app.renderers.protocol import RendererError, RendererOptions
from app.renderers.sanitize import clean_text, safe_filename, slugify
from app.renderers.snapshot import ReportSnapshot, TenantDisplay

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _report(**overrides):
    base = {
        "id": "abc123def456",
        "company": "Northreach Cloud",
        "market": "EMEA",
        "persona": "Support Agent",
        "customPersona": "",
        "category": "Support",
        "generatedAt": "2026-07-18T09:30:00Z",
        "confidence": 88,
        "summary": "Executive summary text for the report.",
        "topFinding": "The main blocker is data residency, supported by ACME-SEC-1.",
        "generationMode": "deterministic",
        "llmProvider": "none",
        "personaBrief": {
            "title": "Support Agent",
            "description": "Handles customer tickets with cited answers.",
            "goals": ["Resolve tickets fast", "Cite every claim"],
            "priorities": ["Accuracy", "SLA compliance"],
            "relevantTopics": ["Security"],
            "riskFocus": ["Residency"],
            "outputStyle": "Concise, cited",
            "isCustom": False,
        },
        "workflowSteps": [
            {
                "step": 1,
                "title": "Verify entitlement",
                "description": "Check the tier.",
                "whyItMatters": "Avoid over-promising.",
                "expectedOutput": "Confirmed tier",
                "evidenceCode": "ACME-SEC-1",
            },
            {
                "step": 2,
                "title": "Draft reply",
                "description": "Cited response.",
                "whyItMatters": "Trust.",
                "expectedOutput": "Draft",
                "evidenceCode": "N/A",
            },
        ],
        "risks": [
            {
                "severity": "High",
                "title": "Residency gap",
                "description": "Metadata routed abroad.",
                "businessImpact": "Compliance breach",
                "recommendedFix": "Pin region",
                "owner": "Compliance",
                "evidenceCode": "ACME-SEC-1",
            },
            {
                "severity": "Medium",
                "title": "SLA ambiguity",
                "description": "Unclear tiers.",
                "businessImpact": "Disputes",
                "recommendedFix": "Clarify",
                "owner": "Legal",
                "evidenceCode": "N/A",
            },
        ],
        "citations": [
            {
                "id": "ACME-SEC-1",
                "source": "Security Policy · Access",
                "section": "Access",
                "excerpt": "Administrative access requires MFA.",
                "whyItMatters": "Grounds the residency risk.",
            }
        ],
        "metrics": {
            "documentsAnalyzed": 3,
            "passagesIndexed": 123,
            "citationsUsed": 1,
            "risksFlagged": 2,
            "confidence": 88,
            "personaRelevanceScore": 90,
            "workflowCompleteness": 80,
            "citationCoverage": 75,
            "complianceSensitivity": "High",
            "documentRelevance": [{"document": "Security Policy", "score": 92}],
        },
        "suggestedActions": [
            {"title": "Open residency gap", "detail": "Escalate to engineering."}
        ],
        "agentSteps": [
            {"agent": "Document Ingest", "status": "complete", "detail": "Parsed 3 docs", "duration": "0.6s"}
        ],
    }
    base.update(overrides)
    return base


def _audit(**overrides):
    base = {
        "corpusMode": "tenant",
        "corpusSnapshotDigest": "tcs1:" + "a" * 64,
        "retrievalEngineVersion": "tenant-lexical-v1",
        "orchestratorVersion": "evidentia-orchestrator-v1",
        "executionMode": "deterministic",
        "llmProvider": None,
        "llmModel": None,
        "sourceVersionCount": 1,
        "evidenceSectionCount": 1,
        "generationStatus": "completed",
        "sourceVersions": [
            {
                "documentId": "doc-1",
                "documentVersionId": "ver-2",
                "versionNo": 2,
                "manifestSha256": "b" * 64,
                "finalizationTargetDigest": "cft1:" + "c" * 64,
                "position": 0,
            }
        ],
        "evidenceBindings": [
            {
                "documentId": "doc-1",
                "documentVersionId": "ver-2",
                "documentTitle": "Security Policy",
                "originalFilename": "sec.md",
                "sectionOrdinal": 3,
                "headingPath": ["Security", "Access"],
                "sectionTitle": "Access",
                "anchorId": "anchor-1",
                "citationId": "ACME-SEC-1",
                "sectionSignature": "d" * 64,
                "retrievalRank": 1,
                "retrievalScore": 9.0,
                "selectedForPrompt": True,
                "citedInFinal": True,
                "excerpt": "Administrative access requires MFA.",
            }
        ],
    }
    base.update(overrides)
    return base


def _tenant():
    return TenantDisplay(company_name="Acme Corp", company_id="co-1")


def _render(report=None, audit="default", options=None):
    if report is None:
        report = _report()
    if audit == "default":
        audit = _audit()
    snapshot = ReportSnapshot.from_persisted(report, audit, _tenant())
    return DocxRenderer().render(snapshot, options or RendererOptions())


def _zip(artifact):
    return zipfile.ZipFile(io.BytesIO(artifact.data))


def _document_xml(artifact) -> str:
    return _zip(artifact).read("word/document.xml").decode("utf-8")


# --- valid container -------------------------------------------------------


def test_output_is_a_valid_docx_zip_with_required_parts():
    artifact = _render()
    assert artifact.content_type == DOCX_CONTENT_TYPE
    assert artifact.filename.endswith(".docx")
    zf = _zip(artifact)
    names = set(zf.namelist())
    for required in (
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
        "docProps/core.xml",
    ):
        assert required in names, f"missing part {required}"
    assert zf.testzip() is None  # no corrupt entries


def test_document_xml_parses():
    artifact = _render()
    # Raises on malformed XML.
    minidom.parseString(_document_xml(artifact))


def test_headings_and_sections_present():
    text = _document_xml(_render())
    for heading in (
        "Executive summary",
        "Analysis overview",
        "Recommended workflow",
        "Risk register",
        "Recommendations",
        "Evidence &amp; citations",
        "Audit appendix",
    ):
        assert heading in text, f"expected section heading: {heading!r}"


def test_named_styles_are_registered():
    styles = _zip(_render()).read("word/styles.xml").decode("utf-8")
    for name in ("Evidence Quote", "Citation", "Risk High", "Metadata", "Table Header"):
        assert name in styles, f"missing named style {name!r}"


def test_tables_are_real_word_tables():
    text = _document_xml(_render())
    assert "<w:tbl>" in text or "<w:tbl " in text
    # The risk register header must be a table header cell, not an image.
    assert "Business impact" in text
    assert "Mitigation" in text


def test_repeating_table_header_is_marked():
    text = _document_xml(_render())
    assert "tblHeader" in text


# --- citations from source audit ------------------------------------------


def test_citations_resolve_from_source_audit_not_current_version():
    text = _document_xml(_render())
    # Version + section come from the report-local binding, not a live lookup.
    assert "Version ver-2" in text
    assert "Section 4" in text  # sectionOrdinal 3 → 1-based 4
    assert "Administrative access requires MFA." in text


def test_source_appendix_lists_frozen_versions():
    text = _document_xml(_render())
    assert "Source appendix" in text
    assert "Source versions" in text
    assert "ver-2" in text


# --- frozen binding excerpt is authoritative (post-review correction) ------
#
# The evidence quote and provenance for a citation must come from the frozen M4
# source-audit binding, never from the loosely-typed report_json projection —
# and binding metadata must never be combined with a report_json excerpt.


def _stale_citation(cid="ACME-SEC-1"):
    """A citation whose report_json excerpt/source deliberately differ from the
    frozen binding, so a test can prove which one the DOCX actually shows."""
    return {
        "id": cid,
        "source": "REPORTJSON source label (stale)",
        "section": "REPORTJSON section (stale)",
        "excerpt": "REPORTJSON excerpt that must never appear as evidence.",
        "whyItMatters": "Grounds the residency risk.",
    }


def _frozen_binding(cid="ACME-SEC-1"):
    return {
        "documentId": "doc-1",
        "documentVersionId": "ver-frozen-9",
        "documentTitle": "Frozen Source Title",
        "originalFilename": "frozen.md",
        "sectionOrdinal": 6,
        "headingPath": ["Frozen", "Path"],
        "sectionTitle": "Frozen Section",
        "anchorId": "anchor-9",
        "citationId": cid,
        "sectionSignature": "e" * 64,
        "retrievalRank": 1,
        "retrievalScore": 9.0,
        "selectedForPrompt": True,
        "citedInFinal": True,
        "excerpt": "FROZEN audit excerpt: the only evidence quote.",
    }


def test_bound_citation_shows_frozen_binding_excerpt_only():
    # (1) binding excerpt differs from the report_json excerpt;
    # (2) the DOCX displays ONLY the binding excerpt.
    report = _report(citations=[_stale_citation()])
    audit = _audit(evidenceBindings=[_frozen_binding()])
    text = _document_xml(_render(report, audit))

    assert "FROZEN audit excerpt: the only evidence quote." in text
    assert "REPORTJSON excerpt that must never appear as evidence." not in text
    # Title, version, section and id all come from the same frozen record —
    # never the stale report_json source/section labels.
    assert "Frozen Source Title" in text
    assert "Version ver-frozen-9" in text
    assert "Section 7" in text  # sectionOrdinal 6 → 1-based 7
    assert "REPORTJSON source label (stale)" not in text
    assert "REPORTJSON section (stale)" not in text


def test_tenant_citation_without_binding_labels_audit_unavailable():
    # (3) A tenant report whose citation has no binding must label the source
    # audit unavailable and must NOT show the report_json excerpt as evidence.
    report = _report(
        citations=[
            {
                "id": "UNBOUND-1",
                "source": "Some report source",
                "section": "Some report section",
                "excerpt": "UNVERIFIED report-json text, not frozen evidence.",
                "whyItMatters": "w",
            }
        ]
    )
    audit = _audit(corpusMode="tenant", evidenceBindings=[])
    text = _document_xml(_render(report, audit))

    assert "Source audit unavailable for this citation" in text
    assert "UNVERIFIED report-json text, not frozen evidence." not in text


def test_legacy_demo_citation_without_binding_preserves_excerpt_honestly():
    # (4) Legacy demo compatibility: with an EXPLICIT demo corpus, an unbound
    # citation keeps its report_json excerpt, but is never implied to be frozen
    # source-audit evidence.
    report = _report(
        citations=[
            {
                "id": "DEMO-1",
                "source": "Demo report source",
                "section": "Demo report section",
                "excerpt": "Demo excerpt kept for compatibility.",
                "whyItMatters": "w",
            }
        ]
    )
    audit = _audit(corpusMode="demo", evidenceBindings=[])
    text = _document_xml(_render(report, audit))

    assert "Demo excerpt kept for compatibility." in text
    assert "frozen source-audit binding exists for this demo citation" in text
    assert "Source audit unavailable" not in text


def test_live_current_version_pointer_cannot_alter_frozen_excerpt():
    # (5) A live "current version" pointer is not a renderer input. Two snapshots
    # differing only in such a field render identically, and the evidence always
    # comes from the frozen binding.
    audit = _audit(evidenceBindings=[_frozen_binding()])
    cit = _stale_citation()
    a = _render(_report(citations=[cit], currentVersionId="ver-CURRENT-500"), audit)
    b = _render(_report(citations=[cit], currentVersionId="ver-CURRENT-999"), audit)

    assert a.content_hash == b.content_hash
    assert a.semantic_digest == b.semantic_digest

    text = _document_xml(a)
    assert "FROZEN audit excerpt: the only evidence quote." in text
    assert "Version ver-frozen-9" in text
    assert "ver-CURRENT-500" not in text
    assert "ver-CURRENT-999" not in text
    assert "REPORTJSON excerpt that must never appear as evidence." not in text


# --- optional sections omitted honestly -----------------------------------


def test_empty_workflow_is_labelled_not_faked():
    text = _document_xml(_render(_report(workflowSteps=[])))
    assert "No workflow steps could be grounded" in text


def test_empty_risks_are_labelled_not_faked():
    text = _document_xml(_render(_report(risks=[])))
    assert "No risks met the evidence-support threshold" in text


def test_missing_source_audit_is_handled_honestly():
    artifact = _render(audit=None)
    text = _document_xml(artifact)
    assert "No report-local source audit was available" in text
    # No fabricated version identifiers.
    assert "Version ver-2" not in text
    assert artifact.telemetry["auditPresent"] is False


def test_table_of_contents_can_be_omitted():
    with_toc = _document_xml(_render(options=RendererOptions(include_table_of_contents=True)))
    without = _document_xml(_render(options=RendererOptions(include_table_of_contents=False)))
    assert "TOC" in with_toc
    assert "Update Field" in with_toc
    assert "Right-click and choose" not in without


def test_old_demo_report_without_optional_fields_still_renders():
    legacy = {
        "id": "legacy-1",
        "company": "Northreach Cloud",
        "market": "EMEA",
        "persona": "Support Agent",
        "summary": "A legacy summary.",
        "citations": [],
        "risks": [],
        "workflowSteps": [],
    }
    artifact = _render(legacy, audit=None)
    minidom.parseString(_document_xml(artifact))
    assert artifact.byte_size > 0


# --- safety ---------------------------------------------------------------


def test_invalid_xml_characters_are_stripped():
    hostile = _report(summary="Bad \x00\x01\x08\x0b\x0c\x1f control chars kept text")
    text = _document_xml(_render(hostile))
    minidom.parseString(text)  # must still parse
    for illegal in ("\x00", "\x01", "\x08", "\x0b", "\x0c", "\x1f"):
        assert illegal not in text
    assert "control chars kept text" in text  # legitimate text preserved


def test_hostile_xml_markup_is_escaped_not_executed():
    hostile = _report(topFinding="<script>alert('x')</script> & <w:body/> injection")
    text = _document_xml(_render(hostile))
    minidom.parseString(text)
    # The angle brackets are escaped; no raw injected element appears.
    assert "&lt;script&gt;" in text
    assert "<script>" not in text


def test_hostile_title_cannot_alter_filename_path():
    hostile = _report(persona="../../etc/passwd", market="..\\..\\windows", id="../../../x")
    artifact = _render(hostile)
    assert "/" not in artifact.filename
    assert "\\" not in artifact.filename
    assert ".." not in artifact.filename
    assert artifact.filename.endswith(".docx")


def test_no_external_relationships():
    zf = _zip(_render())
    for name in zf.namelist():
        if name.endswith(".rels"):
            assert 'TargetMode="External"' not in zf.read(name).decode("utf-8")


def test_no_macros_in_output():
    zf = _zip(_render())
    names = zf.namelist()
    assert not any(n.endswith("vbaProject.bin") for n in names)
    content_types = zf.read("[Content_Types].xml").decode("utf-8")
    assert "macroEnabled" not in content_types


def test_output_size_cap_is_enforced():
    with pytest.raises(RendererError) as excinfo:
        _render(options=RendererOptions(max_output_bytes=1024))
    assert excinfo.value.code == "export_too_large"


# --- determinism ----------------------------------------------------------


def test_bytes_are_deterministic_for_identical_input():
    a = _render()
    b = _render()
    assert a.data == b.data
    assert a.content_hash == b.content_hash


def test_semantic_digest_is_deterministic_and_container_independent():
    a = _render()
    b = _render()
    assert a.semantic_digest == b.semantic_digest


def test_different_content_changes_the_digests():
    a = _render()
    b = _render(_report(summary="A completely different summary."))
    assert a.content_hash != b.content_hash
    assert a.semantic_digest != b.semantic_digest


def test_no_wallclock_timestamp_in_core_properties():
    # created/modified must equal the persisted generatedAt, not "now".
    core = _zip(_render()).read("docProps/core.xml").decode("utf-8")
    assert "2026-07-18T09:30:00" in core
    # A pinned epoch is used when generatedAt is absent — never the wall clock.
    core2 = _zip(_render(_report(generatedAt=""))).read("docProps/core.xml").decode("utf-8")
    assert "2001-01-01T00:00:00" in core2


def test_renderer_metadata_is_pinned():
    artifact = _render()
    assert artifact.renderer_version == RENDERER_VERSION
    assert RENDERER_VERSION in _document_xml(artifact)


# --- sanitize unit --------------------------------------------------------


def test_clean_text_bounds_length():
    assert len(clean_text("x" * 100_000, limit=100)) <= 100


def test_slugify_is_path_safe():
    assert slugify("../../Etc/Passwd!!") == "etc-passwd"
    assert slugify("") == "report"


def test_safe_filename_shape():
    name = safe_filename("Support Agent", "EMEA", "abc12345")
    assert name == "evidentia-support-agent-emea-abc12345.docx"
