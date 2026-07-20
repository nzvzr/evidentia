import type { AgentInput, WorkspaceSelection } from "./types";

/** Map workspace persona ids to backend persona titles. */
export const PERSONA_TITLE_BY_ID: Record<string, string> = {
  support: "Support Agent",
  sales: "Sales Engineer",
  compliance: "Compliance Officer",
  ops: "Operations Manager",
  architect: "Solutions Architect",
  newhire: "New Hire",
};

/** Build authenticated generation input from real tenant document ids. */
export function buildAgentInput(selection: WorkspaceSelection): AgentInput {
  const market = selection.market || "EMEA";
  const isCustom = selection.persona === "custom" || !!selection.custom.trim();
  const persona = isCustom ? "" : PERSONA_TITLE_BY_ID[selection.persona] || "Support Agent";
  const customPersona = isCustom ? selection.custom.trim() : "";
  const selectedDocumentIds = selection.picked.filter(Boolean);
  return { market, persona, customPersona, selectedDocumentIds };
}
