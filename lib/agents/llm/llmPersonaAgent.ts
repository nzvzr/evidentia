import { generateStructuredObject } from "@/lib/llm/provider";
import { summarizeSectionsForPrompt } from "@/lib/tools/documentTools";
import type { DocumentSection, PersonaBrief } from "@/lib/types";

const asStringArray = (v: unknown, fallback: string[]): string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string") && v.length > 0 ? (v as string[]) : fallback;

const asString = (v: unknown, fallback: string): string =>
  typeof v === "string" && v.trim() ? v.trim() : fallback;

/**
 * LLM-assisted persona modeler. Refines the deterministic PersonaBrief.
 * Custom roles always take priority for the title/isCustom flag.
 */
export async function llmPersonaAgent(args: {
  market: string;
  persona: string;
  customPersona?: string;
  sections: DocumentSection[];
  baseline: PersonaBrief;
}): Promise<PersonaBrief> {
  const { market, persona, customPersona, sections, baseline } = args;

  const result = await generateStructuredObject<Partial<PersonaBrief>>({
    schemaName: "PersonaBrief",
    schema: {
      title: "string",
      description: "string (2-3 sentences)",
      goals: "string[]",
      priorities: "string[]",
      relevantTopics: "string[]",
      riskFocus: "string[]",
      outputStyle: "string",
    },
    system:
      "You are Evidentia's Persona Modeler. Model the reader's role for an enterprise documentation playbook. " +
      "Infer responsibilities, priorities, relevant topics, risk focus, and preferred output style. " +
      "Ground everything in the provided document context and market. Return concise, professional content.",
    user:
      `Market: ${market}\n` +
      `Predefined persona: ${persona || "(none)"}\n` +
      `Custom role (takes priority if present): ${customPersona || "(none)"}\n\n` +
      `Document context:\n${summarizeSectionsForPrompt({ sections })}\n\n` +
      `Baseline persona brief (improve on this):\n${JSON.stringify(baseline)}`,
    fallback: baseline,
  });

  const isCustom = !!(customPersona && customPersona.trim());
  return {
    title: isCustom ? customPersona!.trim() : asString(result.title, baseline.title),
    description: asString(result.description, baseline.description),
    goals: asStringArray(result.goals, baseline.goals),
    priorities: asStringArray(result.priorities, baseline.priorities),
    relevantTopics: asStringArray(result.relevantTopics, baseline.relevantTopics),
    riskFocus: asStringArray(result.riskFocus, baseline.riskFocus),
    outputStyle: asString(result.outputStyle, baseline.outputStyle),
    isCustom,
  };
}
