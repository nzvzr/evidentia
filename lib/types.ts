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
  exportStatus: string;
  templateType: string;
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

export interface Citation {
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

export interface WorkflowStep {
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
  steps: WorkflowStep[];
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
