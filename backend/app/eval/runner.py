"""Benchmark runner: executes scenarios across intensity modes and scores them."""

from __future__ import annotations

from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Tuple

from app.agents import orchestrator
from app.agents.orchestrator import run_pipeline_ex
from app.eval.dataset import BENCHMARK_VERSION, SCENARIOS
from app.eval.metrics import available_citation_ids, evaluate_report, expected_match_metrics
from app.eval.pricing import estimate_cost

# A replacement below this relevance score is treated as low-confidence.
LOW_CONFIDENCE_RELEVANCE = 3.0

# Human-facing mode name -> pipeline intensity override.
MODE_TO_INTENSITY = {
    "deterministic": "off",
    "summary": "summary",
    "full": "full",
    "auto": "auto",
}
DEFAULT_MODES = ["deterministic", "summary", "full"]


def filter_scenarios(
    scenarios: List[Dict[str, Any]],
    scenario_ids: Optional[List[str]] = None,
    categories: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    out = scenarios
    if scenario_ids:
        wanted = set(scenario_ids)
        out = [s for s in out if s["id"] in wanted]
    if categories:
        cats = set(categories)
        out = [s for s in out if s["category"] in cats]
    return out


def run_benchmark(
    modes: Optional[List[str]] = None,
    scenarios: Optional[List[Dict[str, Any]]] = None,
    clear_cache: bool = True,
    runs: int = 1,
) -> List[Dict[str, Any]]:
    modes = modes or DEFAULT_MODES
    scenarios = scenarios or SCENARIOS
    results: List[Dict[str, Any]] = []
    for run_index in range(max(1, runs)):
        results.extend(_run_once(modes, scenarios, clear_cache, run_index))
    return results


def _run_once(
    modes: List[str], scenarios: List[Dict[str, Any]], clear_cache: bool, run_index: int
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for scenario in scenarios:
        inp = scenario["input"]
        expected = scenario.get("expected") or {}
        docs = inp["selectedDocumentIds"]
        custom = inp.get("customPersona", "")

        # Deterministic baseline for per-scenario deltas.
        if clear_cache:
            orchestrator._CACHE.clear()
        base_report, _base_tel = run_pipeline_ex(
            market=inp["market"], persona=inp["persona"], custom_persona=custom,
            selected_document_ids=docs, intensity_override="off", use_cache=False,
        )
        base_eval = evaluate_report(base_report, docs, expected, custom)
        base_overall = base_eval["overallQualityScore"]
        base_narrative = base_eval["narrativeUtilityScore"]

        for mode in modes:
            if clear_cache:
                orchestrator._CACHE.clear()  # ensure real execution, not cache
            intensity = MODE_TO_INTENSITY.get(mode, mode)
            report, tel = run_pipeline_ex(
                market=inp["market"], persona=inp["persona"], custom_persona=custom,
                selected_document_ids=docs, intensity_override=intensity, use_cache=False,
            )
            quality = evaluate_report(report, docs, expected, custom)
            cost = estimate_cost(tel["model"], tel["inputTokens"], tel["outputTokens"])
            accepted = tel["acceptedLlmUpdates"]

            # --- repair-audit relevance metrics ---
            audit = tel["repairAudit"]
            available = available_citation_ids(docs)
            expected_codes = set(expected.get("evidenceCodes", []))
            for a in audit:
                a["matchedExpected"] = a["replacementEvidenceCode"] in expected_codes
            replaced = [a for a in audit if a["repairDecision"] == "replaced"]
            insufficient = [a for a in audit if a["repairDecision"] == "insufficient-evidence"]
            valid_repl = sum(1 for a in replaced if a["replacementEvidenceCode"] in available)
            expected_matches = sum(1 for a in replaced if a["replacementEvidenceCode"] in expected_codes)
            low_conf = sum(1 for a in replaced if a["relevanceScore"] < LOW_CONFIDENCE_RELEVANCE)
            relevance_sum = sum(a["relevanceScore"] for a in replaced)

            # --- ground-truth risk/evidence match semantics (4 metrics) ---
            match = expected_match_metrics(report, expected)

            results.append(
                {
                    "benchmarkVersion": BENCHMARK_VERSION,
                    "promptVersion": tel["promptVersion"],
                    "runIndex": run_index,
                    "scenarioId": scenario["id"],
                    "category": scenario["category"],
                    "description": scenario["description"],
                    "requestedMode": mode,
                    "intensityConfigured": tel["intensityConfigured"],
                    "intensityResolved": tel["intensityResolved"],
                    "generationMode": tel["generationMode"],
                    "provider": tel["provider"],
                    "model": tel["model"],
                    "cacheStatus": tel["cacheStatus"],
                    "llmCalls": tel["llmCalls"],
                    "contextChars": tel["contextChars"],
                    "inputTokens": tel["inputTokens"],
                    "outputTokens": tel["outputTokens"],
                    "estimatedCostUsd": cost,
                    "latencyMs": tel["latencyMs"],
                    "contradictions": tel["contradictions"],
                    "deterministicConfidence": tel["deterministicConfidence"],
                    # narrative/grounding change telemetry
                    "reportChanged": tel["reportChanged"],
                    "summaryChanged": accepted["summaryChanged"],
                    "personaBriefChanged": accepted["personaBriefChanged"],
                    "suggestedActionsAccepted": accepted["suggestedActionsAccepted"],
                    "llmFallback": accepted["llmFallback"],
                    # field-level narrative gate
                    "acceptedFields": tel["acceptedFields"],
                    "rejectedFields": tel["rejectedFields"],
                    "rejectionReasons": tel["rejectionReasons"],
                    "acceptedFieldsCount": len(tel["acceptedFields"]),
                    "rejectedFieldsCount": len(tel["rejectedFields"]),
                    "narrativeGateDecision": tel["narrativeGateDecision"],
                    "deterministicNarrativeScore": tel["deterministicNarrativeScore"],
                    "candidateNarrativeScore": tel["candidateNarrativeScore"],
                    "finalNarrativeScore": tel["finalNarrativeScore"],
                    # grounding repair
                    "ungroundedBeforeRepair": tel["ungroundedBeforeRepair"],
                    "ungroundedAfterRepair": tel["ungroundedAfterRepair"],
                    "evidenceRepairs": tel["evidenceRepairs"],
                    "repairAudit": audit,
                    "repairReplaced": len(replaced),
                    "repairInsufficient": len(insufficient),
                    "repairValidReplacements": valid_repl,
                    "repairExpectedMatches": expected_matches,
                    "repairLowConfidence": low_conf,
                    "repairRelevanceSum": round(relevance_sum, 3),
                    "validReplacementRate": round(valid_repl / len(replaced), 3) if replaced else 1.0,
                    "expectedEvidenceMatchRate": round(expected_matches / len(replaced), 3) if replaced else 0.0,
                    "insufficientEvidenceRate": round(len(insufficient) / len(audit), 3) if audit else 0.0,
                    "lowConfidenceRepairRate": round(low_conf / len(replaced), 3) if replaced else 0.0,
                    "averageRepairRelevanceScore": round(relevance_sum / len(replaced), 3) if replaced else 0.0,
                    # source-constrained generation
                    "risksGeneratedBeforeFiltering": tel["risksGeneratedBeforeFiltering"],
                    "groundedRisksKept": tel["groundedRisksKept"],
                    "unsupportedRisksDropped": tel["unsupportedRisksDropped"],
                    "workflowsGeneratedBeforeFiltering": tel["workflowsGeneratedBeforeFiltering"],
                    "groundedWorkflowStepsKept": tel["groundedWorkflowStepsKept"],
                    "unsupportedWorkflowStepsDropped": tel["unsupportedWorkflowStepsDropped"],
                    "insufficientEvidenceItemsFinal": tel["insufficientEvidenceItemsFinal"],
                    "sourceDocumentMismatchCount": tel["sourceDocumentMismatchCount"],
                    "evidenceSupportScoreAvg": tel["evidenceSupportScoreAvg"],
                    "evidenceSupportScoreMin": tel["evidenceSupportScoreMin"],
                    "generationAudit": tel["generationAudit"],
                    # ground-truth match semantics
                    "expectedRiskConceptRecall": match["expectedRiskConceptRecall"],
                    "expectedSourceDocumentMatchRate": match["expectedSourceDocumentMatchRate"],
                    "expectedCitationFamilyMatchRate": match["expectedCitationFamilyMatchRate"],
                    "expectedCitationExactMatchRate": match["expectedCitationExactMatchRate"],
                    # full-mode structural gate
                    "deterministicStructuralScore": tel["deterministicStructuralScore"],
                    "candidateStructuralScore": tel["candidateStructuralScore"],
                    "finalStructuralScore": tel["finalStructuralScore"],
                    "structuralGateDecision": tel["structuralGateDecision"],
                    "acceptedStructuralComponents": tel["acceptedStructuralComponents"],
                    "rejectedStructuralComponents": tel["rejectedStructuralComponents"],
                    "acceptedStructuralComponentCount": len(tel["acceptedStructuralComponents"]),
                    "rejectedStructuralComponentCount": len(tel["rejectedStructuralComponents"]),
                    "acceptedRiskCount": tel["acceptedRiskCount"],
                    "rejectedRiskCount": tel["rejectedRiskCount"],
                    "acceptedWorkflowStepCount": tel["acceptedWorkflowStepCount"],
                    "rejectedWorkflowStepCount": tel["rejectedWorkflowStepCount"],
                    "structuralRejectionReasons": tel["structuralRejectionReasons"],
                    "fullModeAnalyticalFallback": tel["fullModeAnalyticalFallback"],
                    # deterministic pre-LLM analytical scores + routing telemetry
                    "documentComplexity": len(docs),
                    "personaComplexity": 1 if (custom or "").strip() else 0,
                    "deterministicStructuralScoreBaseline": tel["deterministicStructuralScoreBaseline"],
                    "deterministicNarrativeScoreBaseline": tel["deterministicNarrativeScoreBaseline"],
                    "routingReason": tel["routingReason"],
                    "routingConfidence": tel["routingConfidence"],
                    "predictedIncrementalGain": tel["predictedIncrementalGain"],
                    "selectedMode": tel["selectedMode"],
                    "alternativeMode": tel["alternativeMode"],
                    # deltas vs deterministic baseline
                    "overallDeltaVsDeterministic": round(quality["overallQualityScore"] - base_overall, 1),
                    "narrativeDeltaVsDeterministic": round(quality["narrativeUtilityScore"] - base_narrative, 1),
                    **quality,
                }
            )
    return results


def _mean_opt(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [x[key] for x in rows if x.get(key) is not None]
    return round(mean(vals), 3) if vals else None


def _repl(rows: List[Dict[str, Any]]) -> int:
    return sum(x["repairReplaced"] for x in rows)


def _insuff(rows: List[Dict[str, Any]]) -> int:
    return sum(x["repairInsufficient"] for x in rows)


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_mode: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_mode.setdefault(r["requestedMode"], []).append(r)

    summary: Dict[str, Any] = {}
    for mode, rows in by_mode.items():
        total_fields = sum(x["acceptedFieldsCount"] + x["rejectedFieldsCount"] for x in rows)
        total_accepted = sum(x["acceptedFieldsCount"] for x in rows)
        summary[mode] = {
            "count": len(rows),
            "avgOverallQualityScore": round(mean(x["overallQualityScore"] for x in rows), 1),
            "avgGroundingScore": round(mean(x["groundingScore"] for x in rows), 1),
            "avgNarrativeUtilityScore": round(mean(x["narrativeUtilityScore"] for x in rows), 1),
            "avgOverallDeltaVsDeterministic": round(mean(x["overallDeltaVsDeterministic"] for x in rows), 2),
            "avgNarrativeDeltaVsDeterministic": round(mean(x["narrativeDeltaVsDeterministic"] for x in rows), 2),
            "schemaValidRate": round(mean(1.0 if x["schemaValid"] else 0.0 for x in rows), 3),
            "avgCitationAccuracy": round(mean(x["citationAccuracy"] for x in rows), 3),
            "avgActionUsefulness": round(mean(x["actionUsefulness"] for x in rows), 3),
            "avgHallucinationWarnings": round(mean(x["hallucinationWarnings"] for x in rows), 2),
            "reportsChanged": sum(1 for x in rows if x["reportChanged"]),
            # gate + repair reporting
            "narrativeRegressionsBeforeGate": sum(
                1 for x in rows if x["candidateNarrativeScore"] < x["deterministicNarrativeScore"]
            ),
            "narrativeRegressionsAfterGate": sum(
                1 for x in rows if x["finalNarrativeScore"] < x["deterministicNarrativeScore"]
            ),
            "fieldAcceptanceRate": round(total_accepted / total_fields, 3) if total_fields else 0.0,
            "ungroundedBeforeRepair": sum(x["ungroundedBeforeRepair"] for x in rows),
            "ungroundedAfterRepair": sum(x["ungroundedAfterRepair"] for x in rows),
            "evidenceRepairs": sum(x["evidenceRepairs"] for x in rows),
            # repair-relevance audit (pooled across scenarios)
            "repairAudited": _repl(rows) + _insuff(rows),
            "repairReplaced": _repl(rows),
            "repairInsufficient": _insuff(rows),
            "validReplacementRate": round(sum(x["repairValidReplacements"] for x in rows) / _repl(rows), 3) if _repl(rows) else 1.0,
            "expectedEvidenceMatchRate": round(sum(x["repairExpectedMatches"] for x in rows) / _repl(rows), 3) if _repl(rows) else 0.0,
            "insufficientEvidenceRate": round(_insuff(rows) / (_repl(rows) + _insuff(rows)), 3) if (_repl(rows) + _insuff(rows)) else 0.0,
            "lowConfidenceRepairRate": round(sum(x["repairLowConfidence"] for x in rows) / _repl(rows), 3) if _repl(rows) else 0.0,
            "averageRepairRelevanceScore": round(sum(x["repairRelevanceSum"] for x in rows) / _repl(rows), 3) if _repl(rows) else 0.0,
            # source-constrained generation (pooled)
            "risksGeneratedBeforeFiltering": sum(x["risksGeneratedBeforeFiltering"] for x in rows),
            "groundedRisksKept": sum(x["groundedRisksKept"] for x in rows),
            "unsupportedRisksDropped": sum(x["unsupportedRisksDropped"] for x in rows),
            "workflowsGeneratedBeforeFiltering": sum(x["workflowsGeneratedBeforeFiltering"] for x in rows),
            "groundedWorkflowStepsKept": sum(x["groundedWorkflowStepsKept"] for x in rows),
            "unsupportedWorkflowStepsDropped": sum(x["unsupportedWorkflowStepsDropped"] for x in rows),
            "insufficientEvidenceItemsFinal": sum(x["insufficientEvidenceItemsFinal"] for x in rows),
            "sourceDocumentMismatchCount": sum(x["sourceDocumentMismatchCount"] for x in rows),
            "avgEvidenceSupportScore": round(
                mean([x["evidenceSupportScoreAvg"] for x in rows if x["evidenceSupportScoreAvg"] > 0]), 3
            ) if any(x["evidenceSupportScoreAvg"] > 0 for x in rows) else 0.0,
            "minEvidenceSupportScore": round(
                min([x["evidenceSupportScoreMin"] for x in rows if x["groundedRisksKept"] > 0]), 3
            ) if any(x["groundedRisksKept"] > 0 for x in rows) else 0.0,
            # ground-truth match semantics (means over scenarios that carry each)
            "avgExpectedRiskConceptRecall": _mean_opt(rows, "expectedRiskConceptRecall"),
            "avgExpectedSourceDocumentMatchRate": _mean_opt(rows, "expectedSourceDocumentMatchRate"),
            "avgExpectedCitationFamilyMatchRate": _mean_opt(rows, "expectedCitationFamilyMatchRate"),
            "avgExpectedCitationExactMatchRate": _mean_opt(rows, "expectedCitationExactMatchRate"),
            # full-mode structural gate
            "avgDeterministicStructuralScore": round(mean(x["deterministicStructuralScore"] for x in rows), 2),
            "avgCandidateStructuralScore": round(mean(x["candidateStructuralScore"] for x in rows), 2),
            "avgFinalStructuralScore": round(mean(x["finalStructuralScore"] for x in rows), 2),
            "structuralRegressionsBeforeGate": sum(
                1 for x in rows if x["candidateStructuralScore"] < x["deterministicStructuralScore"]
            ),
            "structuralRegressionsAfterGate": sum(
                1 for x in rows if x["finalStructuralScore"] < x["deterministicStructuralScore"]
            ),
            "acceptedStructuralComponents": sum(x["acceptedStructuralComponentCount"] for x in rows),
            "rejectedStructuralComponents": sum(x["rejectedStructuralComponentCount"] for x in rows),
            "acceptedRiskCount": sum(x["acceptedRiskCount"] for x in rows),
            "rejectedRiskCount": sum(x["rejectedRiskCount"] for x in rows),
            "acceptedWorkflowStepCount": sum(x["acceptedWorkflowStepCount"] for x in rows),
            "rejectedWorkflowStepCount": sum(x["rejectedWorkflowStepCount"] for x in rows),
            "fullModeAnalyticalFallbacks": sum(1 for x in rows if x["fullModeAnalyticalFallback"]),
            # mean/std for quality, latency, cost
            "overallQualityStd": round(pstdev([x["overallQualityScore"] for x in rows]), 2) if len(rows) > 1 else 0.0,
            "latencyMsStd": round(pstdev([x["latencyMs"] for x in rows]), 1) if len(rows) > 1 else 0.0,
            "estimatedCostStd": round(pstdev([x["estimatedCostUsd"] for x in rows]), 6) if len(rows) > 1 else 0.0,
            "avgLatencyMs": round(mean(x["latencyMs"] for x in rows), 1),
            "totalLlmCalls": sum(x["llmCalls"] for x in rows),
            "totalTokens": sum(x["inputTokens"] + x["outputTokens"] for x in rows),
            "totalEstimatedCostUsd": round(sum(x["estimatedCostUsd"] for x in rows), 6),
        }
    return summary


def _key(row: Dict[str, Any]) -> Tuple[Any, Any]:
    return (row["scenarioId"], row["runIndex"])


def _wtl(rows_a: Dict[Tuple, Dict], rows_b: Dict[Tuple, Dict], eps: float = 0.05) -> Dict[str, int]:
    win = tie = loss = 0
    for k, a in rows_a.items():
        b = rows_b.get(k)
        if not b:
            continue
        d = a["overallQualityScore"] - b["overallQualityScore"]
        if d > eps:
            win += 1
        elif d < -eps:
            loss += 1
        else:
            tie += 1
    return {"win": win, "tie": tie, "loss": loss}


def compare_modes(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cross-mode analysis: win/tie/loss, incremental gain, cost per accepted
    analytical improvement, and     structural regressions."""
    by_mode: Dict[str, Dict[Tuple, Dict]] = {}
    for r in results:
        by_mode.setdefault(r["requestedMode"], {})[_key(r)] = r

    out: Dict[str, Any] = {}

    def mean_overall(mode: str) -> Optional[float]:
        rows = list(by_mode.get(mode, {}).values())
        return round(mean(x["overallQualityScore"] for x in rows), 2) if rows else None

    if "full" in by_mode and "deterministic" in by_mode:
        out["fullVsDeterministic"] = _wtl(by_mode["full"], by_mode["deterministic"])
    if "full" in by_mode and "summary" in by_mode:
        out["fullVsSummary"] = _wtl(by_mode["full"], by_mode["summary"])
        fm, sm = mean_overall("full"), mean_overall("summary")
        out["fullIncrementalGainVsSummary"] = round(fm - sm, 2) if (fm is not None and sm is not None) else None

    if "full" in by_mode:
        full_rows = list(by_mode["full"].values())
        accepted = sum(x["acceptedStructuralComponentCount"] for x in full_rows)
        accepted_items = sum(x["acceptedRiskCount"] + x["acceptedWorkflowStepCount"] for x in full_rows)
        full_cost = round(sum(x["estimatedCostUsd"] for x in full_rows), 6)
        out["fullStructuralRegressionsBeforeGate"] = sum(
            1 for x in full_rows if x["candidateStructuralScore"] < x["deterministicStructuralScore"]
        )
        out["fullStructuralRegressionsAfterGate"] = sum(
            1 for x in full_rows if x["finalStructuralScore"] < x["deterministicStructuralScore"]
        )
        out["fullAcceptedStructuralComponents"] = accepted
        out["fullAcceptedAnalyticalItems"] = accepted_items
        out["fullTotalCostUsd"] = full_cost
        out["costPerAcceptedComponentUsd"] = round(full_cost / accepted, 6) if accepted else None
        out["costPerAcceptedItemUsd"] = round(full_cost / accepted_items, 6) if accepted_items else None
    return out
