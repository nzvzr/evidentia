import type { PlaybookRecord } from "./types";

/**
 * Deterministic demo playbooks shown in the Playbooks library.
 * Each carries a workspace selection so "View report" / "Export PDF"
 * can re-hydrate the report and playbook pages.
 */
export const PLAYBOOK_SCENARIOS: PlaybookRecord[] = [
  {
    id: "sc-sales-emea",
    title: "Sales Engineer · EMEA",
    company: "Northreach Cloud",
    persona: "Sales Engineer",
    market: "EMEA",
    generatedDate: "Jul 04 2026",
    confidence: 92,
    risks: 4,
    citations: 14,
    exportStatus: "Exported",
    templateType: "Sales enablement playbook",
    selection: { picked: ["d1", "d3", "d5", "d2"], market: "EMEA", persona: "sales", custom: "" },
  },
  {
    id: "sc-compliance-health",
    title: "Compliance Officer · Healthcare",
    company: "Northreach Cloud",
    persona: "Compliance Officer",
    market: "Healthcare",
    generatedDate: "Jul 03 2026",
    confidence: 90,
    risks: 4,
    citations: 11,
    exportStatus: "Ready",
    templateType: "Compliance review playbook",
    selection: { picked: ["d5", "d1", "d3"], market: "Healthcare", persona: "compliance", custom: "" },
  },
  {
    id: "sc-support-finserv",
    title: "Support Agent · Financial Services",
    company: "Northreach Cloud",
    persona: "Support Agent",
    market: "Financial Services",
    generatedDate: "Jul 02 2026",
    confidence: 88,
    risks: 4,
    citations: 11,
    exportStatus: "Ready",
    templateType: "Support escalation playbook",
    selection: {
      picked: ["d6", "d3", "d4"],
      market: "Financial Services",
      persona: "support",
      custom: "",
    },
  },
  {
    id: "sc-architect-govcloud",
    title: "Solutions Architect · GovCloud",
    company: "Northreach Cloud",
    persona: "Solutions Architect",
    market: "Public Sector (GovCloud)",
    generatedDate: "Jul 01 2026",
    confidence: 93,
    risks: 4,
    citations: 11,
    exportStatus: "Exported",
    templateType: "Architecture validation playbook",
    selection: {
      picked: ["d4", "d2", "d5"],
      market: "Public Sector (GovCloud)",
      persona: "architect",
      custom: "",
    },
  },
  {
    id: "sc-field-manufacturing",
    title: "Field Technician · Manufacturing",
    company: "Northreach Cloud",
    persona: "Field Technician",
    market: "Manufacturing",
    generatedDate: "Jun 29 2026",
    confidence: 86,
    risks: 4,
    citations: 11,
    exportStatus: "Ready",
    templateType: "Field operations playbook",
    selection: {
      picked: ["d6", "d4", "d8"],
      market: "Manufacturing",
      persona: "custom",
      custom: "Field technician handling on-site equipment incidents",
    },
  },
];

export interface PlaybookTemplate {
  id: string;
  name: string;
  purpose: string;
  bestPersonas: string[];
  outputs: string[];
}

export const PLAYBOOK_TEMPLATES: PlaybookTemplate[] = [
  {
    id: "tpl-sales",
    name: "Sales enablement playbook",
    purpose: "Arm the deal team with defensible, cited answers for technical evaluation.",
    bestPersonas: ["Sales Engineer", "Solutions Architect"],
    outputs: ["SecQ answers", "Residency talk track", "POC success criteria"],
  },
  {
    id: "tpl-compliance",
    name: "Compliance review playbook",
    purpose: "Consolidate controls and surface gaps before an attestation or audit.",
    bestPersonas: ["Compliance Officer", "Operations Manager"],
    outputs: ["Controls matrix", "Residency gap log", "Attestation checklist"],
  },
  {
    id: "tpl-support",
    name: "Support escalation playbook",
    purpose: "Resolve and route incidents with SLA-accurate, source-backed replies.",
    bestPersonas: ["Support Agent", "Operations Manager"],
    outputs: ["Severity triage", "Customer-safe reply", "Escalation routing"],
  },
  {
    id: "tpl-architecture",
    name: "Architecture validation playbook",
    purpose: "Validate a reference design against residency, API, and failover constraints.",
    bestPersonas: ["Solutions Architect", "Operations Manager"],
    outputs: ["Reference architecture brief", "Residency topology", "API rate-limit map"],
  },
  {
    id: "tpl-field",
    name: "Field operations playbook",
    purpose: "Guide on-site work with incident, safety, and escalation procedures.",
    bestPersonas: ["Field Technician", "New Hire"],
    outputs: ["On-site checklist", "Incident report template", "Escalation contacts"],
  },
];
