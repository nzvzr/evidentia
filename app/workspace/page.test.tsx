// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PENDING_RUN_KEY } from "@/lib/pendingRun";
import { WORKSPACE_STORAGE_KEY } from "@/lib/useWorkspace";
import WorkspacePage from "./page";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  useTenantDocuments: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/AppShell", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/tenantDocuments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/tenantDocuments")>();
  return { ...actual, useTenantDocuments: mocks.useTenantDocuments };
});

function document(id: string, title: string, ingestion: Record<string, unknown>) {
  return {
    id,
    title,
    type: "MD",
    category: "Uploaded",
    createdAt: "2026-07-20T10:00:00Z",
    metadata: null,
    ingestion: {
      status: "ready",
      stage: "ready",
      stageKind: "finalize",
      identity: "final",
      finalized: true,
      generationEligible: true,
      versionNo: 2,
      filename: `${id}.md`,
      detectedFormat: "markdown",
      byteSize: 1000,
      sectionCount: 7,
      errorCode: null,
      errorMessage: null,
      updatedAt: "2026-07-20T10:00:00Z",
      sourceType: "upload",
      ...ingestion,
    },
  };
}

function hookResult(documents: ReturnType<typeof document>[]) {
  return {
    documents,
    corpus: {
      enabled: true,
      generationEnabled: true,
      acceptedExtensions: [".md", ".txt"],
      maxFileBytes: 2_000_000,
    },
    corpusEnabled: true,
    loadError: false,
    hydrated: true,
  };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("WorkspacePage tenant selection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mocks.push.mockReset();
  });

  afterEach(() => cleanup());

  it("lists only ready, finalized, generation-eligible tenant documents", async () => {
    mocks.useTenantDocuments.mockReturnValue(
      hookResult([
        document("doc-ready", "Tenant Ready Policy", {}),
        document("doc-processing", "Processing Policy", {
          status: "processing",
          stage: "classifying",
          identity: null,
          finalized: false,
          generationEligible: false,
        }),
        document("doc-transitional", "Awaiting Finalization", {
          identity: "transitional",
          finalized: false,
          generationEligible: false,
        }),
      ]),
    );

    render(<WorkspacePage />);
    await flush();

    expect(screen.getByText("Tenant Ready Policy")).toBeTruthy();
    expect(screen.queryByText("Processing Policy")).toBeNull();
    expect(screen.queryByText("Awaiting Finalization")).toBeNull();
    expect(screen.queryByText("Security & Compliance Whitepaper")).toBeNull();
    expect(screen.getByText("0 of 1 selected")).toBeTruthy();
  });

  it("writes only the selected real tenant id and starts the authenticated running flow", async () => {
    mocks.useTenantDocuments.mockReturnValue(
      hookResult([document("doc-real-42", "Tenant Operations Policy", {})]),
    );

    render(<WorkspacePage />);
    await flush();
    fireEvent.click(screen.getByText("Tenant Operations Policy"));
    fireEvent.click(screen.getByRole("button", { name: /Run workflow/ }));

    const pending = JSON.parse(String(window.localStorage.getItem(PENDING_RUN_KEY)));
    expect(pending.input.selectedDocumentIds).toEqual(["doc-real-42"]);
    expect(mocks.push).toHaveBeenCalledWith("/running");
  });

  it("disables generation and links to Documents when no eligible corpus exists", async () => {
    mocks.useTenantDocuments.mockReturnValue(
      hookResult([
        document("doc-processing", "Still Processing", {
          status: "processing",
          stage: "sectioning",
          identity: null,
          finalized: false,
          generationEligible: false,
        }),
      ]),
    );

    render(<WorkspacePage />);
    await flush();

    expect(screen.getByRole("button", { name: /Run workflow/ })).toHaveProperty("disabled", true);
    expect(screen.getAllByRole("button", { name: /Documents/ }).length).toBeGreaterThan(0);
  });

  it("ignores stale bundled selections from both old and current storage keys", async () => {
    window.localStorage.setItem(
      "evidentia:workspace",
      JSON.stringify({ picked: ["d1", "d8"], market: "EMEA", persona: "architect", custom: "" }),
    );
    window.localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({ picked: ["d1", "security-compliance-whitepaper"], market: "EMEA", persona: "architect", custom: "" }),
    );
    mocks.useTenantDocuments.mockReturnValue(
      hookResult([document("doc-real", "Tenant Policy", {})]),
    );

    render(<WorkspacePage />);
    await flush();

    expect(screen.getByText("0 of 1 selected")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Run workflow/ })).toHaveProperty("disabled", true);
  });
});
