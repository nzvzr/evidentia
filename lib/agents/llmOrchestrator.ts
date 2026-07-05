import type { AgentInput, EvidentiaReport } from "@/lib/types";
import { activeModel, activeProvider, isLlmEnabled } from "@/lib/env";
import { runEvidentiaAgents, type RunOptions } from "./orchestrator";
import { documentReaderAgent } from "./documentReaderAgent";
import { resolvePersonaKey } from "./personaMapperAgent";
import { metricsAgent } from "./metricsAgent";
import { buildAgentSteps, reportAgent } from "./reportAgent";
import { llmPersonaAgent } from "./llm/llmPersonaAgent";
import { llmWorkflowAgent } from "./llm/llmWorkflowAgent";
import { llmRiskAgent } from "./llm/llmRiskAgent";
import { llmCitationAgent } from "./llm/llmCitationAgent";
import { llmReportAgent } from "./llm/llmReportAgent";

const DEFAULT_MARKET = "EMEA";
const DEFAULT_PERSONA = "Support Agent";

/**
 * Agentic pipeline v2.
 *
 * Runs the deterministic pipeline first (always), then, when an LLM is enabled
 * and configured, refines persona, workflow, risks, citations, and the report
 * narrative with LLM agents. Each LLM step falls back to the deterministic
 * baseline on any failure, so the API never crashes and the demo always works.
 */
export async function runEvidentiaAgentsV2(
  input: AgentInput,
  options: RunOptions = {},
): Promise<EvidentiaReport> {
  const base = runEvidentiaAgents(input, options);

  if (!isLlmEnabled()) {
    return { ...base, generationMode: "deterministic", llmProvider: "none" };
  }

  try {
    const customPersona = (input.customPersona || "").trim();
    const market = (input.market || "").trim() || DEFAULT_MARKET;
    const persona = customPersona
      ? (input.persona || "").trim()
      : (input.persona || "").trim() || DEFAULT_PERSONA;

    const { documents, sections } = documentReaderAgent(input.selectedDocumentIds);
    const personaKey = resolvePersonaKey(persona, customPersona);

    const personaBrief = await llmPersonaAgent({
      market,
      persona,
      customPersona,
      sections,
      baseline: base.personaBrief,
    });

    const workflowSteps = await llmWorkflowAgent({
      market,
      personaBrief,
      sections,
      baseline: base.workflowSteps,
    });

    const risks = await llmRiskAgent({
      market,
      personaBrief,
      sections,
      workflowSteps,
      baseline: base.risks,
    });

    const citations = await llmCitationAgent({
      sections,
      workflowSteps,
      risks,
      baseline: base.citations,
    });

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

    const agentSteps = buildAgentSteps({
      documents,
      sections,
      risks,
      citations,
      workflowSteps,
      personaTitle: personaBrief.title,
    });

    const draft = reportAgent({
      id: base.id,
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
      generatedAt: base.generatedAt,
    });

    const refinement = await llmReportAgent({ draft, workflowSteps, risks, citations });

    return {
      ...draft,
      summary: refinement.summary,
      topFinding: refinement.topFinding,
      suggestedActions: refinement.suggestedActions,
      generationMode: "llm-assisted",
      llmProvider: activeProvider(),
      llmModel: activeModel(),
    };
  } catch (error) {
    if (typeof window === "undefined") {
      console.error("[evidentia:llm] pipeline refinement failed; using deterministic output:", error);
    }
    return { ...base, generationMode: "deterministic", llmProvider: "none" };
  }
}
