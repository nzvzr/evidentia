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
        for mode in modes:
            if clear_cache:
                orchestrator._CACHE.clear()  # ensure real execution, not cache
            intensity = MODE_TO_INTENSITY.get(mode, mode)
            report, tel = run_pipeline_ex(
                market=inp["market"],
                persona=inp["persona"],
                custom_persona=inp.get("customPersona", ""),
                selected_document_ids=inp["selectedDocumentIds"],
                intensity_override=intensity,
                use_cache=False,
            )
            quality = evaluate_report(report, inp["selectedDocumentIds"], inp.get("customPersona", ""))
            cost = estimate_cost(tel["model"], tel["inputTokens"], tel["outputTokens"])
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
            "avgQualityScore": round(mean(x["qualityScore"] for x in rows), 1),
            "schemaValidRate": round(mean(1.0 if x["schemaValid"] else 0.0 for x in rows), 3),
            "avgCitationAccuracy": round(mean(x["citationAccuracy"] for x in rows), 3),
            "avgCitationCoverage": round(mean(x["citationCoverage"] for x in rows), 3),
            "avgActionSpecificity": round(mean(x["actionSpecificity"] for x in rows), 3),
            "avgHallucinationWarnings": round(mean(x["hallucinationWarnings"] for x in rows), 2),
            "avgLatencyMs": round(mean(x["latencyMs"] for x in rows), 1),
            "totalLlmCalls": sum(x["llmCalls"] for x in rows),
            "totalTokens": sum(x["inputTokens"] + x["outputTokens"] for x in rows),
            "totalEstimatedCostUsd": round(sum(x["estimatedCostUsd"] for x in rows), 6),
        }
    return summary
