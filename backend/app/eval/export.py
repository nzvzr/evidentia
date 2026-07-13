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
    # narrative sub-metrics
    "summaryFactualConsistency", "summaryCompleteness", "summaryConcision",
    "personaMarketRelevance", "actionUsefulness", "actionEvidenceAlignment",
    "vagueLanguagePenalty", "repetitionPenalty",
    # field-level gate
    "deterministicNarrativeScore", "candidateNarrativeScore", "finalNarrativeScore",
    "narrativeGateDecision", "acceptedFieldsCount", "rejectedFieldsCount",
    # grounding repair
    "ungroundedBeforeRepair", "ungroundedAfterRepair", "evidenceRepairs",
    "repairReplaced", "repairInsufficient", "validReplacementRate",
    "expectedEvidenceMatchRate", "insufficientEvidenceRate", "lowConfidenceRepairRate",
    "averageRepairRelevanceScore",
    # source-constrained generation
    "risksGeneratedBeforeFiltering", "groundedRisksKept", "unsupportedRisksDropped",
    "workflowsGeneratedBeforeFiltering", "groundedWorkflowStepsKept", "unsupportedWorkflowStepsDropped",
    "insufficientEvidenceItemsFinal", "sourceDocumentMismatchCount",
    "evidenceSupportScoreAvg", "evidenceSupportScoreMin", "expectedRiskRecall",
    # change telemetry
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


AUDIT_COLUMNS = [
    "scenarioId", "requestedMode", "itemType", "itemTitle", "originalEvidenceCode",
    "replacementEvidenceCode", "repairDecision", "relevanceScore", "matchedExpected",
    "matchedTerms", "matchedPhrases",
]


def to_audit_csv(results: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=AUDIT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in results:
        for a in row.get("repairAudit", []):
            writer.writerow({
                "scenarioId": row.get("scenarioId", ""),
                "requestedMode": row.get("requestedMode", ""),
                "itemType": a.get("itemType", ""),
                "itemTitle": a.get("itemTitle", ""),
                "originalEvidenceCode": a.get("originalEvidenceCode", ""),
                "replacementEvidenceCode": a.get("replacementEvidenceCode", ""),
                "repairDecision": a.get("repairDecision", ""),
                "relevanceScore": a.get("relevanceScore", ""),
                "matchedExpected": a.get("matchedExpected", ""),
                "matchedTerms": "; ".join(a.get("matchedTerms", [])),
                "matchedPhrases": "; ".join(a.get("matchedPhrases", [])),
            })
    return buf.getvalue()


def write_audit_csv(path: str, results: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(to_audit_csv(results))


GEN_AUDIT_COLUMNS = [
    "scenarioId", "requestedMode", "itemType", "title", "proposedRiskOrStep",
    "proposedSourceDocumentId", "proposedCitationId", "supportScore",
    "rejectionReason", "finalDecision",
]


def to_generation_audit_csv(results: List[Dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=GEN_AUDIT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in results:
        for a in row.get("generationAudit", []):
            record = {k: a.get(k, "") for k in GEN_AUDIT_COLUMNS}
            record["scenarioId"] = row.get("scenarioId", "")
            record["requestedMode"] = row.get("requestedMode", "")
            writer.writerow(record)
    return buf.getvalue()


def write_generation_audit_csv(path: str, results: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(to_generation_audit_csv(results))
