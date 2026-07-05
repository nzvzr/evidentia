import { generateStructuredObject } from "@/lib/llm/provider";
import type { Citation, EvidentiaReport, RiskItem, SuggestedAction, WorkflowStep } from "@/lib/types";

const asString = (v: unknown, fallback: string): string =>
  typeof v === "string" && v.trim() ? v.trim() : fallback;

export interface LlmReportRefinement {
  summary: string;
  topFinding: string;
  suggestedActions: SuggestedAction[];
}

/**
 * LLM-assisted playbook composer. Refines the narrative summary, top finding,
 * and suggested actions. All factual claims must stay grounded in the provided
 * citations/risks — falls back to the deterministic draft on any failure.
 */
export async function llmReportAgent(args: {
  draft: EvidentiaReport;
  workflowSteps: WorkflowStep[];
  risks: RiskItem[];
  citations: Citation[];
}): Promise<LlmReportRefinement> {
  const { draft, risks, citations } = args;
  const fallback: LlmReportRefinement = {
    summary: draft.summary,
    topFinding: draft.topFinding,
    suggestedActions: draft.suggestedActions,
  };

  const result = await generateStructuredObject<Partial<LlmReportRefinement>>({
    schemaName: "ReportNarrative",
    schema: {
      summary: "string (2-4 sentences)",
      topFinding: "string (1 sentence)",
      suggestedActions: [{ title: "string", detail: "string" }],
    },
    system:
      "You are Evidentia's Playbook Composer. Write an executive summary, a single top finding, and 3-4 " +
      "persona-specific suggested actions. Keep every factual claim grounded in the provided risks and citations. " +
      "Do not introduce facts that are not supported.",
    user:
      `Company: ${draft.company}\nMarket: ${draft.market}\nPersona: ${draft.persona}\n\n` +
      `Risks:\n${JSON.stringify(risks)}\n\n` +
      `Citations:\n${JSON.stringify(citations.map((c) => ({ id: c.id, source: c.source })))}\n\n` +
      `Baseline summary:\n${draft.summary}\n\nBaseline top finding:\n${draft.topFinding}\n\n` +
      `Baseline suggested actions:\n${JSON.stringify(draft.suggestedActions)}`,
    fallback,
  });

  const actions = Array.isArray(result.suggestedActions)
    ? (result.suggestedActions as unknown[])
        .map((a) => {
          const o = (a ?? {}) as Record<string, unknown>;
          if (typeof o.title !== "string" || !o.title.trim()) return null;
          return { title: o.title.trim(), detail: asString(o.detail, "") };
        })
        .filter((a): a is SuggestedAction => a !== null)
    : [];

  return {
    summary: asString(result.summary, fallback.summary),
    topFinding: asString(result.topFinding, fallback.topFinding),
    suggestedActions: actions.length > 0 ? actions : fallback.suggestedActions,
  };
}
