/**
 * UI-only constants for the report/playbook libraries. Demo report data now
 * comes from the multi-agent pipeline via data/scenarios.ts + data/demoReports.ts.
 */

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
