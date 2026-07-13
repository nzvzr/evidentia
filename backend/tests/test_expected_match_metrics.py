"""Tests for the four ground-truth risk/evidence match metrics."""

from app.eval.metrics import expected_match_metrics


def _report(codes, risk_titles=None):
    risks = []
    titles = risk_titles or ["Risk"] * len(codes)
    for code, title in zip(codes, titles):
        risks.append({"evidenceCode": code, "title": title, "description": ""})
    return {"risks": risks}


def test_exact_match_scores_all_four():
    rep = _report(["RES-14"], ["Data residency gap"])
    exp = {"evidenceCodes": ["RES-14"], "summaryConcepts": ["residency"]}
    m = expected_match_metrics(rep, exp)
    assert m["expectedCitationExactMatchRate"] == 1.0
    assert m["expectedCitationFamilyMatchRate"] == 1.0
    assert m["expectedSourceDocumentMatchRate"] == 1.0
    assert m["expectedRiskConceptRecall"] == 1.0


def test_same_document_different_section_is_family_not_exact():
    # correct risk + correct document, different valid section (RES-9 vs RES-14)
    rep = _report(["RES-9"], ["Data residency gap"])
    exp = {"evidenceCodes": ["RES-14"], "summaryConcepts": ["residency"]}
    m = expected_match_metrics(rep, exp)
    assert m["expectedCitationExactMatchRate"] == 0.0
    assert m["expectedCitationFamilyMatchRate"] == 1.0
    assert m["expectedSourceDocumentMatchRate"] == 1.0
    assert m["expectedRiskConceptRecall"] == 1.0


def test_wrong_document_right_concept_is_concept_only():
    # residency concept present in the title, but grounded in a security citation
    rep = _report(["SEC-4.2"], ["Data residency gap for EMEA"])
    exp = {"evidenceCodes": ["RES-14"], "summaryConcepts": ["residency"]}
    m = expected_match_metrics(rep, exp)
    assert m["expectedCitationExactMatchRate"] == 0.0
    assert m["expectedCitationFamilyMatchRate"] == 0.0
    assert m["expectedSourceDocumentMatchRate"] == 0.0
    assert m["expectedRiskConceptRecall"] == 1.0


def test_missing_concept_recall_zero():
    rep = _report(["SEC-4.2"], ["Unrelated pricing note"])
    exp = {"evidenceCodes": ["RES-14"], "summaryConcepts": ["residency"]}
    m = expected_match_metrics(rep, exp)
    assert m["expectedRiskConceptRecall"] == 0.0


def test_no_ground_truth_returns_none():
    m = expected_match_metrics(_report(["RES-14"]), {})
    assert m["expectedCitationExactMatchRate"] is None
    assert m["expectedRiskConceptRecall"] is None


def test_partial_exact_match_rate():
    rep = _report(["RES-14", "SEC-5.1"], ["residency", "security"])
    exp = {"evidenceCodes": ["RES-14", "SEC-4.2"]}
    m = expected_match_metrics(rep, exp)
    assert m["expectedCitationExactMatchRate"] == 0.5   # only RES-14 exact
    assert m["expectedCitationFamilyMatchRate"] == 1.0  # RES + SEC families both present
    assert m["expectedSourceDocumentMatchRate"] == 1.0
