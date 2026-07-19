"""Regression metrics for the intentionally small M5a claim fixture pack.

These metrics prove determinism and catch regressions. They are not a claim of
statistical production quality; M5b supplies design-partner content volume.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def claim_fixture_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    positives = [row for row in values if row["expectedDecision"] == "accepted"]
    negatives = [row for row in values if row["expectedDecision"] != "accepted"]
    accepted = [row for row in values if row["actualDecision"] == "accepted"]
    true_positive = sum(row["expectedDecision"] == "accepted" for row in accepted)
    false_positive = sum(row["expectedDecision"] != "accepted" for row in accepted)
    insufficient = [row for row in values if row["expectedDecision"] == "insufficient_evidence"]
    llm = [row for row in values if row.get("candidateSource") == "llm_proposal"]
    accepted_binding_complete = sum(
        bool(row.get("acceptedBindingIds")) for row in accepted
    )
    accepted_citations_valid = sum(
        bool(row.get("acceptedBindingIds"))
        and set(row.get("acceptedBindingIds", ())) <= set(row.get("allowedBindingIds", ()))
        for row in accepted
    )
    return {
        "fixtureCount": len(values),
        "deterministicClaimPrecision": _rate(true_positive, true_positive + false_positive),
        "claimRecall": _rate(sum(row["actualDecision"] == "accepted" for row in positives), len(positives)),
        "falsePositiveRate": _rate(false_positive, len(negatives)),
        "insufficientEvidenceAccuracy": _rate(
            sum(row["actualDecision"] == "insufficient_evidence" for row in insufficient), len(insufficient)
        ),
        "citationValidity": _rate(accepted_citations_valid, len(accepted)),
        "acceptedClaimBindingCompleteness": _rate(accepted_binding_complete, len(accepted)),
        "llmProposalAcceptanceRate": _rate(sum(row["actualDecision"] == "accepted" for row in llm), len(llm)),
        "llmProposalRejectionRate": _rate(sum(row["actualDecision"] != "accepted" for row in llm), len(llm)),
        "decisionCounts": dict(sorted(Counter(row["actualDecision"] for row in values).items())),
        "statisticalQualityClaimed": False,
    }


def compare_pattern_versions(
    baseline_version: str,
    baseline: Mapping[str, float],
    candidate_version: str,
    candidate: Mapping[str, float],
) -> dict[str, Any]:
    keys = (
        "deterministicClaimPrecision", "claimRecall", "falsePositiveRate",
        "insufficientEvidenceAccuracy", "citationValidity", "acceptedClaimBindingCompleteness",
    )
    return {
        "baselineVersion": baseline_version,
        "candidateVersion": candidate_version,
        "deltas": {
            key: round(float(candidate.get(key, 0.0)) - float(baseline.get(key, 0.0)), 6)
            for key in keys
        },
    }
