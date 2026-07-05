import type { AgentInput } from "@/lib/types";

export interface DemoScenario {
  id: string;
  title: string;
  /** filter category for the reports library */
  category: string;
  input: AgentInput;
}

/** Five deterministic demo scenarios used to seed the libraries. */
export const SCENARIOS: DemoScenario[] = [
  {
    id: "support-emea",
    title: "Support Agent · EMEA",
    category: "Support",
    input: {
      id: "support-emea",
      market: "EMEA",
      persona: "Support Agent",
      customPersona: "",
      selectedDocumentIds: [
        "incident-response-runbook",
        "sla-uptime-commitment",
        "deployment-migration-guide",
      ],
    },
  },
  {
    id: "sales-finserv",
    title: "Sales Engineer · Financial Services",
    category: "Sales",
    input: {
      id: "sales-finserv",
      market: "Financial Services",
      persona: "Sales Engineer",
      customPersona: "",
      selectedDocumentIds: [
        "security-compliance-whitepaper",
        "sla-uptime-commitment",
        "data-residency-sovereignty-policy",
        "platform-api-reference",
      ],
    },
  },
  {
    id: "compliance-healthcare",
    title: "Compliance Officer · Healthcare",
    category: "Compliance",
    input: {
      id: "compliance-healthcare",
      market: "Healthcare",
      persona: "Compliance Officer",
      customPersona: "",
      selectedDocumentIds: [
        "data-residency-sovereignty-policy",
        "security-compliance-whitepaper",
        "sla-uptime-commitment",
      ],
    },
  },
  {
    id: "architect-govcloud",
    title: "Solutions Architect · GovCloud",
    category: "Architecture",
    input: {
      id: "architect-govcloud",
      market: "Public Sector (GovCloud)",
      persona: "Solutions Architect",
      customPersona: "",
      selectedDocumentIds: [
        "deployment-migration-guide",
        "platform-api-reference",
        "data-residency-sovereignty-policy",
      ],
    },
  },
  {
    id: "field-manufacturing",
    title: "Field Technician · Manufacturing",
    category: "Operations",
    input: {
      id: "field-manufacturing",
      market: "Manufacturing",
      persona: "",
      customPersona: "Field technician handling on-site equipment incidents",
      selectedDocumentIds: [
        "incident-response-runbook",
        "deployment-migration-guide",
        "customer-onboarding-handbook",
      ],
    },
  },
];

export function getScenario(id: string): DemoScenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
