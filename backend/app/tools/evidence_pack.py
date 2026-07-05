"""Builds a compact, token-bounded evidence pack for the LLM.

Sending this instead of raw documents keeps prompts short, cheap, and grounded.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


def build_evidence_pack(
    report: Dict[str, Any],
    sections: List[Dict[str, Any]],
    max_citations: int = 5,
    max_risks: int = 4,
    max_workflow_steps: int = 5,
) -> Dict[str, Any]:
    metrics = report.get("metrics", {})
    return {
        "persona": report.get("persona"),
        "customPersona": report.get("customPersona"),
        "market": report.get("market"),
        "metrics": {
            "documentsAnalyzed": metrics.get("documentsAnalyzed"),
            "passagesIndexed": metrics.get("passagesIndexed"),
            "citationsUsed": metrics.get("citationsUsed"),
            "risksFlagged": metrics.get("risksFlagged"),
            "confidence": metrics.get("confidence"),
            "complianceSensitivity": metrics.get("complianceSensitivity"),
        },
        "topRisks": [
            {
                "severity": r["severity"],
                "title": r["title"],
                "businessImpact": r["businessImpact"],
                "evidenceCode": r["evidenceCode"],
                "recommendedFix": r["recommendedFix"],
                "owner": r["owner"],
            }
            for r in report.get("risks", [])[:max_risks]
        ],
        "workflow": [
            {"step": w["step"], "title": w["title"], "evidenceCode": w["evidenceCode"]}
            for w in report.get("workflowSteps", [])[:max_workflow_steps]
        ],
        "citations": [
            {
                "id": c["id"],
                "source": c["source"],
                "section": c["section"],
                "excerpt": c["excerpt"],
                "whyItMatters": c["whyItMatters"],
            }
            for c in report.get("citations", [])[:max_citations]
        ],
    }


def pack_to_text(pack: Dict[str, Any], max_chars: int) -> str:
    """Serialize the pack to compact JSON, bounded by max_chars."""
    text = json.dumps(pack, ensure_ascii=False)
    if len(text) <= max_chars:
        return text
    # Drop citation excerpts first (largest field) if over budget, then truncate.
    trimmed = dict(pack)
    trimmed["citations"] = [
        {**c, "excerpt": (c["excerpt"][:120] + "…") if len(c.get("excerpt", "")) > 120 else c.get("excerpt", "")}
        for c in pack.get("citations", [])
    ]
    text = json.dumps(trimmed, ensure_ascii=False)
    return text[:max_chars]
