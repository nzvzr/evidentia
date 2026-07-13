"""Unit tests for the calibrated, conservative auto intensity router."""

from app.agents.mode_router import RoutingSignals, route_intensity


def signals(**kw):
    """A healthy, well-grounded baseline by default (routes to summary)."""
    base = dict(
        deterministic_structural_score=75.0,
        deterministic_narrative_score=90.0,
        document_complexity=3,
        contradictions=0,
        persona_complexity=0,
        deterministic_confidence=88,
        citation_coverage=85.0,
        grounded_risks_kept=3,
        grounded_workflow_steps_kept=4,
        unsupported_risks_dropped=0,
        insufficient_evidence_items=0,
        source_document_mismatch=0,
        evidence_support_score_avg=10.0,
        evidence_support_score_min=8.0,
    )
    base.update(kw)
    return RoutingSignals(**base)


def _strong_full_case(**kw):
    """Clear analytical weakness + strong evidence + multiple opportunity signals."""
    base = dict(
        deterministic_structural_score=45.0,   # weak
        deterministic_narrative_score=70.0,    # weak
        deterministic_confidence=75,           # weak / low
        document_complexity=5,
        contradictions=2,                      # multiple contradictions
        persona_complexity=1,
        citation_coverage=88.0,
        grounded_risks_kept=4,
        grounded_workflow_steps_kept=5,
        unsupported_risks_dropped=3,
        insufficient_evidence_items=0,
        source_document_mismatch=0,
        evidence_support_score_avg=11.0,
        evidence_support_score_min=8.0,
    )
    base.update(kw)
    return RoutingSignals(**base)


def test_high_confidence_simple_chooses_off_or_summary():
    d = route_intensity(signals(deterministic_confidence=94, citation_coverage=92,
                                deterministic_narrative_score=93.0))
    assert d.mode in ("off", "summary")
    assert d.mode == "off"  # strong baseline → deterministic is enough


def test_insufficient_evidence_never_full():
    d = route_intensity(signals(document_complexity=1, grounded_risks_kept=0,
                                grounded_workflow_steps_kept=1))
    assert d.mode != "full"
    # even if analytical scores look weak, no evidence → not full
    d2 = route_intensity(signals(document_complexity=1, grounded_risks_kept=0,
                                 deterministic_structural_score=30.0,
                                 deterministic_narrative_score=50.0))
    assert d2.mode != "full"


def test_custom_persona_alone_does_not_force_full():
    d = route_intensity(signals(persona_complexity=1))
    assert d.mode != "full"


def test_single_contradiction_alone_does_not_force_full():
    d = route_intensity(signals(contradictions=1))
    assert d.mode != "full"


def test_high_doc_count_alone_does_not_force_full():
    d = route_intensity(signals(document_complexity=8))
    assert d.mode != "full"


def test_slightly_low_confidence_alone_does_not_force_full():
    d = route_intensity(signals(deterministic_confidence=82))
    assert d.mode != "full"


def test_full_requires_multiple_strong_signals():
    d = route_intensity(_strong_full_case())
    assert d.mode == "full"
    assert d.predicted_incremental_gain > 0.2
    assert d.full_eligibility["analyticalWeakness"] is True
    assert d.full_eligibility["evidenceSufficient"] is True


def test_tie_break_prefers_cheaper_mode():
    # exactly at the gain threshold (not strictly greater) → cheaper summary wins
    d = route_intensity(_strong_full_case(), full_gain_threshold=0.75)
    assert d.mode == "summary"
    # a single opportunity signal is not enough → summary (cheaper) over full
    d2 = route_intensity(signals(deterministic_structural_score=45.0))
    assert d2.mode in ("summary", "off")


def test_router_is_deterministic():
    s = _strong_full_case()
    assert route_intensity(s).mode == route_intensity(s).mode
    assert route_intensity(s).as_telemetry() == route_intensity(s).as_telemetry()


def test_full_needs_evidence_even_with_weakness():
    # weak analytics but source mismatch present → evidence insufficient → not full
    d = route_intensity(_strong_full_case(source_document_mismatch=2))
    assert d.mode != "full"
    d2 = route_intensity(_strong_full_case(insufficient_evidence_items=3))
    assert d2.mode != "full"
