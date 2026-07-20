// @vitest-environment jsdom

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EvidentiaReport, ReportSourceAudit } from "@/lib/types";
import PrintPlaybookPage from "./page";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  fetchReport: vi.fn(),
  fetchAudit: vi.fn(),
  fetchClaims: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "report-1" }),
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/Logo", () => ({ default: () => <span>Evidentia</span> }));
vi.mock("@/lib/reportsApi", () => ({
  fetchBackendReport: mocks.fetchReport,
  fetchReportSourceAudit: mocks.fetchAudit,
  fetchReportClaimAudit: mocks.fetchClaims,
}));

const report = {
  id: "report-1", company: "Tenant", market: "APAC", persona: "Support Agent",
  category: "Support", generatedAt: "2026-07-20T10:00:00Z", confidence: 84,
  summary: "No claims met the support threshold.", topFinding: "",
  generationMode: "deterministic", llmProvider: "none", agentSteps: [],
  personaBrief: {
    title: "Support Agent", description: "Configured support role.", goals: [], priorities: ["Accuracy"],
    relevantTopics: [], riskFocus: [], outputStyle: "Cited", isCustom: false,
  },
  workflowSteps: [], risks: [], suggestedActions: [],
  citations: [{ id: "SRC-1", source: "Report source", section: "Report section", excerpt: "Stale excerpt", whyItMatters: "Audit only" }],
  metrics: {
    documentsAnalyzed: 1, passagesIndexed: 410, citationsUsed: 1, risksFlagged: 0, confidence: 84,
    personaRelevanceScore: 82, workflowCompleteness: 80, citationCoverage: 73,
    complianceSensitivity: "Moderate", documentRelevance: [],
  },
} as EvidentiaReport;

const audit: ReportSourceAudit = {
  corpusMode: "tenant", corpusSnapshotDigest: "tcs1:" + "a".repeat(64),
  retrievalEngineVersion: "tenant-lexical-v1", orchestratorVersion: "orchestrator-v1",
  executionMode: "deterministic", llmProvider: "none", llmModel: null,
  sourceVersionCount: 1, evidenceSectionCount: 29, generationStatus: "completed",
  sourceVersions: [{ documentId: "doc-1", documentVersionId: "version-3", versionNo: 3, manifestSha256: "b".repeat(64), finalizationTargetDigest: "cft1:" + "c".repeat(64), position: 0 }],
  evidenceBindings: [{
    documentId: "doc-1", documentVersionId: "version-3", documentTitle: "Frozen source title",
    originalFilename: "source.md", sectionOrdinal: 2, headingPath: ["Support", "Escalation"],
    sectionTitle: "Escalation", anchorId: "anchor-1", citationId: "SRC-1", sectionSignature: "d".repeat(64),
    retrievalRank: 1, retrievalScore: 9, selectedForPrompt: true, citedInFinal: true,
    excerpt: "The full frozen source excerpt.",
  }],
};

const analyticalReport: EvidentiaReport = {
  ...report,
  workflowSteps: [{ step: 1, title: "Review escalation", description: "Review it", whyItMatters: "Support", expectedOutput: "Decision", evidenceCode: "SRC-1" }],
  risks: [{ severity: "Medium", title: "Escalation gap", description: "Gap", businessImpact: "Delay", evidenceCode: "SRC-1", recommendedFix: "Update", owner: "Support" }],
  suggestedActions: [{ title: "Update escalation", detail: "Use the cited source." }],
};

function unboundAudit(corpusMode: unknown): ReportSourceAudit {
  return {
    ...audit,
    corpusMode,
    sourceVersions: [],
    sourceVersionCount: 0,
    evidenceSectionCount: 0,
    evidenceBindings: [],
  } as unknown as ReportSourceAudit;
}

const acceptedClaims = {
  claimEngineEnabled: true,
  candidates: [{ candidateId: "accepted", appearedInFinal: true, decision: { status: "accepted" } }],
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  mocks.fetchAudit.mockResolvedValue(audit);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("PrintPlaybookPage", () => {
  it("prints only honest compact sections for zero accepted claims", async () => {
    mocks.fetchReport.mockResolvedValue(report);
    mocks.fetchClaims.mockResolvedValue({
      claimEngineEnabled: true,
      candidates: [{ candidateId: "rejected", appearedInFinal: false, decision: { status: "rejected" } }],
    });

    render(<PrintPlaybookPage />);
    await flush();

    expect(screen.getByText("No claims were sufficiently supported")).toBeTruthy();
    expect(screen.getByText("CONFIGURED PERSONA CONTEXT")).toBeTruthy();
    expect(screen.getByText("Frozen source title")).toBeTruthy();
    expect(screen.getByText("SOURCE AUDIT & PROVENANCE")).toBeTruthy();
    expect(screen.queryByText("RECOMMENDED WORKFLOW")).toBeNull();
    expect(screen.queryByText("RISK REGISTER & EVIDENCE")).toBeNull();
    expect(screen.queryByText("TOP RECOMMENDATIONS")).toBeNull();
    expect(screen.queryByText("IMPLEMENTATION CHECKLIST")).toBeNull();
    expect(screen.queryByText("REVIEW OWNER")).toBeNull();
    expect(screen.queryByText("NEXT REVIEW DATE")).toBeNull();
    expect(screen.queryByText("84%")).toBeNull();
  });

  it("preserves analytical sections for a non-zero report", async () => {
    mocks.fetchReport.mockResolvedValue(analyticalReport);
    mocks.fetchClaims.mockResolvedValue(acceptedClaims);

    render(<PrintPlaybookPage />);
    await flush();

    expect(screen.getByText("RECOMMENDED WORKFLOW")).toBeTruthy();
    expect(screen.getByText("RISK REGISTER & EVIDENCE")).toBeTruthy();
    expect(screen.getByText(/TOP RECOMMENDATIONS/)).toBeTruthy();
    expect(screen.getByText("PERSISTED ACTION CHECKLIST")).toBeTruthy();
  });

  it("allows the report-local citation excerpt for a demo corpus", async () => {
    mocks.fetchReport.mockResolvedValue(analyticalReport);
    mocks.fetchAudit.mockResolvedValue(unboundAudit("demo"));
    mocks.fetchClaims.mockResolvedValue(acceptedClaims);

    render(<PrintPlaybookPage />);
    await flush();

    expect(screen.getByText("Stale excerpt", { exact: false })).toBeTruthy();
    expect(screen.queryByText("Frozen source binding unavailable for this citation.", { exact: false })).toBeNull();
  });

  it.each(["tenant", undefined, "future-corpus"])(
    "does not use the report-local citation excerpt for corpus mode %s",
    async (corpusMode) => {
      mocks.fetchReport.mockResolvedValue(analyticalReport);
      mocks.fetchAudit.mockResolvedValue(unboundAudit(corpusMode));
      mocks.fetchClaims.mockResolvedValue(acceptedClaims);

      render(<PrintPlaybookPage />);
      await flush();

      expect(screen.queryByText("Stale excerpt", { exact: false })).toBeNull();
      expect(screen.getByText("Frozen source binding unavailable for this citation.", { exact: false })).toBeTruthy();
      cleanup();
    },
  );
});
