"""Export benchmark results as JSON and CSV."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.eval.dataset import BENCHMARK_VERSION

# Scalar columns for the CSV (list/dict fields are omitted).
CSV_COLUMNS = [
    "benchmarkVersion", "promptVersion", "scenarioId", "category", "requestedMode",
    "intensityConfigured", "intensityResolved", "generationMode", "provider", "model",
    "cacheStatus",
    "overallQualityScore", "groundingScore", "narrativeUtilityScore",
    "overallDeltaVsDeterministic", "narrativeDeltaVsDeterministic",
    "schemaValid", "citationAccuracy", "citationCoverage", "hallucinationWarnings",
    "factualConsistency", "summaryCompleteness", "concision", "personaMarketRelevance",
    "actionUsefulness", "actionAlignment",
    "reportChanged", "summaryChanged", "personaBriefChanged", "suggestedActionsAccepted", "llmFallback",
    "llmCalls", "contextChars", "inputTokens", "outputTokens", "estimatedCostUsd", "latencyMs",
    "contradictions", "deterministicConfidence",
]


def build_document(results: List[Dict[str, Any]], summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "benchmarkVersion": BENCHMARK_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "results": results,
    }


def to_json(results: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    return json.dumps(build_document(results, summary), indent=2)


def to_csv(results: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in results:
        writer.writerow({k: row.get(k, "") for k in CSV_COLUMNS})
    return buf.getvalue()


def write_json(path: str, results: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_json(results, summary))


def write_csv(path: str, results: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(to_csv(results))
