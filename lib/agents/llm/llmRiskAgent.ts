import { generateStructuredObject } from "@/lib/llm/provider";
import {
  findApiRisks,
  findIncidentEscalationRisks,
  findResidencyRisks,
  findSlaRisks,
  summarizeSectionsForPrompt,
} from "@/lib/tools/documentTools";
import type { DocumentSection, PersonaBrief, RiskItem, WorkflowStep } from "@/lib/types";

const SEVERITIES: RiskItem["severity"][] = ["High", "Medium", "Low"];
const asString = (v: unknown, fallback: string): string =>
  typeof v === "string" && v.trim() ? v.trim() : fallback;

/**
 * LLM-assisted risk analyzer. Returns 3–5 grounded risks with valid evidence
 * codes; guarantees at least one High and one Medium.
 */
export async function llmRiskAgent(args: {
  market: string;
  personaBrief: PersonaBrief;
  sections: DocumentSection[];
  workflowSteps: WorkflowStep[];
  baseline: RiskItem[];
}): Promise<RiskItem[]> {
  const { market, personaBrief, sections, baseline } = args;
  const validCodes = new Set(sections.map((s) => s.citationId));
  const fallbackCode = baseline[0]?.evidenceCode ?? sections[0]?.citationId ?? "SEC-4.2";

  // Deterministic tool signals give the model grounded hints.
  const signals = {
    residency: findResidencyRisks({ sections, market }).map((s) => s.citationId),
    sla: findSlaRisks({ sections }).map((s) => s.citationId),
    api: findApiRisks({ sections }).map((s) => s.citationId),
    escalation: findIncidentEscalationRisks({ sections }).map((s) => s.citationId),
  };

  const result = await generateStructuredObject<{ risks?: unknown }>({
    schemaName: "RiskRegister",
    schema: {
      risks: [
        {
          severity: "High | Medium | Low",
          title: "string",
          description: "string",
          businessImpact: "string",
          evidenceCode: "string (must be a provided citation id)",
          recommendedFix: "string",
          owner: "string",
        },
      ],
    },
    system:
      "You are Evidentia's Risk Analyzer. Identify 3-5 concrete risks supported by the document context. " +
      "Prefer data residency, SLA, API rate-limit, incident escalation, and compliance issues when the sources support them. " +
      "Every evidenceCode must be a real citation id from the context. Do not invent ids.",
    user:
      `Market: ${market}\n` +
      `Persona: ${JSON.stringify(personaBrief)}\n\n` +
      `Grounded signals (citation ids by risk area): ${JSON.stringify(signals)}\n\n` +
      `Document context:\n${summarizeSectionsForPrompt({ sections })}\n\n` +
      `Baseline risks (improve on these):\n${JSON.stringify(baseline)}`,
    fallback: { risks: baseline },
  });

  const raw = Array.isArray(result.risks) ? result.risks : baseline;
  let cleaned: RiskItem[] = raw
    .map((item, i) => {
      const r = (item ?? {}) as Record<string, unknown>;
      const base = baseline[i];
      const severity = SEVERITIES.includes(r.severity as RiskItem["severity"])
        ? (r.severity as RiskItem["severity"])
        : base?.severity ?? "Medium";
      const evidence = typeof r.evidenceCode === "string" && validCodes.has(r.evidenceCode)
        ? r.evidenceCode
        : base?.evidenceCode && validCodes.has(base.evidenceCode)
          ? base.evidenceCode
          : fallbackCode;
      return {
        severity,
        title: asString(r.title, base?.title ?? "Risk"),
        description: asString(r.description, base?.description ?? ""),
        businessImpact: asString(r.businessImpact, base?.businessImpact ?? ""),
        evidenceCode: evidence,
        recommendedFix: asString(r.recommendedFix, base?.recommendedFix ?? ""),
        owner: asString(r.owner, base?.owner ?? "Platform Eng"),
      };
    })
    .slice(0, 5);

  if (cleaned.length < 3) cleaned = baseline;

  // Guarantee at least one High and one Medium.
  if (!cleaned.some((r) => r.severity === "High") && cleaned.length > 0) cleaned[0].severity = "High";
  if (!cleaned.some((r) => r.severity === "Medium") && cleaned.length > 1) {
    cleaned[cleaned.length - 1].severity = "Medium";
  }

  return cleaned;
}
