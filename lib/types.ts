export interface SuggestedAction {
  title: string;
  detail: string;
}

export interface Persona {
  id: string;
  title: string;
  focus: string;
}

export interface WorkspaceSelection {
  /** Real tenant document ids selected for the next generation. */
  picked: string[];
  market: string;
  persona: string;
  custom: string;
}

export interface AppSettings {
  workspaceName: string;
  defaultMarket: string;
  defaultPersona: string;
  exportFormat: "US Letter" | "A4";
  theme: "System" | "Light" | "Dark";
}

/** The authenticated user, as reported by the server. Never holds a token. */
export interface SessionUser {
  id: string;
  email: string;
  name: string | null;
  emailVerified: boolean;
}

export type CompanyRole = "owner" | "admin" | "member";

/** A company the current user belongs to, and their role in it. */
export interface Membership {
  id: string;
  name: string;
  slug: string;
  role: CompanyRole;
}

/** Input to the generation pipeline / API route. */
export interface AgentInput {
  market: string;
  /** predefined persona title, e.g. "Support Agent" */
  persona: string;
  /** free-text custom role; takes priority when non-empty */
  customPersona?: string;
  /** Authenticated tenant document ids. */
  selectedDocumentIds: string[];
}

export interface AgentStep {
  agent: string;
  status: "complete" | "running" | "queued";
  detail: string;
  duration: string;
}

export interface PersonaBrief {
  title: string;
  description: string;
  goals: string[];
  priorities: string[];
  relevantTopics: string[];
  riskFocus: string[];
  outputStyle: string;
  /** true when derived from a free-text custom role */
  isCustom: boolean;
}

export interface WorkflowStep {
  step: number;
  title: string;
  description: string;
  whyItMatters: string;
  expectedOutput: string;
  evidenceCode: string;
}

export interface RiskItem {
  severity: "High" | "Medium" | "Low";
  title: string;
  description: string;
  businessImpact: string;
  evidenceCode: string;
  recommendedFix: string;
  owner: string;
}

export interface Citation {
  id: string;
  source: string;
  section: string;
  excerpt: string;
  whyItMatters: string;
}

export interface DocumentRelevance {
  document: string;
  score: number;
}

export interface ReportMetrics {
  documentsAnalyzed: number;
  passagesIndexed: number;
  citationsUsed: number;
  risksFlagged: number;
  confidence: number;
  personaRelevanceScore: number;
  workflowCompleteness: number;
  citationCoverage: number;
  complianceSensitivity: "Low" | "Moderate" | "High";
  documentRelevance: DocumentRelevance[];
}

export interface EvidentiaReport {
  id: string;
  company: string;
  market: string;
  persona: string;
  customPersona?: string;
  category: string;
  generatedAt: string;
  confidence: number;
  summary: string;
  topFinding: string;
  agentSteps: AgentStep[];
  personaBrief: PersonaBrief;
  workflowSteps: WorkflowStep[];
  risks: RiskItem[];
  citations: Citation[];
  metrics: ReportMetrics;
  suggestedActions: SuggestedAction[];
  /** how the report was produced */
  generationMode?: "deterministic" | "llm-summary" | "llm-assisted";
  /** LLM provider used, or "none" for deterministic */
  llmProvider?: "openai" | "anthropic" | "none";
  /** LLM model used, when llm-assisted */
  llmModel?: string;
}

/** Authenticated audit projection. Kept out of EvidentiaReport compatibility JSON. */
export interface ReportEvidenceSource {
  documentId: string;
  documentVersionId: string;
  documentTitle: string;
  originalFilename?: string | null;
  sectionOrdinal: number;
  headingPath: string[];
  sectionTitle: string;
  anchorId: string;
  citationId: string;
  sectionSignature: string;
  retrievalRank: number;
  retrievalScore: number;
  selectedForPrompt: boolean;
  citedInFinal: boolean;
  excerpt: string;
}

export interface ReportSourceAudit {
  corpusMode: "demo" | "tenant";
  corpusSnapshotDigest?: string | null;
  retrievalEngineVersion?: string | null;
  orchestratorVersion?: string | null;
  executionMode?: string | null;
  llmProvider?: string | null;
  llmModel?: string | null;
  sourceVersionCount: number;
  evidenceSectionCount: number;
  generationStatus: string;
  sourceVersions: Array<{
    documentId: string;
    documentVersionId: string;
    versionNo: number;
    manifestSha256: string;
    finalizationTargetDigest: string;
    position: number;
  }>;
  evidenceBindings: ReportEvidenceSource[];
}

/** Tenant-scoped M5a claim audit. Kept outside EvidentiaReport compatibility JSON. */
export interface ReportClaimAudit {
  claimEngineEnabled: boolean;
  candidates: Array<{
    candidateId: string;
    appearedInFinal: boolean;
    decision: null | {
      status: "accepted" | "rejected" | "insufficient_evidence" | string;
    };
  }>;
}

/** Tenant-private feedback projection. Kept outside EvidentiaReport. */
export type ReportFeedbackVerdict = "correct_useful" | "partially_correct" | "incorrect";
export type ItemFeedbackVerdict = "accepted" | "rejected" | "edited" | "insufficient_evidence";
export type CitationFeedbackVerdict = "correct" | "irrelevant" | "incorrect_source";

export interface ReportFeedbackSnapshot {
  report: null | {
    verdict: ReportFeedbackVerdict;
    reasonCode?: string | null;
    privateText?: string | null;
  };
  items: Array<{
    itemPath: string;
    itemType: "workflow_step" | "risk" | "citation" | "suggested_action";
    verdict: ItemFeedbackVerdict;
    reasonCode?: string | null;
    editedText?: string | null;
  }>;
  citations: Array<{
    itemPath: string;
    citationId: string;
    verdict: CitationFeedbackVerdict;
    correctedAnchorId?: string | null;
  }>;
}
