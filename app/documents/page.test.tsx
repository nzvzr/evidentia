// @vitest-environment jsdom

import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DocumentsPage from "./page";

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const tenantCorpus = {
  enabled: true,
  generationEnabled: true,
  acceptedExtensions: [".md", ".txt"],
  maxFileBytes: 2 * 1024 * 1024,
};

function ingestion(overrides: Record<string, unknown> = {}) {
  return {
    status: "ready",
    stage: "ready",
    stageKind: "finalize",
    identity: "final",
    finalized: true,
    generationEligible: true,
    versionNo: 2,
    filename: "tenant-policy.md",
    detectedFormat: "markdown",
    byteSize: 1536,
    sectionCount: 12,
    errorCode: null,
    errorMessage: null,
    updatedAt: "2026-07-20T10:00:00Z",
    sourceType: "upload",
    ...overrides,
  };
}

function tenantDocument(id: string, title: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    companyId: "company-1",
    title,
    type: "MD",
    category: "Uploaded",
    createdAt: "2026-07-20T10:00:00Z",
    metadata: null,
    ingestion: ingestion(overrides),
  };
}

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function renderPage() {
  return render(
    <StrictMode>
      <DocumentsPage />
    </StrictMode>,
  );
}

describe("DocumentsPage tenant corpus", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders only real tenant documents and truthful corpus statistics", async () => {
    fetchMock.mockResolvedValue(
      response(200, {
        tenantCorpus,
        documents: [
          tenantDocument("doc-ready", "Tenant Access Policy"),
          {
            id: "bundled-row",
            title: "Security & Compliance Whitepaper",
            type: "PDF",
          },
        ],
      }),
    );

    renderPage();
    await flush();

    expect(screen.getByText("Tenant Access Policy")).toBeTruthy();
    expect(screen.queryByText("Security & Compliance Whitepaper")).toBeNull();
    expect(screen.queryByText(/sample corpus/i)).toBeNull();
    expect(screen.getAllByText("1").length).toBeGreaterThan(0);
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("Citation-ready")).toBeTruthy();
  });

  it("shows an explicit disabled state and never offers a local upload fallback", async () => {
    fetchMock.mockResolvedValue(response(200, { documents: [] }));

    renderPage();
    await flush();

    expect(screen.getByText("Tenant document corpus disabled")).toBeTruthy();
    expect(screen.getByRole("button", { name: /upload document/i })).toHaveProperty("disabled", true);
    expect(screen.queryByText(/processed locally/i)).toBeNull();
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("shows unavailable when the authenticated document API fails", async () => {
    fetchMock.mockResolvedValue(response(503, { code: "backend_unavailable" }));

    renderPage();
    await flush();

    expect(screen.getByText("Document service unavailable")).toBeTruthy();
    expect(screen.getByText(/No local or bundled corpus was substituted/)).toBeTruthy();
  });

  it("keeps processing, finalization, retry, new-version, and remove actions on tenant rows", async () => {
    fetchMock.mockResolvedValue(
      response(200, {
        tenantCorpus,
        documents: [
          tenantDocument("doc-processing", "Processing Policy", {
            status: "processing",
            stage: "classifying",
            identity: null,
            finalized: false,
            generationEligible: false,
          }),
          tenantDocument("doc-finalize", "Needs Finalization", {
            stageKind: "ingest",
            identity: "transitional",
            finalized: false,
            generationEligible: false,
          }),
          tenantDocument("doc-failed", "Failed Policy", {
            status: "failed",
            stage: "failed",
            generationEligible: false,
            errorMessage: "Parser failed",
          }),
        ],
      }),
    );

    renderPage();
    await flush();

    expect(screen.getByText("Classifying")).toBeTruthy();
    expect(screen.getByText("Awaiting finalization")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Finalize" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "New version" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(3);
  });

  it("uploads through the authenticated multipart tenant route", async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/documents/upload" && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        return response(202, { documentId: "doc-new" });
      }
      return response(200, { tenantCorpus, documents: [] });
    });

    const { container } = renderPage();
    await flush();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["# Tenant policy"], "tenant-policy.md", { type: "text/markdown" })] },
    });
    await flush();

    expect(fetchMock.mock.calls.some(([url]) => url === "/api/documents/upload")).toBe(true);
    expect(screen.getByText("Upload accepted — processing has started.")).toBeTruthy();
  });
});
