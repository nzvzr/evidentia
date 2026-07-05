import { HIGH_COMPLIANCE_MARKETS } from "@/lib/markets";
import type { DocumentSection, RiskItem } from "@/lib/types";
import type { PersonaKey } from "./personaMapperAgent";

interface RiskTemplate {
  key: string;
  severity: RiskItem["severity"];
  title: string;
  description: string;
  businessImpact: string;
  recommendedFix: string;
  owner: string;
  /** citation prefix this risk is evidenced by */
  prefix: string;
  fallbackCode: string;
  /** personas that especially care about this risk */
  personas: PersonaKey[];
}

const RISK_POOL: RiskTemplate[] = [
  {
    key: "residency",
    severity: "High",
    title: "Data residency gap for EMEA deployments",
    description:
      "Default control-plane routing stores metadata in us-east-1; regulated markets require in-region processing that is not enabled by default.",
    businessImpact: "Blocks compliant onboarding; regulatory and deal exposure.",
    recommendedFix: "Enable in-region processing and change default routing before regional GA.",
    owner: "Platform Eng",
    prefix: "RES",
    fallbackCode: "RES-14",
    personas: ["compliance", "architect", "sales"],
  },
  {
    key: "sla-multiregion",
    severity: "Medium",
    title: "SLA credit terms undefined for multi-region outages",
    description:
      "The SLA specifies single-region remedies but is silent on simultaneous multi-region failure.",
    businessImpact: "Ambiguous remedy in a correlated outage; credit disputes.",
    recommendedFix: "Define multi-region credit terms and legal-review the SLA addendum.",
    owner: "Legal / RevOps",
    prefix: "SLA",
    fallbackCode: "SLA-3",
    personas: ["ops", "support", "sales", "compliance"],
  },
  {
    key: "incident-tool",
    severity: "Medium",
    title: "Incident runbook references a deprecated on-call tool",
    description:
      "The escalation section names PagerTree, which was retired — pages may not deliver.",
    businessImpact: "Sev-1 pages may not deliver, extending time-to-restore.",
    recommendedFix: "Replace tool references and re-test the escalation path.",
    owner: "SRE On-call",
    prefix: "INC",
    fallbackCode: "INC-2.1",
    personas: ["ops", "support", "field", "newhire"],
  },
  {
    key: "pricing-egress",
    severity: "Low",
    title: "Pricing sheet omits egress overage tiers",
    description:
      "No documented rate for data egress beyond the included allowance; finance review flagged this.",
    businessImpact: "Unforecastable egress cost for customers and finance.",
    recommendedFix: "Publish egress overage tiers in the pricing sheet.",
    owner: "RevOps",
    prefix: "PRC",
    fallbackCode: "PRC-3",
    personas: ["ops", "sales"],
  },
  {
    key: "unsupported-claim",
    severity: "High",
    title: "Unsupported compliance claim in customer-facing material",
    description:
      "A security claim in buyer-facing material lacks a linked source control and may not be defensible.",
    businessImpact: "Regulatory and reputational risk if the claim is challenged in review.",
    recommendedFix: "Attach a source citation to each claim or remove unsupported statements.",
    owner: "Compliance",
    prefix: "SEC",
    fallbackCode: "SEC-4.2",
    personas: ["compliance", "sales"],
  },
  {
    key: "api-limits",
    severity: "Medium",
    title: "API rate limits missing from deployment design",
    description:
      "The reference design does not account for the documented default rate limit, risking throttling under load.",
    businessImpact: "Throttling in production can degrade customer-facing performance.",
    recommendedFix: "Incorporate the documented rate limits and backoff into the design.",
    owner: "Platform Eng",
    prefix: "API",
    fallbackCode: "API-RL",
    personas: ["architect", "ops"],
  },
  {
    key: "untested-rollback",
    severity: "Medium",
    title: "Rollback not verified before migration window",
    description:
      "The deployment guide requires tested rollback, but the migration plan has no rollback validation step.",
    businessImpact: "An untested rollback can turn a routine change into an outage.",
    recommendedFix: "Add a rollback rehearsal to the migration checklist.",
    owner: "SRE On-call",
    prefix: "DEP",
    fallbackCode: "DEP-11",
    personas: ["ops", "architect", "field"],
  },
];

function evidenceFor(sections: DocumentSection[], prefix: string, fallback: string): string {
  const match = sections.find((s) => s.citationId.startsWith(prefix));
  return match ? match.citationId : fallback;
}

/**
 * Risk Agent.
 * Selects 3–5 persona/market/document-aware risks, guaranteeing at least one
 * High and one Medium, and binds each to a source citation.
 */
export function riskAgent(
  personaKey: PersonaKey,
  market: string,
  sections: DocumentSection[],
): RiskItem[] {
  const availablePrefixes = new Set(sections.map((s) => s.citationId.split("-")[0]));
  const highCompliance = HIGH_COMPLIANCE_MARKETS.includes(market) || market === "EMEA";

  // Score each risk: evidence availability + persona relevance.
  const scored = RISK_POOL.map((r) => {
    let score = 0;
    if (availablePrefixes.has(r.prefix)) score += 3;
    if (r.personas.includes(personaKey)) score += 2;
    if (r.key === "residency" && highCompliance) score += 2;
    return { r, score };
  })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score);

  let chosen = scored.slice(0, 5).map((s) => s.r);
  if (chosen.length < 3) {
    // Top up from the pool to guarantee a minimum of 3.
    for (const r of RISK_POOL) {
      if (chosen.length >= 3) break;
      if (!chosen.includes(r)) chosen.push(r);
    }
  }

  const risks: RiskItem[] = chosen.map((r) => {
    const severity =
      r.key === "residency" && highCompliance ? "High" : r.severity;
    return {
      severity,
      title: r.title,
      description: r.description,
      businessImpact: r.businessImpact,
      evidenceCode: evidenceFor(sections, r.prefix, r.fallbackCode),
      recommendedFix: r.recommendedFix,
      owner: r.owner,
    };
  });

  // Guarantee at least one High and one Medium.
  if (!risks.some((r) => r.severity === "High") && risks.length > 0) {
    risks[0].severity = "High";
  }
  if (!risks.some((r) => r.severity === "Medium") && risks.length > 1) {
    risks[risks.length - 1].severity = "Medium";
  }

  return risks.slice(0, 5);
}
