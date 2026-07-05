import { HIGH_COMPLIANCE_MARKETS } from "@/lib/markets";
import type {
  Citation,
  DocumentMeta,
  DocumentRelevance,
  DocumentSection,
  ReportMetrics,
  RiskItem,
  WorkflowStep,
} from "@/lib/types";
import type { PersonaKey } from "./personaMapperAgent";

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

interface MetricsInput {
  documents: DocumentMeta[];
  sections: DocumentSection[];
  citations: Citation[];
  risks: RiskItem[];
  workflowSteps: WorkflowStep[];
  market: string;
  personaKey: PersonaKey;
  personaTitle: string;
}

function complianceSensitivity(market: string, personaKey: PersonaKey): ReportMetrics["complianceSensitivity"] {
  if (HIGH_COMPLIANCE_MARKETS.includes(market) || market === "EMEA") return "High";
  if (personaKey === "compliance") return "High";
  return "Moderate";
}

function documentRelevance(documents: DocumentMeta[], personaTitle: string): DocumentRelevance[] {
  return documents
    .map((d, i) => {
      const match = d.usedByPersonas.includes(personaTitle);
      const score = clamp(72 + (match ? 20 : 6) - i * 2, 60, 98);
      return { document: d.short, score };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 6);
}

/**
 * Metrics Agent.
 * Produces deterministic, input-driven report metrics. More selected documents
 * generally raise confidence and citation coverage.
 */
export function metricsAgent(input: MetricsInput): ReportMetrics {
  const documentsAnalyzed = input.documents.length;
  const passagesIndexed = input.sections.length * 41;
  const coverageRatio = documentsAnalyzed / 8;

  const confidence = clamp(Math.round(82 + coverageRatio * 14), 82, 96);
  const personaRelevanceScore = clamp(76 + documentsAnalyzed * 2 + 4, 70, 95);
  const workflowCompleteness = clamp(80 + input.workflowSteps.length * 4, 80, 100);
  const citationCoverage = clamp(70 + documentsAnalyzed * 3, 70, 95);

  return {
    documentsAnalyzed,
    passagesIndexed,
    citationsUsed: input.citations.length,
    risksFlagged: input.risks.length,
    confidence,
    personaRelevanceScore,
    workflowCompleteness,
    citationCoverage,
    complianceSensitivity: complianceSensitivity(input.market, input.personaKey),
    documentRelevance: documentRelevance(input.documents, input.personaTitle),
  };
}
