"""Unit tests for the auto intensity router."""

from app.agents.mode_router import RoutingSignals, route_intensity


def signals(**kw):
    base = dict(
        document_complexity=3,
        contradictions=0,
        citation_coverage=85.0,
        persona_complexity=0,
        deterministic_confidence=88,
    )
    base.update(kw)
    return RoutingSignals(**base)


def test_insufficient_evidence_routes_to_summary():
    assert route_intensity(signals(document_complexity=1)) == "summary"
    assert route_intensity(signals(document_complexity=0)) == "summary"


def test_contradictions_route_to_full():
    assert route_intensity(signals(contradictions=1)) == "full"


def test_custom_persona_routes_to_full():
    assert route_intensity(signals(persona_complexity=1)) == "full"


def test_large_corpus_routes_to_full():
    assert route_intensity(signals(document_complexity=6)) == "full"


def test_low_confidence_routes_to_full():
    assert route_intensity(signals(deterministic_confidence=80)) == "full"


def test_easy_high_confidence_routes_to_off():
    assert route_intensity(
        signals(document_complexity=3, deterministic_confidence=94, citation_coverage=92)
    ) == "off"


def test_medium_case_routes_to_summary():
    # Not easy enough for off, not hard enough for full.
    assert route_intensity(
        signals(document_complexity=3, deterministic_confidence=88, citation_coverage=82)
    ) == "summary"


def test_off_requires_all_easy_conditions():
    # High confidence but low coverage should not downgrade to off.
    assert route_intensity(
        signals(document_complexity=3, deterministic_confidence=95, citation_coverage=80)
    ) == "summary"
