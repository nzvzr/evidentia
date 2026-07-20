// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvidentiaReport } from "@/lib/types";
import ReportsPage from "./page";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  fetchReports: vi.fn(),
  fetchClaims: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/reportsApi", () => ({
  fetchBackendReports: mocks.fetchReports,
  fetchReportClaimAudit: mocks.fetchClaims,
}));

const legacyReport: EvidentiaReport = {
  id: "legacy-report",
  company: "Legacy Tenant",
  market: "EMEA",
  persona: "Support Lead",
  category: "Support",
  generatedAt: "2026-07-20T10:00:00Z",
  confidence: 87,
  summary: "Persisted legacy report.",
  topFinding: "Review the existing workflow.",
  generationMode: "deterministic",
  llmProvider: "none",
  agentSteps: [],
  personaBrief: {
    title: "Support Lead",
    description: "Owns support operations.",
    goals: [],
    priorities: [],
    relevantTopics: [],
    riskFocus: [],
    outputStyle: "Cited",
    isCustom: false,
  },
  workflowSteps: [{
    step: 1,
    title: "Review workflow",
    description: "Review the persisted workflow.",
    whyItMatters: "Keeps operations current.",
    expectedOutput: "Review complete",
    evidenceCode: "LEGACY-1",
  }],
  risks: [],
  citations: [],
  metrics: {
    documentsAnalyzed: 2,
    passagesIndexed: 10,
    citationsUsed: 0,
    risksFlagged: 0,
    confidence: 87,
    personaRelevanceScore: 85,
    workflowCompleteness: 90,
    citationCoverage: 0,
    complianceSensitivity: "Low",
    documentRelevance: [],
  },
  suggestedActions: [{ title: "Complete review", detail: "Confirm the persisted workflow." }],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ReportsPage", () => {
  it("keeps a legacy null-audit report's persisted score and normal access", async () => {
    mocks.fetchReports.mockResolvedValue([legacyReport]);
    mocks.fetchClaims.mockResolvedValue(null);

    render(<ReportsPage />);

    await waitFor(() => expect(screen.getByText("87%")).toBeTruthy());
    expect(screen.queryByText("No supported claims", { exact: false })).toBeNull();
    expect(screen.getByText("READY")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "View report" }));
    expect(mocks.push).toHaveBeenCalledWith("/reports/legacy-report");
  });
});
