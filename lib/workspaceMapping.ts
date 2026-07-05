import type { AgentInput, DocId, WorkspaceSelection } from "./types";

/** Map the workspace UI document ids to pipeline slug ids. */
export const DOC_SLUG_BY_ID: Record<DocId, string> = {
  d1: "security-compliance-whitepaper",
  d2: "platform-api-reference",
  d3: "sla-uptime-commitment",
  d4: "deployment-migration-guide",
  d5: "data-residency-sovereignty-policy",
  d6: "incident-response-runbook",
  d7: "pricing-packaging-sheet",
  d8: "customer-onboarding-handbook",
};

/** Map workspace persona ids to pipeline persona titles. */
export const PERSONA_TITLE_BY_ID: Record<string, string> = {
  support: "Support Agent",
  sales: "Sales Engineer",
  compliance: "Compliance Officer",
  ops: "Operations Manager",
  architect: "Solutions Architect",
  newhire: "New Hire",
};

/** Build the pipeline input from a workspace selection. */
export function buildAgentInput(selection: WorkspaceSelection): AgentInput {
  const market = selection.market || "EMEA";
  const isCustom = selection.persona === "custom" || !!selection.custom.trim();
  const persona = isCustom ? "" : PERSONA_TITLE_BY_ID[selection.persona] || "Support Agent";
  const customPersona = isCustom ? selection.custom.trim() : "";
  const selectedDocumentIds = selection.picked
    .map((id) => DOC_SLUG_BY_ID[id])
    .filter((x): x is string => !!x);
  return { market, persona, customPersona, selectedDocumentIds };
}
