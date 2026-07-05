import { generateStructuredObject } from "@/lib/llm/provider";
import { summarizeSectionsForPrompt } from "@/lib/tools/documentTools";
import type { Citation, DocumentSection, RiskItem, WorkflowStep } from "@/lib/types";

const asString = (v: unknown, fallback: string): string =>
  typeof v === "string" && v.trim() ? v.trim() : fallback;

/**
 * LLM-assisted citation binder. Citations are strictly grounded: only ids that
 * exist in the provided sections are allowed, and source/section/excerpt are
 * taken from the real section to prevent invented evidence.
 */
export async function llmCitationAgent(args: {
  sections: DocumentSection[];
  workflowSteps: WorkflowStep[];
  risks: RiskItem[];
  baseline: Citation[];
}): Promise<Citation[]> {
  const { sections, baseline } = args;
  const byId = new Map<string, DocumentSection>();
  sections.forEach((s) => {
    if (!byId.has(s.citationId)) byId.set(s.citationId, s);
  });

  const result = await generateStructuredObject<{ citations?: unknown }>({
    schemaName: "CitationSet",
    schema: {
      citations: [
        { id: "string (must be a provided citation id)", whyItMatters: "string" },
      ],
    },
    system:
      "You are Evidentia's Citation Binder. Select the citations that best support the workflow and risks. " +
      "Only use citation ids present in the document context. Never invent sources or ids. " +
      "For each, explain briefly why it matters. Source text is fixed by the system.",
    user:
      `Referenced evidence codes: ${JSON.stringify([
        ...new Set([...args.workflowSteps.map((w) => w.evidenceCode), ...args.risks.map((r) => r.evidenceCode)]),
      ])}\n\n` +
      `Document context:\n${summarizeSectionsForPrompt({ sections, maxChars: 3000 })}\n\n` +
      `Baseline citations:\n${JSON.stringify(baseline)}`,
    fallback: { citations: baseline },
  });

  const raw = Array.isArray(result.citations) ? result.citations : [];
  const seen = new Set<string>();
  const grounded: Citation[] = [];
  for (const item of raw) {
    const c = (item ?? {}) as Record<string, unknown>;
    const id = typeof c.id === "string" ? c.id : "";
    const section = byId.get(id);
    if (!section || seen.has(id)) continue;
    seen.add(id);
    const baseMatch = baseline.find((b) => b.id === id);
    grounded.push({
      id: section.citationId,
      source: `${section.source} · ${section.sectionTitle}`,
      section: section.sectionTitle,
      excerpt: section.excerpt,
      whyItMatters: asString(c.whyItMatters, baseMatch?.whyItMatters ?? `Supports the ${section.sectionTitle.toLowerCase()} guidance.`),
    });
  }

  // If the model produced nothing usable, keep the deterministic baseline.
  return grounded.length > 0 ? grounded : baseline;
}
