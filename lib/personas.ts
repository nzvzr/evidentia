import type { Persona } from "./types";

export const PERSONAS: Persona[] = [
  {
    id: "support",
    title: "Support Agent",
    focus: "Resolve incidents fast with cited answers",
    brief:
      "As a Support Agent, your day is driven by ticket volume and time-to-resolution. This brief surfaces the deployment, incident, and SLA knowledge you need to answer confidently — with every claim traced to source documentation, so no customer-facing reply is a guess.",
    priorities: ["Time to resolution", "SLA accuracy", "Escalation clarity"],
    steps: [
      {
        t: "Triage against the severity matrix",
        d: "Classify the ticket using the Incident Response Runbook severity definitions.",
        output: "A severity classification with the matching runbook clause.",
      },
      {
        t: "Confirm SLA entitlements",
        d: "Verify the customer's region and tier commitments before promising a remediation window.",
        output: "A confirmed remediation window tied to the SLA tier.",
      },
      {
        t: "Pull verified remediation steps",
        d: "Retrieve the documented fix and attach the source passage to your reply.",
        output: "A cited, customer-safe remediation reply.",
      },
      {
        t: "Escalate P1/P2 correctly",
        d: "Route severe incidents through the current on-call path — not the deprecated tool.",
        output: "A correctly routed escalation with the live on-call owner.",
      },
    ],
    actions: [
      {
        title: "Triage against severity matrix",
        detail: "Classify the ticket using the Incident Response Runbook definitions.",
      },
      {
        title: "Draft customer-safe reply",
        detail: "Generate a cited response template for recurring infrastructure tickets.",
      },
      {
        title: "Escalate privacy or billing cases",
        detail: "Route sensitive cases through the correct current on-call path.",
      },
    ],
    boosts: { d6: 30, d3: 25, d4: 15 },
  },
  {
    id: "sales",
    title: "Sales Engineer",
    focus: "Win technical trust in the deal cycle",
    brief:
      "As a Sales Engineer, you translate platform depth into buyer confidence. This brief arms you with defensible security, SLA, and architecture talking points for the selected market — each backed by a citation you can drop straight into a security questionnaire.",
    priorities: ["Objection handling", "Security posture", "Competitive proof"],
    steps: [
      {
        t: "Map requirements to capabilities",
        d: "Align the buyer's stated needs to documented platform features.",
        output: "A requirements-to-capabilities matrix.",
      },
      {
        t: "Prepare SecQ responses",
        d: "Draft security-questionnaire answers with inline citations.",
        output: "A set of cited security-questionnaire answers.",
      },
      {
        t: "Address data residency",
        d: "Confirm the residency posture for the target market before the technical review.",
        output: "A residency talk track for the selected market.",
      },
      {
        t: "Assemble a POC architecture",
        d: "Produce a reference architecture the customer's team can validate.",
        output: "A POC reference architecture with success criteria.",
      },
    ],
    actions: [
      {
        title: "Generate SecQ answers",
        detail: "Cited responses to the 20 most common security-questionnaire items.",
      },
      {
        title: "Build a residency talk track",
        detail: "Two-minute narrative on in-region processing for this market.",
      },
      {
        title: "Draft POC success criteria",
        detail: "Measurable exit criteria mapped to platform capabilities.",
      },
    ],
    boosts: { d1: 28, d3: 20, d5: 18 },
  },
  {
    id: "compliance",
    title: "Compliance Officer",
    focus: "Ensure regulatory obligations are met",
    brief:
      "As a Compliance Officer, your lens is risk and evidence. This brief consolidates data residency, encryption, and audit controls for the selected market, and elevates the gaps that must be remediated before attestation.",
    priorities: ["Data residency", "Audit readiness", "Control coverage"],
    steps: [
      {
        t: "Review residency posture",
        d: "Assess where control-plane and customer data are processed for this market.",
        output: "A residency posture summary with any deviations.",
      },
      {
        t: "Validate encryption & access",
        d: "Check controls against the stated policy and note deviations.",
        output: "A control-validation checklist with findings.",
      },
      {
        t: "Reconcile SLA credit terms",
        d: "Confirm remedy definitions for multi-region outage scenarios.",
        output: "A reconciled SLA credit-terms note.",
      },
      {
        t: "Log gaps for remediation",
        d: "File each finding into the remediation tracker with an owner.",
        output: "A remediation log with owners and citations.",
      },
    ],
    actions: [
      {
        title: "Open the residency gap",
        detail: "Escalate the EMEA metadata-routing finding to engineering.",
      },
      {
        title: "Export a controls matrix",
        detail: "Map documented controls to SOC 2 / ISO 27001 criteria.",
      },
      {
        title: "Schedule an attestation review",
        detail: "Book the pre-audit walkthrough with evidence attached.",
      },
    ],
    boosts: { d5: 32, d1: 26, d3: 16 },
  },
  {
    id: "ops",
    title: "Operations Manager",
    focus: "Keep the platform reliable and on-budget",
    brief:
      "As an Operations Manager, you own uptime, cost, and process. This brief connects the SLA commitments, incident runbook, and pricing structure so you can spot operational and financial exposure before it reaches a customer or a finance review.",
    priorities: ["Uptime", "Cost control", "Process integrity"],
    steps: [
      {
        t: "Review SLA commitments",
        d: "Check availability targets and multi-region outage terms.",
        output: "An SLA commitment summary with exposure notes.",
      },
      {
        t: "Audit the incident runbook",
        d: "Identify stale references and tooling gaps in the on-call process.",
        output: "A runbook audit with remediation items.",
      },
      {
        t: "Model cost exposure",
        d: "Estimate egress and overage cost under expected load.",
        output: "A cost-exposure model across regions.",
      },
      {
        t: "Align on-call staffing",
        d: "Map staffing to the severity matrix response windows.",
        output: "An on-call staffing plan aligned to SLAs.",
      },
    ],
    actions: [
      {
        title: "Model egress costs",
        detail: "Project overage exposure across the top three deployment regions.",
      },
      {
        title: "Refresh the runbook",
        detail: "Replace deprecated tooling references and re-verify escalation paths.",
      },
      {
        title: "Set uptime alert thresholds",
        detail: "Define alerting aligned to the 99.99% SLA commitment.",
      },
    ],
    boosts: { d3: 28, d6: 24, d7: 22 },
  },
  {
    id: "architect",
    title: "Solutions Architect",
    focus: "Design deployments that fit constraints",
    brief:
      "As a Solutions Architect, you turn requirements into resilient designs. This brief aligns the deployment guide, API surface, and residency policy so your reference architecture holds up to security review in the selected market.",
    priorities: ["Reference architecture", "Data residency", "API coverage"],
    steps: [
      {
        t: "Select deployment topology",
        d: "Choose a topology that satisfies the market's residency rules.",
        output: "A chosen topology with residency justification.",
      },
      {
        t: "Map required API surfaces",
        d: "Identify endpoints and rate limits the design depends on.",
        output: "An API-surface map with rate-limit notes.",
      },
      {
        t: "Design multi-region failover",
        d: "Meet the SLA with automated failover and rollback.",
        output: "A failover design meeting the SLA target.",
      },
      {
        t: "Document assumptions",
        d: "Record every design decision with a supporting citation.",
        output: "A cited assumptions log for review.",
      },
    ],
    actions: [
      {
        title: "Generate a reference architecture brief",
        detail: "Component list and data-flow notes for the architecture diagram.",
      },
      {
        title: "Validate residency topology",
        detail: "Confirm in-region processing for the selected market.",
      },
      {
        title: "List API rate limits",
        detail: "Extract the limits the reference design must respect.",
      },
    ],
    boosts: { d4: 30, d2: 26, d5: 18 },
  },
  {
    id: "newhire",
    title: "New Hire",
    focus: "Ramp quickly on platform and process",
    brief:
      "As a New Hire, you need the shortest path to competence. This brief sequences the onboarding handbook, deployment basics, and incident process into a first-two-weeks learning path — with sources so you can go deeper wherever you need to.",
    priorities: ["Fast ramp", "Process fluency", "Knowing where to look"],
    steps: [
      {
        t: "Complete onboarding essentials",
        d: "Work through the core sections of the onboarding handbook.",
        output: "A completed onboarding-essentials checklist.",
      },
      {
        t: "Learn deployment fundamentals",
        d: "Understand how the platform is deployed and rolled back.",
        output: "Notes on deployment and rollback fundamentals.",
      },
      {
        t: "Study the severity matrix",
        d: "Know how incidents are classified and escalated.",
        output: "A personal severity-matrix cheat sheet.",
      },
      {
        t: "Bookmark the citation library",
        d: "Keep the source index handy for day-to-day questions.",
        output: "A saved index of key source citations.",
      },
    ],
    actions: [
      {
        title: "Generate a 2-week ramp plan",
        detail: "A sequenced learning path with daily objectives.",
      },
      {
        title: "Take the platform basics quiz",
        detail: "Check comprehension of core deployment concepts.",
      },
      {
        title: "Meet your escalation contacts",
        detail: "Identify the on-call owners for your first rotations.",
      },
    ],
    boosts: { d8: 40, d4: 18, d6: 14 },
  },
];

export function buildCustomPersona(
  custom: string,
  company: string,
  market: string,
): Persona {
  const title = custom.trim() || "Custom Role";
  const mkt = market || "selected";
  return {
    id: "custom",
    title,
    focus: "Modeled from your description",
    brief: `Evidentia modeled a role profile from your description and mapped ${company}'s documentation to it. The brief below prioritizes the passages, risks, and actions most relevant to "${title}" in the ${mkt} market.`,
    priorities: ["Relevance", "Evidence", "Next action"],
    steps: [
      {
        t: "Model the role profile",
        d: "Infer priorities and information needs from the described responsibilities.",
        output: "A modeled role profile with priorities.",
      },
      {
        t: "Retrieve relevant evidence",
        d: "Rank passages across the corpus against the modeled profile.",
        output: "A ranked evidence set for the role.",
      },
      {
        t: "Assess role-specific risk",
        d: "Surface gaps and warnings that matter for this role.",
        output: "A shortlist of role-specific risks.",
      },
      {
        t: "Compose the cited brief",
        d: "Assemble the workflow and actions with linked sources.",
        output: "A cited playbook tailored to the role.",
      },
    ],
    actions: [
      {
        title: "Refine the role model",
        detail: "Add detail to sharpen the persona and re-run.",
      },
      {
        title: "Export the cited brief",
        detail: "Download the tailored playbook as a PDF.",
      },
      {
        title: "Share with a teammate",
        detail: "Send the report to a colleague in the same role.",
      },
    ],
    boosts: { d5: 12, d2: 10, d1: 8 },
  };
}

export function getPersonaById(id: string): Persona | undefined {
  return PERSONAS.find((p) => p.id === id);
}
