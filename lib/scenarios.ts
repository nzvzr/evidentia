import type { PlaybookRecord } from "./types";

/**
 * Deterministic demo reports shown in the Reports and Playbooks libraries.
 * Each carries a workspace selection so opening a report/playbook can
 * re-hydrate the report and print pages without a database.
 */
export const DEMO_REPORTS: PlaybookRecord[] = [
  {
    id: "support-emea",
    title: "Support Agent · EMEA",
    company: "Northreach Cloud",
    persona: "Support Agent",
    market: "EMEA",
    generatedDate: "Jul 04 2026",
    confidence: 89,
    risks: 4,
    citations: 11,
    documents: 3,
    exportStatus: "Ready",
    templateType: "Support escalation playbook",
    category: "Support",
    selection: { picked: ["d6", "d3", "d4"], market: "EMEA", persona: "support", custom: "" },
  },
  {
    id: "sales-finserv",
    title: "Sales Engineer · Financial Services",
    company: "Northreach Cloud",
    persona: "Sales Engineer",
    market: "Financial Services",
    generatedDate: "Jul 03 2026",
    confidence: 92,
    risks: 4,
    citations: 14,
    documents: 4,
    exportStatus: "Exported",
    templateType: "Sales enablement playbook",
    category: "Sales",
    selection: {
      picked: ["d1", "d3", "d5", "d2"],
      market: "Financial Services",
      persona: "sales",
      custom: "",
    },
  },
  {
    id: "compliance-healthcare",
    title: "Compliance Officer · Healthcare",
    company: "Northreach Cloud",
    persona: "Compliance Officer",
    market: "Healthcare",
    generatedDate: "Jul 02 2026",
    confidence: 90,
    risks: 4,
    citations: 11,
    documents: 3,
    exportStatus: "Ready",
    templateType: "Compliance review playbook",
    category: "Compliance",
    selection: {
      picked: ["d5", "d1", "d3"],
      market: "Healthcare",
      persona: "compliance",
      custom: "",
    },
  },
  {
    id: "architect-govcloud",
    title: "Solutions Architect · GovCloud",
    company: "Northreach Cloud",
    persona: "Solutions Architect",
    market: "Public Sector (GovCloud)",
    generatedDate: "Jul 01 2026",
    confidence: 93,
    risks: 4,
    citations: 11,
    documents: 3,
    exportStatus: "Exported",
    templateType: "Architecture validation playbook",
    category: "Architecture",
    selection: {
      picked: ["d4", "d2", "d5"],
      market: "Public Sector (GovCloud)",
      persona: "architect",
      custom: "",
    },
  },
  {
    id: "field-manufacturing",
    title: "Field Technician · Manufacturing",
    company: "Northreach Cloud",
    persona: "Field Technician",
    market: "Manufacturing",
    generatedDate: "Jun 29 2026",
    confidence: 86,
    risks: 4,
    citations: 11,
    documents: 3,
    exportStatus: "Ready",
    templateType: "Field operations playbook",
    category: "Operations",
    selection: {
      picked: ["d6", "d4", "d8"],
      market: "Manufacturing",
      persona: "custom",
      custom: "Field technician handling on-site equipment incidents",
    },
  },
];

/** Back-compat alias. */
export const PLAYBOOK_SCENARIOS = DEMO_REPORTS;

export function getReportById(id: string): PlaybookRecord | undefined {
  return DEMO_REPORTS.find((r) => r.id === id);
}

export const REPORT_CATEGORIES = [
  "All",
  "Support",
  "Sales",
  "Compliance",
  "Operations",
  "Architecture",
] as const;

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
