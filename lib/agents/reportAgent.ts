import type {
  AgentStep,
  Citation,
  DocumentMeta,
  DocumentSection,
  EvidentiaReport,
  PersonaBrief,
  ReportMetrics,
  RiskItem,
  SuggestedAction,
  WorkflowStep,
} from "@/lib/types";
import type { PersonaKey } from "./personaMapperAgent";

export const PIPELINE_COMPANY = "Northreach Cloud";
/** Deterministic default stamp so demo/static generation is hydration-safe. */
export const DEFAULT_GENERATED_AT = "2026-07-05T08:30:00.000Z";

const SUGGESTED_ACTIONS: Record<PersonaKey, SuggestedAction[]> = {
  support: [
    { title: "Draft a customer-safe reply", detail: "Generate a cited response for the current ticket." },
    { title: "Verify SLA entitlement before promising remediation", detail: "Confirm region and tier commitments first." },
    { title: "Escalate privacy or billing cases", detail: "Route sensitive cases through the correct on-call path." },
    { title: "Attach citations to the ticket", detail: "Link each claim to its source passage." },
  ],
  sales: [
    { title: "Generate a buyer-facing proof brief", detail: "Cited security and SLA talking points for the deal." },
    { title: "Validate compliance claims before demo", detail: "Confirm each claim maps to documented evidence." },
    { title: "Confirm deployment constraints", detail: "Check residency and rate limits for the target market." },
    { title: "Attach source-backed architecture notes", detail: "Package the POC architecture with citations." },
  ],
  compliance: [
    { title: "Open the residency gap", detail: "Escalate the metadata-routing finding to engineering." },
    { title: "Export a controls matrix", detail: "Map documented controls to SOC 2 / ISO 27001 criteria." },
    { title: "Schedule an attestation review", detail: "Book the pre-audit walkthrough with evidence attached." },
    { title: "Flag unsupported claims", detail: "List customer-facing claims lacking a citation." },
  ],
  ops: [
    { title: "Model egress costs", detail: "Project overage exposure across the top regions." },
    { title: "Refresh the runbook", detail: "Replace deprecated tooling and re-verify escalation paths." },
    { title: "Set uptime alert thresholds", detail: "Define alerting aligned to the 99.99% SLA commitment." },
    { title: "Confirm rollback rehearsal", detail: "Add a rollback test to the next change window." },
  ],
  architect: [
    { title: "Generate a reference diagram brief", detail: "Component list and data-flow notes for the diagram." },
    { title: "Validate residency topology", detail: "Confirm in-region processing for the selected market." },
    { title: "List API rate limits", detail: "Extract the limits the reference design must respect." },
    { title: "Document failover assumptions", detail: "Record each design decision with a citation." },
  ],
  newhire: [
    { title: "Generate a 2-week ramp plan", detail: "A sequenced learning path with daily objectives." },
    { title: "Take the platform basics quiz", detail: "Check comprehension of core deployment concepts." },
    { title: "Meet your escalation contacts", detail: "Identify the on-call owners for your first rotations." },
    { title: "Bookmark the citation library", detail: "Keep the source index handy for questions." },
  ],
  field: [
    { title: "Open the on-site checklist", detail: "Follow the documented, safety-first procedure." },
    { title: "File an incident report", detail: "Log actions with timestamps for follow-up." },
    { title: "Confirm the live escalation path", detail: "Avoid the deprecated on-call tool." },
    { title: "Set customer-facing boundaries", detail: "Share only approved information on site." },
  ],
};

const CATEGORY_BY_PERSONA: Record<PersonaKey, string> = {
  support: "Support",
  sales: "Sales",
  compliance: "Compliance",
  ops: "Operations",
  architect: "Architecture",
  newhire: "Support",
  field: "Operations",
};

export function buildAgentSteps(args: {
  documents: DocumentMeta[];
  sections: DocumentSection[];
  risks: RiskItem[];
  citations: Citation[];
  workflowSteps: WorkflowStep[];
  personaTitle: string;
}): AgentStep[] {
  const high = args.risks.filter((r) => r.severity === "High").length;
  const med = args.risks.filter((r) => r.severity === "Medium").length;
  const low = args.risks.filter((r) => r.severity === "Low").length;
  const passages = (args.sections.length * 41).toLocaleString();
  return [
    { agent: "Document Ingest", status: "complete", detail: `Parsed ${args.documents.length} documents → ${passages} passages`, duration: "0.6s" },
    { agent: "Persona Modeler", status: "complete", detail: `Modeled ${args.personaTitle} profile & priorities`, duration: "0.4s" },
    { agent: "Semantic Retrieval", status: "complete", detail: `Indexed & ranked ${args.sections.length} sections`, duration: "1.1s" },
    { agent: "Risk Analyzer", status: "complete", detail: `Flagged ${args.risks.length} risks (${high} high / ${med} med / ${low} low)`, duration: "0.9s" },
    { agent: "Brief Synthesizer", status: "complete", detail: `Composed persona brief + ${args.workflowSteps.length} workflow steps`, duration: "0.7s" },
    { agent: "Citation Binder", status: "complete", detail: `Linked ${args.citations.length} citations to source spans`, duration: "0.5s" },
    { agent: "Playbook Composer", status: "complete", detail: "Assembled exportable playbook", duration: "0.3s" },
  ];
}

interface ReportAgentArgs {
  id: string;
  market: string;
  persona: string;
  customPersona?: string;
  personaKey: PersonaKey;
  personaBrief: PersonaBrief;
  documents: DocumentMeta[];
  sections: DocumentSection[];
  workflowSteps: WorkflowStep[];
  risks: RiskItem[];
  citations: Citation[];
  metrics: ReportMetrics;
  agentSteps: AgentStep[];
  generatedAt: string;
}

/**
 * Report Agent / Playbook Composer.
 * Assembles the final EvidentiaReport, including a narrative summary,
 * top finding, and persona-specific suggested actions.
 */
export function reportAgent(args: ReportAgentArgs): EvidentiaReport {
  const personaTitle = args.personaBrief.title;
  const topRisk = args.risks.find((r) => r.severity === "High") ?? args.risks[0];
  const topFinding = topRisk
    ? `${topRisk.title}: ${topRisk.businessImpact}`
    : `Prioritize ${args.market} readiness for the ${personaTitle}.`;

  const customNote = args.personaBrief.isCustom
    ? " This playbook was generated from a custom role description."
    : "";

  const summary =
    `This playbook translates ${PIPELINE_COMPANY}'s enterprise documentation into an operating brief for a ${personaTitle} in the ${args.market} market.${customNote} ` +
    `Evidentia analyzed ${args.metrics.documentsAnalyzed} documents across ${args.metrics.passagesIndexed.toLocaleString()} passages, ` +
    `linked ${args.metrics.citationsUsed} source-traced citations, and flagged ${args.metrics.risksFlagged} risks. ` +
    `The key finding is: ${topFinding} ` +
    `The recommended ${args.workflowSteps.length}-step workflow below is prioritized around ${args.personaBrief.priorities.join(", ").toLowerCase()}.`;

  return {
    id: args.id,
    company: PIPELINE_COMPANY,
    market: args.market,
    persona: personaTitle,
    customPersona: args.customPersona || undefined,
    category: CATEGORY_BY_PERSONA[args.personaKey],
    generatedAt: args.generatedAt,
    confidence: args.metrics.confidence,
    summary,
    topFinding,
    agentSteps: args.agentSteps,
    personaBrief: args.personaBrief,
    workflowSteps: args.workflowSteps,
    risks: args.risks,
    citations: args.citations,
    metrics: args.metrics,
    suggestedActions: SUGGESTED_ACTIONS[args.personaKey],
  };
}
