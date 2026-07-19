// @vitest-environment jsdom

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { generateReportForId } from "@/data/demoReports";
import type { ReportSourceAudit } from "@/lib/types";
import ReportDetailPage from "./page";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  fetchReport: vi.fn(),
  fetchAudit: vi.fn(),
  fetchFeedback: vi.fn(),
  putReportFeedback: vi.fn(),
  putItemFeedback: vi.fn(),
  putCitationFeedback: vi.fn(),
  session: {
    user: { id: "user-a" },
    activeCompany: { id: "company-a" },
    status: "authenticated",
  },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "report-1" }),
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/SessionProvider", () => ({
  useSession: () => mocks.session,
}));

vi.mock("@/lib/reportsApi", () => ({
  fetchBackendReport: mocks.fetchReport,
  fetchReportSourceAudit: mocks.fetchAudit,
  fetchReportFeedback: mocks.fetchFeedback,
  putReportFeedback: mocks.putReportFeedback,
  putItemFeedback: mocks.putItemFeedback,
  putCitationFeedback: mocks.putCitationFeedback,
}));

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  mocks.session.user.id = "user-a";
  mocks.session.activeCompany.id = "company-a";
  mocks.fetchFeedback.mockResolvedValue({ report: null, items: [], citations: [] });
  mocks.putReportFeedback.mockResolvedValue(true);
  mocks.putItemFeedback.mockResolvedValue(true);
  mocks.putCitationFeedback.mockResolvedValue(true);
});

describe("ReportDetailPage source truth", () => {
  it("renders tenant citation bindings and deterministic audit metadata", async () => {
    const report = { ...generateReportForId("report-1"), generationMode: "deterministic" as const };
    const citation = report.citations[0];
    const audit: ReportSourceAudit = {
      corpusMode: "tenant",
      corpusSnapshotDigest: "tcs1:" + "a".repeat(64),
      retrievalEngineVersion: "tenant-lexical-v1",
      orchestratorVersion: "evidentia-orchestrator-v1",
      executionMode: "deterministic",
      llmProvider: "none",
      llmModel: null,
      sourceVersionCount: 1,
      evidenceSectionCount: 1,
      generationStatus: "completed",
      sourceVersions: [{
        documentId: "doc-1",
        documentVersionId: "version-exact-2",
        versionNo: 2,
        manifestSha256: "b".repeat(64),
        finalizationTargetDigest: "cft1:" + "c".repeat(64),
        position: 0,
      }],
      evidenceBindings: [{
        documentId: "doc-1",
        documentVersionId: "version-exact-2",
        documentTitle: "Tenant policy",
        originalFilename: "policy.md",
        sectionOrdinal: 3,
        headingPath: ["Policy", "Access"],
        sectionTitle: citation.section,
        anchorId: "anchor-1",
        citationId: citation.id,
        sectionSignature: "d".repeat(64),
        retrievalRank: 1,
        retrievalScore: 9,
        selectedForPrompt: true,
        citedInFinal: true,
        excerpt: citation.excerpt,
      }],
    };
    mocks.fetchReport.mockResolvedValue(report);
    mocks.fetchAudit.mockResolvedValue(audit);

    render(<ReportDetailPage />);
    await flush();

    expect(screen.getByText("DETERMINISTIC")).toBeTruthy();
    expect(screen.getByText("TENANT CORPUS")).toBeTruthy();
    expect(screen.getByText("VERSION version-exact-2 · SECTION 4")).toBeTruthy();
    expect(screen.getByText("SOURCE AUDIT")).toBeTruthy();
    expect(screen.getByText("RETRIEVAL tenant-lexical-v1")).toBeTruthy();
    expect(screen.getByText(citation.excerpt, { exact: false })).toBeTruthy();
  });

  it("keeps an old migrated demo report readable and labels it as sample corpus", async () => {
    mocks.fetchReport.mockResolvedValue(generateReportForId("legacy-report"));
    mocks.fetchAudit.mockResolvedValue({
      corpusMode: "demo",
      corpusSnapshotDigest: null,
      retrievalEngineVersion: null,
      orchestratorVersion: null,
      executionMode: "deterministic",
      llmProvider: null,
      llmModel: null,
      sourceVersionCount: 0,
      evidenceSectionCount: 0,
      generationStatus: "completed",
      sourceVersions: [],
      evidenceBindings: [],
    });

    render(<ReportDetailPage />);
    await flush();

    expect(screen.getByText("SAMPLE CORPUS")).toBeTruthy();
    expect(screen.getByText("SOURCE AUDIT")).toBeTruthy();
    expect(screen.queryByText(/VERSION version-exact/)).toBeNull();
  });

  it("never guesses sample corpus when audit metadata is unavailable", async () => {
    mocks.fetchReport.mockResolvedValue(generateReportForId("unknown-corpus"));
    mocks.fetchAudit.mockResolvedValue(null);

    render(<ReportDetailPage />);
    await flush();

    expect(screen.getByText("CORPUS UNAVAILABLE")).toBeTruthy();
    expect(screen.queryByText("SAMPLE CORPUS")).toBeNull();
  });

  it("clears tenant feedback state when the account scope changes", async () => {
    const report = generateReportForId("report-1");
    mocks.fetchReport.mockResolvedValue(report);
    mocks.fetchAudit.mockResolvedValue(null);
    mocks.fetchFeedback.mockResolvedValueOnce({
      report: { verdict: "correct_useful", privateText: "Tenant A note" },
      items: [],
      citations: [],
    }).mockResolvedValueOnce({ report: null, items: [], citations: [] });

    const view = render(<ReportDetailPage />);
    await flush();
    expect(screen.getByRole("button", { name: "Correct & useful" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByLabelText("Private feedback note")).toHaveProperty("value", "Tenant A note");

    mocks.session.user.id = "user-b";
    mocks.session.activeCompany.id = "company-b";
    view.rerender(<ReportDetailPage />);
    expect(screen.queryByText("Tenant A note")).toBeNull();
    await flush();

    expect(screen.getByRole("button", { name: "Correct & useful" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByLabelText("Private feedback note")).toHaveProperty("value", "");
    expect(mocks.fetchFeedback).toHaveBeenCalledTimes(2);
  });
});
