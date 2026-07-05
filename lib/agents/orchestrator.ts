import type { AgentInput, EvidentiaReport } from "@/lib/types";
import { documentReaderAgent } from "./documentReaderAgent";
import { personaMapperAgent, resolvePersonaKey } from "./personaMapperAgent";
import { workflowBuilderAgent } from "./workflowBuilderAgent";
import { riskAgent } from "./riskAgent";
import { citationAgent } from "./citationAgent";
import { metricsAgent } from "./metricsAgent";
import { buildAgentSteps, reportAgent, DEFAULT_GENERATED_AT } from "./reportAgent";

export interface RunOptions {
  /** ISO timestamp; defaults to a fixed stamp for deterministic output */
  generatedAt?: string;
}

const DEFAULT_MARKET = "EMEA";
const DEFAULT_PERSONA = "Support Agent";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}

/** Small, stable hash for deterministic report ids. */
function hash(value: string): string {
  let h = 5381;
  for (let i = 0; i < value.length; i += 1) {
    h = (h * 33) ^ value.charCodeAt(i);
  }
  return (h >>> 0).toString(36);
}

function deriveId(market: string, persona: string, customPersona: string, docs: string[]): string {
  const roleSlug = customPersona ? slugify(customPersona) : slugify(persona);
  const marketSlug = slugify(market);
  const docHash = hash([...docs].sort().join("|"));
  return `${roleSlug || "role"}-${marketSlug || "market"}-${docHash}`;
}

/**
 * Runs the deterministic Evidentia multi-agent pipeline end to end and returns
 * a complete EvidentiaReport. Fully offline — no external APIs required.
 */
export function runEvidentiaAgents(input: AgentInput, options: RunOptions = {}): EvidentiaReport {
  const customPersona = (input.customPersona || "").trim();
  const market = (input.market || "").trim() || DEFAULT_MARKET;
  const persona = customPersona ? (input.persona || "").trim() : (input.persona || "").trim() || DEFAULT_PERSONA;
  const generatedAt = options.generatedAt || DEFAULT_GENERATED_AT;

  // 1. Document Reader
  const { documents, sections } = documentReaderAgent(input.selectedDocumentIds);

  // 2. Persona Mapper
  const personaKey = resolvePersonaKey(persona, customPersona);
  const personaBrief = personaMapperAgent(market, persona, customPersona, sections);

  // 3. Workflow Builder
  const workflowSteps = workflowBuilderAgent(personaKey, market, sections);

  // 4. Risk Agent
  const risks = riskAgent(personaKey, market, sections);

  // 5. Citation Agent
  const citations = citationAgent(sections, workflowSteps, risks);

  // 6. Metrics Agent
  const metrics = metricsAgent({
    documents,
    sections,
    citations,
    risks,
    workflowSteps,
    market,
    personaKey,
    personaTitle: personaBrief.title,
  });

  // 7. Report Agent
  const agentSteps = buildAgentSteps({
    documents,
    sections,
    risks,
    citations,
    workflowSteps,
    personaTitle: personaBrief.title,
  });

  const id =
    input.id ||
    deriveId(market, persona, customPersona, documents.map((d) => d.id));

  return reportAgent({
    id,
    market,
    persona,
    customPersona,
    personaKey,
    personaBrief,
    documents,
    sections,
    workflowSteps,
    risks,
    citations,
    metrics,
    agentSteps,
    generatedAt,
  });
}
