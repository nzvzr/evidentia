"""Pipeline orchestrator.

Runs the deterministic agents in order, then optionally refines the output with
LLM agents when EVIDENTIA_USE_LLM=true and a key is configured. Every LLM step
falls back to the deterministic baseline, so the pipeline never fails.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.services.llm import generate_structured_object
from app.tools.document_search import summarize_sections
from app.tools.risk_tools import (
    find_api_risks,
    find_incident_escalation_risks,
    find_residency_risks,
    find_sla_risks,
)

from .citation_binder import citation_binder
from .document_reader import document_reader
from .metrics_agent import metrics_agent
from .persona_mapper import persona_mapper, resolve_persona_key
from .report_composer import build_agent_steps, report_composer, suggested_actions_for
from .risk_analyzer import risk_analyzer
from .workflow_builder import workflow_builder

DEFAULT_MARKET = "EMEA"
DEFAULT_PERSONA = "Support Agent"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _derive_id(market: str, persona: str, custom_persona: str, doc_ids: List[str]) -> str:
    role = (custom_persona or persona or "role").lower()
    role_slug = "".join(c if c.isalnum() else "-" for c in role).strip("-")[:32] or "role"
    market_slug = "".join(c if c.isalnum() else "-" for c in market.lower()).strip("-")[:32] or "market"
    h = 5381
    for ch in "|".join(sorted(doc_ids)):
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return f"{role_slug}-{market_slug}-{format(h, 'x')}"


# ---------------------------------------------------------------------------
# LLM refinement helpers (each grounded + fully fallback-safe)
# ---------------------------------------------------------------------------

def _refine_persona(market: str, persona: str, custom_persona: str, sections, baseline) -> Dict[str, Any]:
    result = generate_structured_object(
        system=(
            "You are Evidentia's Persona Modeler. Infer responsibilities, priorities, relevant topics, "
            "risk focus, and preferred output style, grounded in the document context and market."
        ),
        user=(
            f"Market: {market}\nPredefined persona: {persona or '(none)'}\n"
            f"Custom role (takes priority): {custom_persona or '(none)'}\n\n"
            f"Document context:\n{summarize_sections(sections)}\n\n"
            f"Baseline persona brief:\n{baseline}"
        ),
        schema_name="PersonaBrief",
        schema={"title": "string", "description": "string", "goals": ["string"], "priorities": ["string"],
                "relevantTopics": ["string"], "riskFocus": ["string"], "outputStyle": "string"},
        fallback={},
    )
    is_custom = bool(custom_persona and custom_persona.strip())

    def arr(key):
        v = result.get(key)
        return v if isinstance(v, list) and v and all(isinstance(x, str) for x in v) else baseline[key]

    def s(key):
        v = result.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else baseline[key]

    return {
        "title": custom_persona.strip() if is_custom else s("title"),
        "description": s("description"),
        "goals": arr("goals"),
        "priorities": arr("priorities"),
        "relevantTopics": arr("relevantTopics"),
        "riskFocus": arr("riskFocus"),
        "outputStyle": s("outputStyle"),
        "isCustom": is_custom,
    }


def _refine_workflow(market, persona_brief, sections, baseline) -> List[Dict[str, Any]]:
    valid = {s["citationId"] for s in sections}
    fallback_code = baseline[0]["evidenceCode"] if baseline else (sections[0]["citationId"] if sections else "SEC-4.2")
    result = generate_structured_object(
        system=(
            "You are Evidentia's Workflow Builder. Produce 4-6 practical, role-specific steps. "
            "Each evidenceCode must be a citation id present in the document context; never invent ids."
        ),
        user=(
            f"Market: {market}\nPersona: {persona_brief}\n\n"
            f"Document context:\n{summarize_sections(sections)}\n\nBaseline steps:\n{baseline}"
        ),
        schema_name="WorkflowPlan",
        schema={"steps": [{"step": "number", "title": "string", "description": "string",
                            "whyItMatters": "string", "expectedOutput": "string", "evidenceCode": "string"}]},
        fallback={},
    )
    raw = result.get("steps")
    if not isinstance(raw, list) or len(raw) < 4:
        return baseline
    cleaned: List[Dict[str, Any]] = []
    for i, item in enumerate(raw[:6]):
        if not isinstance(item, dict):
            return baseline
        base = baseline[i] if i < len(baseline) else {}
        ev = item.get("evidenceCode")
        if not (isinstance(ev, str) and ev in valid):
            ev = base.get("evidenceCode") if base.get("evidenceCode") in valid else fallback_code

        def s(key, default):
            v = item.get(key)
            return v.strip() if isinstance(v, str) and v.strip() else default

        cleaned.append({
            "step": i + 1,
            "title": s("title", base.get("title", f"Step {i + 1}")),
            "description": s("description", base.get("description", "")),
            "whyItMatters": s("whyItMatters", base.get("whyItMatters", "")),
            "expectedOutput": s("expectedOutput", base.get("expectedOutput", "")),
            "evidenceCode": ev,
        })
    return cleaned if len(cleaned) >= 4 else baseline


def _refine_risks(market, persona_brief, sections, baseline) -> List[Dict[str, Any]]:
    valid = {s["citationId"] for s in sections}
    fallback_code = baseline[0]["evidenceCode"] if baseline else (sections[0]["citationId"] if sections else "SEC-4.2")
    signals = {
        "residency": [s["citationId"] for s in find_residency_risks(sections, market)],
        "sla": [s["citationId"] for s in find_sla_risks(sections)],
        "api": [s["citationId"] for s in find_api_risks(sections)],
        "escalation": [s["citationId"] for s in find_incident_escalation_risks(sections)],
    }
    result = generate_structured_object(
        system=(
            "You are Evidentia's Risk Analyzer. Identify 3-5 grounded risks. Prefer residency, SLA, API, "
            "incident escalation, and compliance issues supported by the sources. evidenceCode must be a real id."
        ),
        user=(
            f"Market: {market}\nPersona: {persona_brief}\n\nSignals: {signals}\n\n"
            f"Document context:\n{summarize_sections(sections)}\n\nBaseline risks:\n{baseline}"
        ),
        schema_name="RiskRegister",
        schema={"risks": [{"severity": "High|Medium|Low", "title": "string", "description": "string",
                           "businessImpact": "string", "evidenceCode": "string", "recommendedFix": "string",
                           "owner": "string"}]},
        fallback={},
    )
    raw = result.get("risks")
    if not isinstance(raw, list) or len(raw) < 3:
        return baseline
    cleaned: List[Dict[str, Any]] = []
    for i, item in enumerate(raw[:5]):
        if not isinstance(item, dict):
            return baseline
        base = baseline[i] if i < len(baseline) else {}
        sev = item.get("severity")
        if sev not in ("High", "Medium", "Low"):
            sev = base.get("severity", "Medium")
        ev = item.get("evidenceCode")
        if not (isinstance(ev, str) and ev in valid):
            ev = base.get("evidenceCode") if base.get("evidenceCode") in valid else fallback_code

        def s(key, default):
            v = item.get(key)
            return v.strip() if isinstance(v, str) and v.strip() else default

        cleaned.append({
            "severity": sev,
            "title": s("title", base.get("title", "Risk")),
            "description": s("description", base.get("description", "")),
            "businessImpact": s("businessImpact", base.get("businessImpact", "")),
            "evidenceCode": ev,
            "recommendedFix": s("recommendedFix", base.get("recommendedFix", "")),
            "owner": s("owner", base.get("owner", "Platform Eng")),
        })
    if len(cleaned) < 3:
        return baseline
    if not any(r["severity"] == "High" for r in cleaned):
        cleaned[0]["severity"] = "High"
    if not any(r["severity"] == "Medium" for r in cleaned) and len(cleaned) > 1:
        cleaned[-1]["severity"] = "Medium"
    return cleaned


def _refine_report(draft, risks, citations) -> Dict[str, Any]:
    fallback = {
        "summary": draft["summary"],
        "topFinding": draft["topFinding"],
        "suggestedActions": draft["suggestedActions"],
    }
    result = generate_structured_object(
        system=(
            "You are Evidentia's Playbook Composer. Write an executive summary, one top finding, and 3-4 "
            "persona-specific suggested actions. Keep claims grounded in the provided risks and citations."
        ),
        user=(
            f"Company: {draft['company']}\nMarket: {draft['market']}\nPersona: {draft['persona']}\n\n"
            f"Risks:\n{risks}\n\nCitations:\n{[c['id'] for c in citations]}\n\n"
            f"Baseline summary:\n{draft['summary']}\nBaseline top finding:\n{draft['topFinding']}\n"
            f"Baseline actions:\n{draft['suggestedActions']}"
        ),
        schema_name="ReportNarrative",
        schema={"summary": "string", "topFinding": "string",
                "suggestedActions": [{"title": "string", "detail": "string"}]},
        fallback={},
    )
    actions = result.get("suggestedActions")
    clean_actions = []
    if isinstance(actions, list):
        for a in actions:
            if isinstance(a, dict) and isinstance(a.get("title"), str) and a["title"].strip():
                clean_actions.append({"title": a["title"].strip(),
                                      "detail": a["detail"].strip() if isinstance(a.get("detail"), str) else ""})

    def s(key):
        v = result.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else fallback[key]

    return {
        "summary": s("summary"),
        "topFinding": s("topFinding"),
        "suggestedActions": clean_actions if clean_actions else fallback["suggestedActions"],
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_pipeline(
    market: str,
    persona: str,
    custom_persona: str,
    selected_document_ids: List[str],
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    settings = get_settings()
    custom_persona = (custom_persona or "").strip()
    market = (market or "").strip() or DEFAULT_MARKET
    persona = (persona or "").strip() if custom_persona else ((persona or "").strip() or DEFAULT_PERSONA)
    generated_at = generated_at or _now_iso()

    documents, sections = document_reader(selected_document_ids)
    persona_key = resolve_persona_key(persona, custom_persona)
    report_id = _derive_id(market, persona, custom_persona, [d["id"] for d in documents])

    persona_brief = persona_mapper(market, persona, custom_persona, sections)
    workflow_steps = workflow_builder(persona_key, market, sections)
    risks = risk_analyzer(persona_key, market, sections)
    citations = citation_binder(sections, workflow_steps, risks)

    llm = settings.is_llm_enabled()
    if llm:
        try:
            persona_brief = _refine_persona(market, persona, custom_persona, sections, persona_brief)
            workflow_steps = _refine_workflow(market, persona_brief, sections, workflow_steps)
            risks = _refine_risks(market, persona_brief, sections, risks)
            citations = citation_binder(sections, workflow_steps, risks)  # re-bind grounded evidence
        except Exception:  # noqa: BLE001
            llm = False  # any unexpected failure → deterministic

    metrics = metrics_agent(
        documents, sections, citations, risks, workflow_steps, market, persona_key, persona_brief["title"]
    )
    agent_steps = build_agent_steps(documents, sections, risks, citations, workflow_steps, persona_brief["title"])

    report = report_composer(
        report_id=report_id,
        market=market,
        persona=persona,
        custom_persona=custom_persona,
        persona_key=persona_key,
        persona_brief=persona_brief,
        documents=documents,
        sections=sections,
        workflow_steps=workflow_steps,
        risks=risks,
        citations=citations,
        metrics=metrics,
        agent_steps=agent_steps,
        generated_at=generated_at,
    )

    if llm:
        try:
            refinement = _refine_report(report, risks, citations)
            report["summary"] = refinement["summary"]
            report["topFinding"] = refinement["topFinding"]
            report["suggestedActions"] = refinement["suggestedActions"]
        except Exception:  # noqa: BLE001
            pass
        report["generationMode"] = "llm-assisted"
        report["llmProvider"] = settings.active_provider()
        report["llmModel"] = settings.active_model()
    else:
        report["suggestedActions"] = suggested_actions_for(persona_key)
        report["generationMode"] = "deterministic"
        report["llmProvider"] = "none"

    return report
