"""Benchmark runner: executes scenarios across intensity modes and scores them."""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional

from app.agents import orchestrator
from app.agents.orchestrator import run_pipeline_ex
from app.eval.dataset import BENCHMARK_VERSION, SCENARIOS
from app.eval.metrics import evaluate_report
from app.eval.pricing import estimate_cost

# Human-facing mode name -> pipeline intensity override.
MODE_TO_INTENSITY = {
    "deterministic": "off",
    "summary": "summary",
    "full": "full",
    "auto": "auto",
}
DEFAULT_MODES = ["deterministic", "summary", "full"]


def run_benchmark(
    modes: Optional[List[str]] = None,
    scenarios: Optional[List[Dict[str, Any]]] = None,
    clear_cache: bool = True,
) -> List[Dict[str, Any]]:
    modes = modes or DEFAULT_MODES
    scenarios = scenarios or SCENARIOS
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
            results.append(
                {
                    "benchmarkVersion": BENCHMARK_VERSION,
                    "promptVersion": tel["promptVersion"],
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
                    # deltas vs deterministic baseline
                    "overallDeltaVsDeterministic": round(quality["overallQualityScore"] - base_overall, 1),
                    "narrativeDeltaVsDeterministic": round(quality["narrativeUtilityScore"] - base_narrative, 1),
                    **quality,
                }
            )
    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_mode: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_mode.setdefault(r["requestedMode"], []).append(r)

    summary: Dict[str, Any] = {}
    for mode, rows in by_mode.items():
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
            "avgLatencyMs": round(mean(x["latencyMs"] for x in rows), 1),
            "totalLlmCalls": sum(x["llmCalls"] for x in rows),
            "totalTokens": sum(x["inputTokens"] + x["outputTokens"] for x in rows),
            "totalEstimatedCostUsd": round(sum(x["estimatedCostUsd"] for x in rows), 6),
        }
    return summary
