"""Pipeline orchestrator with cost-calibrated LLM usage.

Modes (EVIDENTIA_LLM_INTENSITY):
  off      → deterministic only, 0 LLM calls          (generationMode "deterministic")
  summary  → deterministic + 1 LLM call to polish narrative  ("llm-summary")
  full     → deterministic + <=3 LLM calls to refine         ("llm-assisted")

Every LLM step validates its output and falls back to the deterministic baseline,
so the pipeline never fails. Results are cached in-memory per server session.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import get_settings
from app.services.llm import LLMCallResult, generate_structured_object
from app.tools.document_search import rank_sections_for_persona, summarize_sections
from app.tools.evidence_pack import build_evidence_pack, pack_to_text
from app.tools.text_quality import is_precise_text

from .citation_binder import citation_binder
from .document_reader import document_reader
from .metrics_agent import metrics_agent
from .persona_mapper import persona_mapper, resolve_persona_key
from .report_composer import build_agent_steps, report_composer, suggested_actions_for
from .risk_analyzer import risk_analyzer
from .workflow_builder import workflow_builder

logger = logging.getLogger("evidentia.pipeline")

DEFAULT_MARKET = "EMEA"
DEFAULT_PERSONA = "Support Agent"

# Calibrated system prompt shared by all LLM calls.
ANALYST_SYSTEM = (
    "You are Evidentia, an enterprise documentation analysis agent. "
    "Your job is to produce precise, concise, source-grounded operational reports. "
    "You must not invent facts, citations, risks, or metrics. "
    "You must only use the provided evidence pack. "
    "Every recommendation must be tied to a source citation when possible. "
    "Avoid vague phrases such as: 'critical insights', 'actionable recommendations', "
    "'enhance operational readiness', 'leverage documentation', 'drive business value', "
    "'optimize processes'. "
    "Prefer concrete language, e.g.: 'Verify SLA entitlement before promising remediation.', "
    "'Route Severity 1 incidents through the current on-call system.', "
    "'Do not claim EMEA in-region processing unless it is provisioned.', "
    "'Attach citation RES-14 when escalating residency concerns.' "
    "Style: concise, executive but practical, no hype, no generic SaaS language, no filler. "
    "Summary: no more than 4 sentences. topFinding: one specific sentence. "
    "suggestedActions: short imperative actions."
)

_CACHE: Dict[str, Dict[str, Any]] = {}


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


def _cache_key(market: str, persona: str, custom: str, docs: List[str], intensity: str, model: str) -> str:
    raw = "|".join([market, persona, custom, ",".join(sorted(docs)), intensity, model or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# LLM helpers — each returns (LLMCallResult, validated_updates)
# ---------------------------------------------------------------------------

def _llm_report_polish(report: Dict[str, Any], sections: List[Dict[str, Any]], max_output_tokens: int) -> Tuple[LLMCallResult, Dict[str, Any]]:
    settings = get_settings()
    pack = build_evidence_pack(report, sections)
    pack_text = pack_to_text(pack, settings.evidentia_max_context_chars)
    # topFinding stays deterministic (clean, executive, correctly spaced), so the
    # LLM only sharpens the summary, actions, and (optionally) the persona brief.
    user = (
        f"Deterministic draft summary (match this concrete style, do not add hype):\n{report['summary']}\n\n"
        f"Current persona brief description:\n{report['personaBrief']['description']}\n\n"
        f"Evidence pack (JSON — the ONLY facts you may use):\n{pack_text}\n\n"
        "Write a summary of at most 4 sentences that names the persona, market, document/risk/citation counts, "
        "the highest-severity issue with its evidence code, and the top 3 workflow steps. "
        "Then 3-4 short imperative suggestedActions, each with a one-line description and a priority. "
        "Optionally sharpen personaBriefDescription. Be specific and grounded; never use generic phrases like "
        "'structured workflow should be followed' or 'several additional risks require attention'."
    )
    result = generate_structured_object(
        system=ANALYST_SYSTEM,
        user=user,
        schema_name="ReportNarrative",
        schema={
            "summary": "string (<=4 sentences)",
            "suggestedActions": [{"title": "string", "description": "string", "priority": "High|Medium|Low"}],
            "personaBriefDescription": "string (optional)",
        },
        fallback={},
        max_output_tokens=max_output_tokens,
    )

    updates: Dict[str, Any] = {}
    data = result.value if isinstance(result.value, dict) else {}

    summary = data.get("summary")
    if isinstance(summary, str) and is_precise_text(summary, max_len=700):
        updates["summary"] = summary.strip()

    desc = data.get("personaBriefDescription")
    if isinstance(desc, str) and is_precise_text(desc, max_len=500):
        updates["personaBriefDescription"] = desc.strip()

    actions = data.get("suggestedActions")
    if isinstance(actions, list):
        clean: List[Dict[str, Any]] = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            title = a.get("title")
            if not (isinstance(title, str) and title.strip()):
                continue
            if not is_precise_text(title, max_len=120):
                continue
            description = a.get("description") if isinstance(a.get("description"), str) else ""
            description = description.strip()
            priority = a.get("priority") if a.get("priority") in ("High", "Medium", "Low") else "Medium"
            # Emit both keys: the frontend reads `detail`; `description` mirrors it
            # for consumers expecting the richer schema.
            clean.append({
                "title": title.strip(),
                "detail": description,
                "description": description,
                "priority": priority,
            })
        if clean:
            updates["suggestedActions"] = clean[:4]

    return result, updates


def _valid_str(value: Any, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _llm_persona_workflow(
    market: str,
    persona: str,
    custom_persona: str,
    sections: List[Dict[str, Any]],
    base_persona: Dict[str, Any],
    base_workflow: List[Dict[str, Any]],
    max_output_tokens: int,
) -> Tuple[LLMCallResult, Dict[str, Any], List[Dict[str, Any]]]:
    settings = get_settings()
    ranked = rank_sections_for_persona(sections, base_persona, market)
    context = summarize_sections(ranked, max_chars=settings.evidentia_max_context_chars)
    valid_codes = {s["citationId"] for s in sections}
    fallback_code = base_workflow[0]["evidenceCode"] if base_workflow else (sections[0]["citationId"] if sections else "SEC-4.2")

    result = generate_structured_object(
        system=ANALYST_SYSTEM,
        user=(
            f"Market: {market}\nPredefined persona: {persona or '(none)'}\n"
            f"Custom role (takes priority): {custom_persona or '(none)'}\n\n"
            f"Ranked source sections (only valid evidence codes in brackets):\n{context}\n\n"
            f"Baseline persona brief:\n{base_persona}\n\nBaseline workflow steps:\n{base_workflow}\n\n"
            "Return an improved persona brief and 4-6 concrete workflow steps. Each step's evidenceCode "
            "MUST be one of the bracketed citation ids; never invent ids."
        ),
        schema_name="PersonaWorkflow",
        schema={
            "personaBrief": {
                "title": "string", "description": "string", "goals": ["string"], "priorities": ["string"],
                "relevantTopics": ["string"], "riskFocus": ["string"], "outputStyle": "string",
            },
            "workflowSteps": [{
                "step": "number", "title": "string", "description": "string",
                "whyItMatters": "string", "expectedOutput": "string", "evidenceCode": "string",
            }],
        },
        fallback={},
        max_output_tokens=max_output_tokens,
    )
    data = result.value if isinstance(result.value, dict) else {}
    is_custom = bool(custom_persona and custom_persona.strip())

    # --- persona brief ---
    pb_in = data.get("personaBrief") if isinstance(data.get("personaBrief"), dict) else {}

    def arr(key: str) -> List[str]:
        v = pb_in.get(key)
        return v if isinstance(v, list) and v and all(isinstance(x, str) for x in v) else base_persona[key]

    persona_brief = {
        "title": custom_persona.strip() if is_custom else _valid_str(pb_in.get("title"), base_persona["title"]),
        "description": _valid_str(pb_in.get("description"), base_persona["description"]),
        "goals": arr("goals"),
        "priorities": arr("priorities"),
        "relevantTopics": arr("relevantTopics"),
        "riskFocus": arr("riskFocus"),
        "outputStyle": _valid_str(pb_in.get("outputStyle"), base_persona["outputStyle"]),
        "isCustom": is_custom,
    }

    # --- workflow ---
    raw = data.get("workflowSteps")
    workflow = base_workflow
    if isinstance(raw, list) and len(raw) >= 4:
        cleaned: List[Dict[str, Any]] = []
        for i, item in enumerate(raw[:6]):
            if not isinstance(item, dict):
                cleaned = []
                break
            base = base_workflow[i] if i < len(base_workflow) else {}
            ev = item.get("evidenceCode")
            if not (isinstance(ev, str) and ev in valid_codes):
                ev = base.get("evidenceCode") if base.get("evidenceCode") in valid_codes else fallback_code
            cleaned.append({
                "step": i + 1,
                "title": _valid_str(item.get("title"), base.get("title", f"Step {i + 1}")),
                "description": _valid_str(item.get("description"), base.get("description", "")),
                "whyItMatters": _valid_str(item.get("whyItMatters"), base.get("whyItMatters", "")),
                "expectedOutput": _valid_str(item.get("expectedOutput"), base.get("expectedOutput", "")),
                "evidenceCode": ev,
            })
        if len(cleaned) >= 4:
            workflow = cleaned

    return result, persona_brief, workflow


def _llm_risks(
    market: str,
    persona_brief: Dict[str, Any],
    sections: List[Dict[str, Any]],
    base_risks: List[Dict[str, Any]],
    max_output_tokens: int,
) -> Tuple[LLMCallResult, List[Dict[str, Any]]]:
    settings = get_settings()
    ranked = rank_sections_for_persona(sections, persona_brief, market)
    context = summarize_sections(ranked, max_chars=settings.evidentia_max_context_chars)
    valid_codes = {s["citationId"] for s in sections}
    fallback_code = base_risks[0]["evidenceCode"] if base_risks else (sections[0]["citationId"] if sections else "SEC-4.2")

    result = generate_structured_object(
        system=ANALYST_SYSTEM,
        user=(
            f"Market: {market}\nPersona: {persona_brief['title']}\n\n"
            f"Ranked source sections:\n{context}\n\nBaseline risks:\n{base_risks}\n\n"
            "Return 3-5 concrete risks. Each evidenceCode MUST be a real citation id from the sections."
        ),
        schema_name="RiskRegister",
        schema={"risks": [{
            "severity": "High|Medium|Low", "title": "string", "description": "string",
            "businessImpact": "string", "evidenceCode": "string", "recommendedFix": "string", "owner": "string",
        }]},
        fallback={},
        max_output_tokens=max_output_tokens,
    )
    data = result.value if isinstance(result.value, dict) else {}
    raw = data.get("risks")
    if not isinstance(raw, list) or len(raw) < 3:
        return result, base_risks

    cleaned: List[Dict[str, Any]] = []
    for i, item in enumerate(raw[:5]):
        if not isinstance(item, dict):
            return result, base_risks
        base = base_risks[i] if i < len(base_risks) else {}
        sev = item.get("severity") if item.get("severity") in ("High", "Medium", "Low") else base.get("severity", "Medium")
        ev = item.get("evidenceCode")
        if not (isinstance(ev, str) and ev in valid_codes):
            ev = base.get("evidenceCode") if base.get("evidenceCode") in valid_codes else fallback_code
        cleaned.append({
            "severity": sev,
            "title": _valid_str(item.get("title"), base.get("title", "Risk")),
            "description": _valid_str(item.get("description"), base.get("description", "")),
            "businessImpact": _valid_str(item.get("businessImpact"), base.get("businessImpact", "")),
            "evidenceCode": ev,
            "recommendedFix": _valid_str(item.get("recommendedFix"), base.get("recommendedFix", "")),
            "owner": _valid_str(item.get("owner"), base.get("owner", "Platform Eng")),
        })
    if len(cleaned) < 3:
        return result, base_risks
    if not any(r["severity"] == "High" for r in cleaned):
        cleaned[0]["severity"] = "High"
    if not any(r["severity"] == "Medium" for r in cleaned) and len(cleaned) > 1:
        cleaned[-1]["severity"] = "Medium"
    return result, cleaned


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

    intensity = settings.effective_intensity()
    model = settings.evidentia_llm_model

    documents, sections = document_reader(selected_document_ids)
    doc_ids = [d["id"] for d in documents]

    # --- cache lookup ---
    cache_key = _cache_key(market, persona, custom_persona, doc_ids, intensity, model)
    if settings.evidentia_enable_cache and cache_key in _CACHE:
        logger.info(
            "[Evidentia LLM] intensity=%s calls=0 model=%s contextChars=0 mode=%s (cache hit)",
            intensity, model if intensity != "off" else None, _CACHE[cache_key]["generationMode"],
        )
        return copy.deepcopy(_CACHE[cache_key])

    persona_key = resolve_persona_key(persona, custom_persona)
    report_id = _derive_id(market, persona, custom_persona, doc_ids)

    # --- deterministic baseline (always) ---
    persona_brief = persona_mapper(market, persona, custom_persona, sections)
    workflow_steps = workflow_builder(persona_key, market, sections)
    risks = risk_analyzer(persona_key, market, sections)
    citations = citation_binder(sections, workflow_steps, risks)

    llm_calls = 0
    context_chars = 0

    if intensity == "full":
        try:
            r1, persona_brief, workflow_steps = _llm_persona_workflow(
                market, persona, custom_persona, sections, persona_brief, workflow_steps,
                settings.evidentia_max_output_tokens,
            )
            llm_calls += 1 if r1.called else 0
            context_chars += r1.input_chars

            r2, risks = _llm_risks(market, persona_brief, sections, risks, settings.evidentia_max_output_tokens)
            llm_calls += 1 if r2.called else 0
            context_chars += r2.input_chars
            citations = citation_binder(sections, workflow_steps, risks)  # re-bind grounded evidence
        except Exception:  # noqa: BLE001
            intensity = "off"  # unexpected failure → deterministic

    # --- metrics + report assembly (deterministic) ---
    metrics = metrics_agent(
        documents, sections, citations, risks, workflow_steps, market, persona_key, persona_brief["title"]
    )
    agent_steps = build_agent_steps(documents, sections, risks, citations, workflow_steps, persona_brief["title"])
    report = report_composer(
        report_id=report_id, market=market, persona=persona, custom_persona=custom_persona,
        persona_key=persona_key, persona_brief=persona_brief, documents=documents, sections=sections,
        workflow_steps=workflow_steps, risks=risks, citations=citations, metrics=metrics,
        agent_steps=agent_steps, generated_at=generated_at,
    )

    # --- narrative polish (summary + full share one final call) ---
    if intensity in ("summary", "full"):
        try:
            max_tokens = 500 if intensity == "summary" else settings.evidentia_max_output_tokens
            r_polish, updates = _llm_report_polish(report, sections, max_tokens)
            llm_calls += 1 if r_polish.called else 0
            context_chars += r_polish.input_chars
            if "summary" in updates:
                report["summary"] = updates["summary"]
            # topFinding is intentionally kept deterministic (clean + executive).
            if "personaBriefDescription" in updates:
                report["personaBrief"]["description"] = updates["personaBriefDescription"]
            if "suggestedActions" in updates:
                report["suggestedActions"] = updates["suggestedActions"]
        except Exception:  # noqa: BLE001
            pass

    # --- generation metadata ---
    if intensity == "off":
        report["suggestedActions"] = suggested_actions_for(persona_key)
        report["generationMode"] = "deterministic"
        report["llmProvider"] = "none"
        report["llmModel"] = None
    elif intensity == "summary":
        report["generationMode"] = "llm-summary"
        report["llmProvider"] = settings.active_provider()
        report["llmModel"] = settings.active_model()
    else:  # full
        report["generationMode"] = "llm-assisted"
        report["llmProvider"] = settings.active_provider()
        report["llmModel"] = settings.active_model()

    logger.info(
        "[Evidentia LLM] intensity=%s calls=%d model=%s contextChars=%d mode=%s",
        intensity, llm_calls, model if intensity != "off" else None, context_chars, report["generationMode"],
    )

    if settings.evidentia_enable_cache:
        _CACHE[cache_key] = copy.deepcopy(report)

    return report
