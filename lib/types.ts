export type DocId =
  | "d1"
  | "d2"
  | "d3"
  | "d4"
  | "d5"
  | "d6"
  | "d7"
  | "d8";

export interface DemoDoc {
  id: DocId;
  name: string;
  short: string;
  meta: string;
  kind: string;
  description: string;
  /** base relevance score before persona boosts */
  base: number;
  /** original filename */
  filename: string;
  /** functional category, e.g. "Security", "Compliance" */
  category: string;
  /** human page/endpoint/tab count, e.g. "48 pages" */
  pages: string;
  /** last-updated label */
  updatedAt: string;
  /** index status */
  status: string;
  /** citation anchor IDs contributed by this doc */
  citationIds: string[];
  /** persona titles that most rely on this doc */
  usedByPersonas: string[];
  /** topics covered */
  topics: string[];
  /** a representative excerpt */
  sampleExcerpt: string;
  /** short relevance tags */
  relevanceTags: string[];
}

export interface UploadedDoc {
  id: string;
  name: string;
  filename: string;
  kind: string;
  category: string;
  sizeLabel: string;
  uploadedAt: string;
  excerpt: string;
  status: string;
}

export interface PlaybookRecord {
  id: string;
  title: string;
  company: string;
  persona: string;
  market: string;
  generatedDate: string;
  confidence: number;
  risks: number;
  citations: number;
  documents: number;
  exportStatus: string;
  templateType: string;
  /** filter category: Support | Sales | Compliance | Operations | Architecture */
  category: string;
  /** workspace selection to re-hydrate report/playbook when opened */
  selection: WorkspaceSelection;
}

export type Severity = "HIGH" | "MED" | "LOW";

export interface Risk {
  sev: Severity;
  title: string;
  detail: string;
  /** short human source label */
  src: string;
  /** citation ref id */
  ref: string;
  impact: string;
  fix: string;
  owner: string;
}

/** Legacy citation shape used by the static demoReport helpers. */
export interface DemoCitation {
  tag: string;
  doc: string;
  snippet: string;
  why: string;
}

export interface Agent {
  id: string;
  name: string;
  log: string;
  dur: string;
}

/** Legacy persona workflow step used by the static persona catalogue. */
export interface PersonaStep {
  /** short imperative title */
  t: string;
  /** detail / why it matters */
  d: string;
  /** expected output on the playbook */
  output: string;
}

export interface SuggestedAction {
  title: string;
  detail: string;
}

export interface Persona {
  id: string;
  title: string;
  focus: string;
  brief: string;
  priorities: string[];
  steps: PersonaStep[];
  actions: SuggestedAction[];
  /** per-doc relevance boost */
  boosts: Partial<Record<DocId, number>>;
}

export interface WorkspaceSelection {
  picked: DocId[];
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

export interface MockUser {
  name: string;
  email: string;
  company: string;
}

/* ============================================================
   MULTI-AGENT PIPELINE TYPES
   Produced by lib/agents/* and consumed by the report + print
   pages. These are self-contained and market/persona-aware.
   ============================================================ */

/** Input to the generation pipeline / API route. */
export interface AgentInput {
  market: string;
  /** predefined persona title, e.g. "Support Agent" */
  persona: string;
  /** free-text custom role; takes priority when non-empty */
  customPersona?: string;
  /** document slug ids, e.g. "security-compliance-whitepaper" */
  selectedDocumentIds: string[];
  /** optional explicit report id (used for demo scenarios) */
  id?: string;
}

/** Static metadata for a demo document. */
export interface DocumentMeta {
  id: string;
  title: string;
  short: string;
  type: string;
  category: string;
  /** e.g. "48 pages", "320 endpoints", "5 tabs" */
  extent: string;
  lastUpdated: string;
  format: string;
  citationPrefix: string;
  /** ordered citation ids aligned to markdown sections */
  citationIds: string[];
  usedByPersonas: string[];
  topics: string[];
}

/** A parsed section of a document. */
export interface DocumentSection {
  documentId: string;
  source: string;
  sectionTitle: string;
  excerpt: string;
  category: string;
  citationId: string;
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
