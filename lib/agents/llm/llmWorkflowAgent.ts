import { generateStructuredObject } from "@/lib/llm/provider";
import { summarizeSectionsForPrompt } from "@/lib/tools/documentTools";
import type { DocumentSection, PersonaBrief, WorkflowStep } from "@/lib/types";

const asString = (v: unknown, fallback: string): string =>
  typeof v === "string" && v.trim() ? v.trim() : fallback;

/**
 * LLM-assisted workflow builder. Returns 4–6 improved steps; each evidenceCode
 * is forced to a citation id that exists in the provided sections.
 */
export async function llmWorkflowAgent(args: {
  market: string;
  personaBrief: PersonaBrief;
  sections: DocumentSection[];
  baseline: WorkflowStep[];
}): Promise<WorkflowStep[]> {
  const { market, personaBrief, sections, baseline } = args;
  const validCodes = new Set(sections.map((s) => s.citationId));
  const fallbackCode = baseline[0]?.evidenceCode ?? sections[0]?.citationId ?? "SEC-4.2";

  const result = await generateStructuredObject<{ steps?: unknown }>({
    schemaName: "WorkflowPlan",
    schema: {
      steps: [
        {
          step: "number",
          title: "string",
          description: "string",
          whyItMatters: "string",
          expectedOutput: "string",
          evidenceCode: "string (must be one of the provided citation ids)",
        },
      ],
    },
    system:
      "You are Evidentia's Workflow Builder. Produce a practical, role-specific, sequenced workflow (4-6 steps) " +
      "for the given persona and market. Each step must cite an evidenceCode that exists in the provided document context. " +
      "Do not invent citation ids.",
    user:
      `Market: ${market}\n` +
      `Persona: ${JSON.stringify(personaBrief)}\n\n` +
      `Document context (valid evidence codes in brackets):\n${summarizeSectionsForPrompt({ sections })}\n\n` +
      `Baseline steps (improve on these):\n${JSON.stringify(baseline)}`,
    fallback: { steps: baseline },
  });

  const raw = Array.isArray(result.steps) ? result.steps : baseline;
  const cleaned: WorkflowStep[] = raw
    .map((item, i) => {
      const s = (item ?? {}) as Record<string, unknown>;
      const base = baseline[i];
      const evidence = typeof s.evidenceCode === "string" && validCodes.has(s.evidenceCode)
        ? s.evidenceCode
        : base?.evidenceCode && validCodes.has(base.evidenceCode)
          ? base.evidenceCode
          : fallbackCode;
      return {
        step: i + 1,
        title: asString(s.title, base?.title ?? `Step ${i + 1}`),
        description: asString(s.description, base?.description ?? ""),
        whyItMatters: asString(s.whyItMatters, base?.whyItMatters ?? ""),
        expectedOutput: asString(s.expectedOutput, base?.expectedOutput ?? ""),
        evidenceCode: evidence,
      };
    })
    .slice(0, 6);

  // Guarantee 4–6 steps; fall back if the model returned too few.
  if (cleaned.length < 4) return baseline;
  return cleaned;
}
