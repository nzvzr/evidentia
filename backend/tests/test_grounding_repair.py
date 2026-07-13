"""Tests for the deterministic grounding repair stage."""

from app.agents.document_reader import document_reader
from app.tools.citation_tools import INSUFFICIENT_EVIDENCE, count_ungrounded, repair_grounding

DOCS = ["incident-response-runbook"]
_sections = document_reader(DOCS)[1]
AVAILABLE = {s["citationId"] for s in _sections}


def test_repairs_invalid_code_with_relevant_citation():
    workflow = [{"step": 1, "title": "Study the deprecated escalation tool notice",
                 "description": "Replace PagerTree references", "evidenceCode": "RES-14"}]
    risks = []
    info = repair_grounding(workflow, risks, _sections)
    assert info["before"] == 1
    assert info["after"] == 0
    assert info["repairs"] == 1
    # replaced with a real INC citation, never invented
    assert workflow[0]["evidenceCode"] in AVAILABLE


def test_marks_insufficient_when_no_relevant_citation():
    risks = [{"severity": "High", "title": "Zzgibberish qwerty flurblewock",
              "description": "nonsense unrelated content", "businessImpact": "b",
              "evidenceCode": "FAKE-9", "recommendedFix": "f", "owner": "o"}]
    info = repair_grounding([], risks, _sections)
    assert info["before"] == 1
    assert risks[0]["evidenceCode"] == INSUFFICIENT_EVIDENCE
    assert info["after"] == 0  # sentinel is not counted as ungrounded


def test_valid_codes_are_left_untouched():
    valid = next(iter(AVAILABLE))
    workflow = [{"step": 1, "title": "Confirm severity", "description": "d", "evidenceCode": valid}]
    info = repair_grounding(workflow, [], _sections)
    assert info["repairs"] == 0
    assert workflow[0]["evidenceCode"] == valid


def test_count_ungrounded_ignores_sentinel_and_empty():
    assert count_ungrounded(["INC-2.1", INSUFFICIENT_EVIDENCE, "", "FAKE-1"], AVAILABLE) == 1
