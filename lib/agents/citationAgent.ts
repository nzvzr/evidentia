import type { Citation, DocumentSection, RiskItem, WorkflowStep } from "@/lib/types";

const WHY_BY_ID: Record<string, string> = {
  "SEC-4.2": "Anchors every security-posture claim to a verifiable control statement.",
  "RES-14": "Establishes the residency default that drives the top finding and highest-severity risk.",
  "SLA-3": "Sets the availability target the recommended failover design must satisfy.",
  "INC-2.1": "Defines escalation timing and surfaces the deprecated-tool risk.",
  "DEP-11": "Backs the deployment-topology and rollback recommendations.",
  "API-RL": "Bounds the rate limits any reference architecture must respect.",
  "PRC-3": "Documents the pricing gap behind the egress-overage risk.",
};

function whyItMatters(section: DocumentSection): string {
  return (
    WHY_BY_ID[section.citationId] ??
    `Backs the ${section.sectionTitle.toLowerCase()} guidance drawn from the ${section.source}.`
  );
}

/**
 * Citation Agent / Binder.
 * Connects workflow steps and risks to their source sections, then rounds out
 * the appendix with the most relevant remaining sections.
 */
export function citationAgent(
  sections: DocumentSection[],
  workflowSteps: WorkflowStep[],
  risks: RiskItem[],
): Citation[] {
  const byId = new Map<string, DocumentSection>();
  sections.forEach((s) => {
    if (!byId.has(s.citationId)) byId.set(s.citationId, s);
  });

  const referenced: string[] = [];
  const push = (id: string) => {
    if (id && byId.has(id) && !referenced.includes(id)) referenced.push(id);
  };
  workflowSteps.forEach((w) => push(w.evidenceCode));
  risks.forEach((r) => push(r.evidenceCode));

  // Round out with additional sections so the appendix is substantive.
  for (const s of sections) {
    if (referenced.length >= Math.min(8, Math.max(6, sections.length))) break;
    push(s.citationId);
  }

  return referenced.map((id) => {
    const s = byId.get(id) as DocumentSection;
    return {
      id: s.citationId,
      source: `${s.source} · ${s.sectionTitle}`,
      section: s.sectionTitle,
      excerpt: s.excerpt,
      whyItMatters: whyItMatters(s),
    };
  });
}
