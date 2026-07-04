import { DEMO_DOCS } from "./demoDocs";
import { HIGH_COMPLIANCE_MARKETS } from "./markets";
import { PERSONAS, buildCustomPersona, getPersonaById } from "./personas";
import type {
  Agent,
  Citation,
  DocId,
  Persona,
  Risk,
  Severity,
  WorkspaceSelection,
} from "./types";

export const DEFAULT_COMPANY = "Northreach Cloud";

export const AGENTS: Agent[] = [
  { id: "ingest", name: "Document Ingest", log: "Parsed documents → 1,284 passages", dur: "0.6s" },
  { id: "persona", name: "Persona Modeler", log: "Modeled role profile & priorities", dur: "0.4s" },
  { id: "retrieval", name: "Semantic Retrieval", log: "Indexed & ranked 1,284 passages", dur: "1.1s" },
  { id: "risk", name: "Risk Analyzer", log: "Flagged 4 compliance & operational risks", dur: "0.9s" },
  { id: "synth", name: "Brief Synthesizer", log: "Composed persona brief + workflow", dur: "0.7s" },
  { id: "cite", name: "Citation Binder", log: "Linked 26 citations to source spans", dur: "0.5s" },
  { id: "playbook", name: "Playbook Composer", log: "Assembled exportable playbook", dur: "0.3s" },
];

export const CITATIONS: Citation[] = [
  {
    tag: "SEC-4.2",
    doc: "Security & Compliance Whitepaper · §4.2",
    snippet: "All customer data is encrypted at rest using AES-256 and in transit via TLS 1.3.",
    why: "Anchors every security-posture claim in the playbook to a verifiable control statement.",
  },
  {
    tag: "RES-14",
    doc: "Data Residency & Sovereignty Policy · p.14",
    snippet:
      "Default control-plane metadata is processed in us-east-1 unless in-region processing is provisioned.",
    why: "Establishes the residency default that drives the top finding and highest-severity risk.",
  },
  {
    tag: "SLA-3",
    doc: "SLA & Uptime Commitment · §3",
    snippet: "Northreach commits to 99.99% monthly availability for multi-AZ Enterprise deployments.",
    why: "Sets the availability target the recommended failover design must satisfy.",
  },
  {
    tag: "INC-2.1",
    doc: "Incident Response Runbook · §2.1",
    snippet: "Severity 1 incidents page the primary on-call within 5 minutes via the escalation tool.",
    why: "Defines the escalation timing and surfaces the deprecated-tool risk.",
  },
  {
    tag: "DEP-11",
    doc: "Deployment & Migration Guide · p.11",
    snippet: "Blue-green deployments are supported across all commercial regions with automated rollback.",
    why: "Backs the deployment-topology and rollback recommendations.",
  },
  {
    tag: "API-RL",
    doc: "Platform API Reference · Rate Limits",
    snippet: "Default account limit is 2,000 requests per minute, burstable to 5,000.",
    why: "Bounds the rate limits any reference architecture must respect.",
  },
];

export const RISKS: Risk[] = [
  {
    sev: "HIGH",
    title: "Data residency gap for EMEA deployments",
    detail:
      "Default control-plane routing stores metadata in us-east-1; EMEA customers require in-region processing that is not enabled by default.",
    src: "RES-14 · Data Residency Policy p.14",
    ref: "RES-14",
    impact: "Blocks compliant EMEA onboarding; regulatory and deal exposure.",
    fix: "Enable in-region processing and change default routing before EMEA GA.",
    owner: "Platform Eng",
  },
  {
    sev: "MED",
    title: "SLA credit terms undefined for multi-region outages",
    detail:
      "The SLA specifies single-region remedies but is silent on simultaneous multi-region failure.",
    src: "SLA-3 · SLA Commitment §3",
    ref: "SLA-3",
    impact: "Ambiguous remedy in a correlated outage; credit disputes.",
    fix: "Define multi-region credit terms and legal-review the SLA addendum.",
    owner: "Legal / RevOps",
  },
  {
    sev: "MED",
    title: "Incident runbook references a deprecated on-call tool",
    detail:
      "Escalation section names PagerTree, which was retired last quarter — pages may not deliver.",
    src: "INC-2.1 · Incident Runbook §2.1",
    ref: "INC-2.1",
    impact: "Sev-1 pages may not deliver, extending time-to-restore.",
    fix: "Replace tool references and re-test the escalation path.",
    owner: "SRE On-call",
  },
  {
    sev: "LOW",
    title: "Pricing sheet omits egress overage tiers",
    detail:
      "No documented rate for data egress beyond the included allowance; finance review flagged this.",
    src: "Pricing & Packaging Sheet · tab 3",
    ref: "PRC-3",
    impact: "Unforecastable egress cost for customers and finance.",
    fix: "Publish egress overage tiers in the pricing sheet.",
    owner: "RevOps",
  },
];

export const SEVERITY_COLORS: Record<Severity, string> = {
  HIGH: "#c34635",
  MED: "#c1852b",
  LOW: "#8b8b91",
};

export const GENERATED_STAMP = "JUL 04 2026 · 14:22 UTC";

export interface RelevanceRow {
  id: DocId;
  short: string;
  pct: number;
}

export interface MetricCard {
  k: string;
  v: string;
  s: string;
  accent: boolean;
}

export interface DerivedReport {
  persona: Persona;
  company: string;
  market: string;
  marketLabel: string;
  personaLabel: string;
  personaTitle: string;
  workspaceName: string;
  genStamp: string;
  nDocs: number;
  nPassages: string;
  nCitations: number;
  execSummary: string;
  topFinding: string;
  metrics: MetricCard[];
  relevance: RelevanceRow[];
  confidence: number;
}

/** Resolve the effective persona from a selection. */
export function resolvePersona(
  selection: WorkspaceSelection,
  company: string,
): Persona {
  if (selection.persona === "custom" || (!selection.persona && selection.custom.trim())) {
    return buildCustomPersona(selection.custom, company, selection.market);
  }
  return getPersonaById(selection.persona) || PERSONAS[0];
}

export function relevanceRows(
  selection: WorkspaceSelection,
  persona: Persona,
): RelevanceRow[] {
  let src = DEMO_DOCS.filter((d) => selection.picked.includes(d.id));
  if (src.length === 0) src = DEMO_DOCS;
  const rows = src.map((d) => {
    const boost = persona.boosts[d.id] ?? 0;
    const pct = Math.min(98, d.base + boost);
    return { id: d.id, short: d.short, pct };
  });
  rows.sort((a, b) => b.pct - a.pct);
  return rows.slice(0, 6);
}

export function deriveReport(
  selection: WorkspaceSelection,
  company: string = DEFAULT_COMPANY,
): DerivedReport {
  const persona = resolvePersona(selection, company);
  const marketLabel = selection.market || "No market selected";
  const personaLabel = selection.persona
    ? persona.title
    : selection.custom.trim() || "No persona selected";

  const nDocs = selection.picked.length || 8;
  const nPassages = (nDocs * 163).toLocaleString();
  const nCitations = nDocs * 3 + 2;
  const mktName = selection.market || "the selected";

  const execSummary = `This playbook translates ${company}'s enterprise documentation into an operating brief for a ${persona.title} in the ${mktName} market. Evidentia analyzed ${nDocs} documents across ${nPassages} semantic passages, linked ${nCitations} source-traced citations, and flagged 4 risks — 1 high, 2 medium, 1 low. The most material finding is a data residency gap affecting EMEA deployments that should be remediated before attestation. The recommended workflow and next actions below are prioritized around: ${persona.priorities
    .join(", ")
    .toLowerCase()}.`;

  const topFinding = `The main blocker for the ${persona.title} is ${mktName} data residency alignment before buyer and security validation.`;

  const metrics: MetricCard[] = [
    { k: "Documents", v: String(nDocs), s: "of 8 available", accent: false },
    { k: "Passages indexed", v: nPassages, s: "semantic chunks", accent: false },
    { k: "Citations", v: String(nCitations), s: "source-traced", accent: false },
    { k: "Risks flagged", v: "4", s: "1 high · 2 med · 1 low", accent: false },
    { k: "Confidence", v: "92%", s: "grounding score", accent: true },
  ];

  return {
    persona,
    company,
    market: selection.market,
    marketLabel,
    personaLabel,
    personaTitle: persona.title,
    workspaceName: `${company} · ${marketLabel}`,
    genStamp: GENERATED_STAMP,
    nDocs,
    nPassages,
    nCitations,
    execSummary,
    topFinding,
    metrics,
    relevance: relevanceRows(selection, persona),
    confidence: 92,
  };
}

export interface InsightMetric {
  label: string;
  pct: number;
  sub: string;
}

export interface ComplianceInsight {
  label: string;
  level: number;
  color: string;
  sub: string;
}

export interface PlaybookInsights {
  coverage: InsightMetric;
  workflow: InsightMetric;
  persona: InsightMetric;
  compliance: ComplianceInsight;
  topEvidence: { tag: string; doc: string };
  topGap: string;
}

const CS_LEVELS = ["Low", "Moderate", "Elevated", "High"];

export function derivePlaybookInsights(
  selection: WorkspaceSelection,
  report: DerivedReport,
): PlaybookInsights {
  const covPct = 92;
  const workPct = 100;
  const rel = report.relevance;
  const personaPct = Math.min(
    98,
    Math.round(rel.reduce((a, d) => a + d.pct, 0) / (rel.length || 1)),
  );

  let cs = 1;
  if (HIGH_COMPLIANCE_MARKETS.includes(selection.market)) cs += 1;
  if (report.persona.id === "compliance") cs += 1;
  cs = Math.min(3, cs);
  const csColor =
    cs >= 3 ? SEVERITY_COLORS.HIGH : cs >= 2 ? SEVERITY_COLORS.MED : "var(--accent)";

  const top = rel[0];

  return {
    coverage: {
      label: `${covPct}%`,
      pct: covPct,
      sub: `${report.nCitations} sources across ${report.nDocs} documents`,
    },
    workflow: {
      label: `${workPct}%`,
      pct: workPct,
      sub: `7 of 7 agents complete · ${report.persona.steps.length} steps mapped`,
    },
    persona: {
      label: `${personaPct}%`,
      pct: personaPct,
      sub: `Corpus match to the ${report.persona.title} profile`,
    },
    compliance: {
      label: CS_LEVELS[cs],
      level: cs,
      color: csColor,
      sub: `${selection.market || "Selected"} market · ${report.persona.title} lens`,
    },
    topEvidence: { tag: "RES-14", doc: top ? top.short : "Residency Policy" },
    topGap: "Data residency gap for EMEA deployments",
  };
}

export interface SeverityCounts {
  HIGH: number;
  MED: number;
  LOW: number;
}

export function severityCounts(): SeverityCounts {
  const counts: SeverityCounts = { HIGH: 0, MED: 0, LOW: 0 };
  RISKS.forEach((r) => {
    counts[r.sev] += 1;
  });
  return counts;
}

/** Citation tags cycled through the workflow steps for evidence badges. */
export const WORKFLOW_CITE_TAGS = ["DEP-11", "RES-14", "SLA-3", "API-RL", "SEC-4.2", "INC-2.1"];
